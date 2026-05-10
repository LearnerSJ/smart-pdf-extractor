"""Base schema extractor.

Provides the abstract base class for all schema-specific extractors.
Implements shared logic: pattern-based field extraction, table extraction
by header matching, and normalisation functions.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable

from api.errors import ErrorCode
from api.models.response import (
    Abstention,
    Field,
    Provenance,
    Table,
    TableRow,
    TriangulationInfo,
)
from pipeline.models import AssembledDocument


# ─── Normalisation Functions ──────────────────────────────────────────────────


def parse_amount(raw: str) -> float:
    """Parse a monetary amount string to float.

    Strips commas, spaces, and currency symbols. Handles negative amounts
    in parentheses notation e.g. (1,234.56) → -1234.56.
    """
    cleaned = raw.strip()

    # Handle parentheses for negative amounts
    negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        negative = True
        cleaned = cleaned[1:-1]

    # Handle leading minus
    if cleaned.startswith("-"):
        negative = True
        cleaned = cleaned[1:]

    # Strip currency symbols and whitespace
    cleaned = re.sub(r"[€$£¥₹\s,]", "", cleaned)

    # Handle empty string after stripping
    if not cleaned:
        return 0.0

    value = float(cleaned)
    return -value if negative else value


def parse_date(raw: str) -> str:
    """Parse common date formats to ISO 8601 (YYYY-MM-DD).

    Supports:
    - DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
    - YYYY-MM-DD (already ISO)
    - DD Mon YYYY (e.g. 15 Jan 2024)
    - Mon DD, YYYY (e.g. Jan 15, 2024)
    """
    cleaned = raw.strip()

    # Already ISO format
    iso_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", cleaned)
    if iso_match:
        return cleaned

    # DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    dmy_match = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$", cleaned)
    if dmy_match:
        day, month, year = dmy_match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"

    # DD Mon YYYY
    formats_to_try = [
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d-%b-%Y",
        "%d/%b/%Y",
    ]
    for fmt in formats_to_try:
        try:
            dt = datetime.strptime(cleaned, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Fallback: return as-is if no format matches
    return cleaned


def normalise_iban(raw: str) -> str:
    """Normalise an IBAN by stripping spaces and converting to uppercase."""
    return re.sub(r"\s+", "", raw.strip()).upper()


# ─── Base Schema Extractor ────────────────────────────────────────────────────


class BaseSchemaExtractor(ABC):
    """Abstract base class for schema-specific extractors.

    Provides shared logic for pattern-based field extraction and
    table extraction by header matching. Subclasses implement the
    `extract()` method with schema-specific field specs.
    """

    @abstractmethod
    def extract(self, doc: AssembledDocument) -> dict:
        """Extract all fields and tables for this schema type.

        Returns a dict with keys: 'fields', 'tables', 'abstentions'.
        """
        ...

    def find_field(
        self,
        doc: AssembledDocument,
        patterns: list[str],
        label: str,
        normaliser: Callable[[str], object] | None = None,
        required: bool = True,
    ) -> Field | Abstention:
        """Search the token stream for the first pattern match.

        Patterns are tried in order; first match wins.

        Args:
            doc: The assembled document with token stream.
            patterns: Ordered list of regex patterns to try.
            label: Human-readable field name.
            normaliser: Optional function to normalise the raw match.
            required: Whether the field is required (affects abstention).

        Returns:
            Field with value and provenance, or Abstention with reason.
        """
        # Build a text representation from the token stream for regex matching
        # We search through text blocks first (word-level), then fall back to
        # concatenated token stream
        text_segments = self._build_text_segments(doc)

        for pattern in patterns:
            compiled = re.compile(pattern, re.IGNORECASE | re.MULTILINE)

            for segment in text_segments:
                match = compiled.search(segment["text"])
                if match:
                    raw_value = match.group(1) if match.lastindex else match.group(0)
                    original_string = raw_value

                    # Apply normaliser if provided
                    if normaliser is not None:
                        value = normaliser(raw_value)
                    else:
                        value = raw_value

                    return Field(
                        value=value,
                        original_string=original_string,
                        confidence=0.95,
                        vlm_used=False,
                        redaction_applied=False,
                        provenance=Provenance(
                            page=segment["page"],
                            bbox=segment["bbox"],
                            source="native",
                            extraction_rule=f"pattern:{pattern}",
                        ),
                    )

        # No pattern matched
        return Abstention(
            field=label,
            table_id=None,
            reason=ErrorCode.EXTRACTION_PATTERN_NOT_FOUND,
            detail=f"No pattern matched for field '{label}' after trying {len(patterns)} patterns",
            vlm_attempted=False,
        )

    def extract_table_by_header(
        self,
        doc: AssembledDocument,
        expected_headers: list[str],
        table_type: str,
    ) -> Table | Abstention:
        """Extract a table by fuzzy-matching expected headers.

        Searches all detected tables in the document for one whose headers
        match the expected headers using fuzzy matching.

        Args:
            doc: The assembled document with detected tables.
            expected_headers: List of expected column headers.
            table_type: Type label for the table (e.g. "transactions").

        Returns:
            Table with rows and provenance, or Abstention.
        """
        best_match: dict | None = None
        best_score = 0.0

        for table_data in doc.tables:
            headers = table_data.get("headers", [])
            if not headers:
                continue

            score = self._header_match_score(expected_headers, headers)
            if score > best_score:
                best_score = score
                best_match = table_data

        # Require at least 60% header match
        if best_match is not None and best_score >= 0.6:
            headers = best_match.get("headers", [])
            raw_rows = best_match.get("rows", [])
            page_number = best_match.get("page_number", 1)
            bbox = best_match.get("bbox", [0.0, 0.0, 0.0, 0.0])

            if isinstance(page_number, int):
                page_num = page_number
            else:
                page_num = 1

            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                bbox_list = [float(b) for b in bbox[:4]]
            else:
                bbox_list = [0.0, 0.0, 0.0, 0.0]

            # Build page range
            page_range_raw = best_match.get("page_range")
            if isinstance(page_range_raw, list) and page_range_raw:
                page_range = [int(p) for p in page_range_raw]
            else:
                page_range = [page_num]

            rows: list[TableRow] = []
            for idx, row in enumerate(raw_rows):
                if isinstance(row, list):
                    rows.append(TableRow(cells=row, row_index=idx))

            return Table(
                table_id=str(best_match.get("table_id", f"{table_type}_0")),
                type=table_type,
                page_range=page_range,
                headers=[str(h) for h in headers],
                triangulation=TriangulationInfo(
                    score=0.0,
                    verdict="agreement",
                    winner="pdfplumber",
                    methods=["pdfplumber"],
                ),
                rows=rows,
            )

        return Abstention(
            field=None,
            table_id=f"{table_type}_not_found",
            reason=ErrorCode.EXTRACTION_TABLE_ABSTAINED,
            detail=f"No table matching expected headers {expected_headers} found (best score: {best_score:.2f})",
            vlm_attempted=False,
        )

    # ─── Private Helpers ──────────────────────────────────────────────────────

    def _build_text_segments(
        self, doc: AssembledDocument
    ) -> list[dict[str, object]]:
        """Build searchable text segments from the document.

        Combines adjacent tokens into line-level segments for regex matching.
        Each segment carries page and bbox provenance.
        """
        segments: list[dict[str, object]] = []

        # First try text blocks (word-level, already ordered)
        if doc.blocks:
            # Group blocks by page and approximate line (y-coordinate)
            page_lines: dict[int, list[dict]] = {}
            for block in doc.blocks:
                page = block.get("provenance", {}).get("page", 1) if isinstance(block.get("provenance"), dict) else 1
                if page not in page_lines:
                    page_lines[page] = []
                page_lines[page].append(block)

            for page_num, blocks in sorted(page_lines.items()):
                # Group by approximate y-coordinate (within 5 units = same line)
                lines: list[list[dict]] = []
                current_line: list[dict] = []
                last_y = -999.0

                sorted_blocks = sorted(
                    blocks,
                    key=lambda b: (
                        float(b.get("bbox", [0, 0, 0, 0])[1]) if isinstance(b.get("bbox"), (list, tuple)) else 0,
                        float(b.get("bbox", [0, 0, 0, 0])[0]) if isinstance(b.get("bbox"), (list, tuple)) else 0,
                    ),
                )

                for block in sorted_blocks:
                    bbox = block.get("bbox", [0, 0, 0, 0])
                    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                        y = float(bbox[1])
                    else:
                        y = 0.0

                    if abs(y - last_y) > 5.0 and current_line:
                        lines.append(current_line)
                        current_line = []

                    current_line.append(block)
                    last_y = y

                if current_line:
                    lines.append(current_line)

                for line_blocks in lines:
                    text_parts = []
                    min_x0 = float("inf")
                    min_y0 = float("inf")
                    max_x1 = 0.0
                    max_y1 = 0.0

                    for block in line_blocks:
                        text_parts.append(str(block.get("text", "")))
                        bbox = block.get("bbox", [0, 0, 0, 0])
                        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                            min_x0 = min(min_x0, float(bbox[0]))
                            min_y0 = min(min_y0, float(bbox[1]))
                            max_x1 = max(max_x1, float(bbox[2]))
                            max_y1 = max(max_y1, float(bbox[3]))

                    line_text = " ".join(text_parts)
                    if line_text.strip():
                        segments.append({
                            "text": line_text,
                            "page": page_num,
                            "bbox": [min_x0, min_y0, max_x1, max_y1],
                        })

        # Fallback: build from token stream if no blocks
        if not segments and doc.token_stream:
            # Group tokens by approximate position into lines
            current_text = ""
            current_page = 1
            current_bbox = [0.0, 0.0, 0.0, 0.0]
            last_y = -999.0

            for token in doc.token_stream:
                if abs(token.bbox[1] - last_y) > 5.0 and current_text:
                    segments.append({
                        "text": current_text,
                        "page": current_page,
                        "bbox": current_bbox[:],
                    })
                    current_text = ""
                    current_bbox = [
                        token.bbox[0],
                        token.bbox[1],
                        token.bbox[2],
                        token.bbox[3],
                    ]

                current_text += token.text
                current_page = 1  # tokens don't carry page info directly
                if not current_text or current_bbox == [0.0, 0.0, 0.0, 0.0]:
                    current_bbox = [
                        token.bbox[0],
                        token.bbox[1],
                        token.bbox[2],
                        token.bbox[3],
                    ]
                else:
                    current_bbox[2] = max(current_bbox[2], token.bbox[2])
                    current_bbox[3] = max(current_bbox[3], token.bbox[3])

                last_y = token.bbox[1]

            if current_text:
                segments.append({
                    "text": current_text,
                    "page": current_page,
                    "bbox": current_bbox[:],
                })

        return segments

    def _header_match_score(
        self, expected: list[str], actual: list[str]
    ) -> float:
        """Compute fuzzy match score between expected and actual headers.

        Returns a score in [0.0, 1.0] representing the fraction of expected
        headers that have a close match in the actual headers.
        """
        if not expected:
            return 0.0

        matches = 0
        for exp_header in expected:
            exp_lower = exp_header.lower().strip()
            for act_header in actual:
                act_lower = str(act_header).lower().strip()
                # Exact match or substring match
                if exp_lower == act_lower or exp_lower in act_lower or act_lower in exp_lower:
                    matches += 1
                    break

        return matches / len(expected)
