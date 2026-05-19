"""Text-based table parser for fixed-width columnar data.

Detects and extracts tables from text that uses fixed-width columns
(space-aligned) rather than bordered table structures. This handles
documents like futures/derivatives statements where pdfplumber cannot
detect table boundaries.

Strategy:
1. Detect header lines (all-caps words separated by spaces)
2. Detect separator lines (dashes/underscores)
3. Parse data rows using column positions derived from the separator
4. Merge continuation tables across pages (same headers)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()

# Pattern for separator lines (dashes, underscores, or equals, possibly with spaces)
SEPARATOR_PATTERN = re.compile(r"^[\s\-_=]{20,}$")

# Pattern for a header line (mostly uppercase words)
HEADER_PATTERN = re.compile(r"^[A-Z][A-Z\s/\-\.]{15,}$")

# Minimum number of data rows to consider it a valid table
MIN_DATA_ROWS = 3

# Maximum header line length to avoid false positives
MAX_HEADER_LINES = 2


@dataclass
class TextTable:
    """A table extracted from fixed-width text."""

    headers: list[str]
    rows: list[dict[str, str | None]]
    page_range: list[int]
    table_type: str = "transactions"
    raw_header_line: str = ""


@dataclass
class ColumnSpec:
    """Specification for a single column derived from separator positions."""

    name: str
    start: int
    end: int


def detect_text_tables(page_texts: list[str]) -> list[TextTable]:
    """Detect and extract text-based tables from a list of page texts.

    Scans each page for header + separator patterns, then extracts
    data rows using the column positions from the separator.

    Args:
        page_texts: List of text strings, one per page.

    Returns:
        List of TextTable objects with merged continuation tables.
    """
    tables: list[TextTable] = []
    current_table: TextTable | None = None
    current_columns: list[ColumnSpec] | None = None

    for page_idx, page_text in enumerate(page_texts):
        lines = page_text.split("\n")
        page_num = page_idx + 1

        i = 0
        found_table_on_page = False

        while i < len(lines):
            line = lines[i]

            # Look for separator line (indicates table structure)
            if SEPARATOR_PATTERN.match(line):
                # Check if the line above is a header
                header_line = lines[i - 1] if i > 0 else ""
                if _is_header_line(header_line):
                    columns = _parse_separator_columns(line, header_line)
                    if columns:
                        headers = [c.name for c in columns]

                        # Check if this is a continuation of the current table
                        if current_table and current_table.headers == headers:
                            # Same table continuing on new page
                            if page_num not in current_table.page_range:
                                current_table.page_range.append(page_num)
                            current_columns = columns
                            found_table_on_page = True
                            i += 1
                            continue
                        else:
                            # New table (or first table)
                            if current_table and len(current_table.rows) >= MIN_DATA_ROWS:
                                tables.append(current_table)

                            current_table = TextTable(
                                headers=headers,
                                rows=[],
                                page_range=[page_num],
                                raw_header_line=header_line,
                            )
                            current_columns = columns
                            found_table_on_page = True
                            i += 1
                            continue

            # If we're inside a table, try to parse data rows
            if current_table and current_columns and found_table_on_page:
                row = _parse_data_row(line, current_columns)
                if row:
                    current_table.rows.append(row)

            i += 1

        # If no table header found on this page but we have a current table,
        # check if the page has data rows that match the current columns
        if not found_table_on_page and current_table and current_columns:
            # Look for data rows without a header (continuation without header repeat)
            data_lines = [ln for ln in lines if _looks_like_data_row(ln)]
            if len(data_lines) > 3:
                for dl in data_lines:
                    row = _parse_data_row(dl, current_columns)
                    if row:
                        current_table.rows.append(row)
                        if page_num not in current_table.page_range:
                            current_table.page_range.append(page_num)

    # Don't forget the last table
    if current_table and len(current_table.rows) >= MIN_DATA_ROWS:
        tables.append(current_table)

    logger.info(
        "text_table_parser.complete",
        tables_found=len(tables),
        total_rows=sum(len(t.rows) for t in tables),
    )

    return tables


def _is_header_line(line: str) -> bool:
    """Check if a line looks like a table header.

    Accepts lines that are mostly uppercase words. Allows digits in headers
    (e.g. "QTY 1", "PRICE (USD)") as long as the line is predominantly
    uppercase alphabetic tokens.
    """
    stripped = line.strip()
    if not stripped or len(stripped) < 20:
        return False

    # Must have multiple space-separated tokens
    tokens = stripped.split()
    if len(tokens) < 3:
        return False

    # Most tokens should be uppercase alphabetic or contain uppercase words
    upper_count = sum(1 for t in tokens if t.isupper() and len(t) > 1)
    # Also count tokens with / like DEBIT/CREDIT
    upper_count += sum(
        1 for t in tokens if "/" in t and all(p.isupper() for p in t.split("/") if p)
    )
    # Count tokens that are uppercase with trailing punctuation (e.g. "DATE.")
    upper_count += sum(
        1
        for t in tokens
        if t.rstrip(".:()").isupper()
        and len(t.rstrip(".:()")) > 1
        and t not in [tok for tok in tokens if tok.isupper()]
    )

    # Reject lines that look like data rows (contain date patterns or amounts)
    # But allow simple numbers in headers (e.g. column numbering)
    date_pattern = re.compile(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}")
    amount_pattern = re.compile(r"\d{1,3}(,\d{3})+(\.\d{2})?")
    if date_pattern.search(stripped) or amount_pattern.search(stripped):
        return False

    return upper_count / len(tokens) >= 0.4


def _parse_separator_columns(separator: str, header_line: str) -> list[ColumnSpec] | None:
    """Parse column positions from a separator line and map to header names.

    Uses the separator line's dash groups to determine column boundaries,
    then maps header words to columns based on position overlap.
    """
    # Find column spans in the separator (groups of dashes/underscores/equals)
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(separator):
        if separator[i] in ("-", "_", "="):
            start = i
            while i < len(separator) and separator[i] in ("-", "_", "="):
                i += 1
            spans.append((start, i))
        else:
            i += 1

    if len(spans) < 3:
        return None

    # Find word positions in the header line
    header_words: list[tuple[str, int, int]] = []  # (word, start, end)
    j = 0
    while j < len(header_line):
        if header_line[j] != " ":
            word_start = j
            while j < len(header_line) and header_line[j] != " ":
                j += 1
            header_words.append((header_line[word_start:j], word_start, j))
        else:
            j += 1

    # Map header words to separator spans based on position overlap
    columns: list[ColumnSpec] = []
    for span_start, span_end in spans:
        # Find all header words that overlap with this span
        overlapping_words = []
        for word, ws, we in header_words:
            # Word overlaps with span if they share any position
            if ws < span_end and we > span_start:
                overlapping_words.append(word)

        col_name = " ".join(overlapping_words) if overlapping_words else f"Col{len(columns) + 1}"
        columns.append(ColumnSpec(name=col_name, start=span_start, end=span_end))

    # Keep all columns — do NOT merge unnamed columns into adjacent ones.
    # Previously, columns without overlapping header words were merged into
    # their neighbours, which collapsed 12-column tables down to 8.
    # Instead, retain unnamed columns with their positional label (Col1, Col2, etc.)
    # so that all data columns are preserved.
    return columns if len(columns) >= 3 else None


def _parse_data_row(line: str, columns: list[ColumnSpec]) -> dict[str, str | None] | None:
    """Parse a data row using column positions.

    Returns None if the line doesn't look like a data row.
    """
    stripped = line.strip()
    if not stripped:
        return None

    # Skip lines that are clearly not data (headers, separators, summaries)
    if SEPARATOR_PATTERN.match(line):
        return None
    if _is_header_line(stripped):
        return None

    # Skip very short lines or lines that are just labels
    if len(stripped) < 10:
        return None

    # Skip summary/total lines
    lower = stripped.lower()
    if any(kw in lower for kw in ["total", "avg long:", "avg short:", "tot comm", "page "]):
        return None

    # Extract values at column positions
    row: dict[str, str | None] = {}
    has_data = False

    for col in columns:
        if col.start < len(line):
            value = line[col.start : min(col.end, len(line))].strip()
            row[col.name] = value if value else None
            if value:
                has_data = True
        else:
            row[col.name] = None

    # Must have at least 2 non-empty values to be a valid data row
    non_empty = sum(1 for v in row.values() if v)
    if non_empty < 2:
        return None

    return row if has_data else None


def _looks_like_data_row(line: str) -> bool:
    """Quick check if a line might be a data row (has date-like patterns)."""
    stripped = line.strip()
    if not stripped or len(stripped) < 10:
        return False
    # Look for date patterns like 3/27/4 or similar
    return bool(re.search(r"\d+/\d+/\d+", stripped))
