"""Digital page extractor using pdfplumber.

Extracts character-level text with bounding boxes, font metadata,
and tables with cell-level provenance from digital PDF pages.
"""

from __future__ import annotations

import structlog

from pipeline.models import PageOutput, Token

logger = structlog.get_logger()


def extract_digital_page(page, page_number: int) -> PageOutput:  # type: ignore[type-arg]
    """Extract text and tables from a digital PDF page.

    Uses pdfplumber to extract:
    - Character-level text with bounding boxes and font metadata
    - Tables with cell-level provenance

    Every extracted element is tagged with page number and bounding box provenance.

    Args:
        page: A pdfplumber page object.
        page_number: The 1-based page number.

    Returns:
        PageOutput with tokens, tables, and text blocks.
    """
    tokens = _extract_tokens(page, page_number)
    tables = _extract_tables(page, page_number)
    text_blocks = _extract_text_blocks(page, page_number)

    logger.info(
        "digital.extracted",
        page_number=page_number,
        token_count=len(tokens),
        table_count=len(tables),
    )

    return PageOutput(
        page_number=page_number,
        classification="DIGITAL",
        tokens=tokens,
        tables=tables,
        text_blocks=text_blocks,
    )


def _extract_tokens(page, page_number: int) -> list[Token]:  # type: ignore[type-arg]
    """Extract character-level tokens with bounding boxes and font metadata.

    Args:
        page: A pdfplumber page object.
        page_number: The 1-based page number.

    Returns:
        List of Token objects with text, bbox, and confidence.
    """
    tokens: list[Token] = []
    chars = page.chars or []

    for char in chars:
        x0 = float(char.get("x0", 0))
        top = float(char.get("top", 0))
        x1 = float(char.get("x1", 0))
        bottom = float(char.get("bottom", 0))

        token = Token(
            text=char.get("text", ""),
            bbox=(x0, top, x1, bottom),
            confidence=1.0,  # Native text has full confidence
        )
        tokens.append(token)

    return tokens


def _extract_tables(page, page_number: int) -> list[dict[str, object]]:  # type: ignore[type-arg]
    """Extract tables from a page using pdfplumber.

    Each table includes cell data and bounding box provenance.

    Args:
        page: A pdfplumber page object.
        page_number: The 1-based page number.

    Returns:
        List of table dictionaries with rows, headers, and provenance.
    """
    tables: list[dict[str, object]] = []

    try:
        page_tables = page.find_tables()
    except Exception:
        logger.warning("digital.table_extraction_failed", page_number=page_number)
        return tables

    for idx, table in enumerate(page_tables):
        try:
            extracted = table.extract()
            if not extracted:
                continue

            # First row as headers
            headers = extracted[0] if extracted else []
            rows = extracted[1:] if len(extracted) > 1 else []

            # Get table bounding box
            bbox = list(table.bbox) if hasattr(table, "bbox") and table.bbox else [0, 0, 0, 0]

            table_data: dict[str, object] = {
                "table_id": f"page{page_number}_table{idx}",
                "page_number": page_number,
                "headers": [h or "" for h in headers],
                "rows": [[cell or "" for cell in row] for row in rows],
                "bbox": bbox,
                "source": "pdfplumber",
                "provenance": {
                    "page": page_number,
                    "bbox": bbox,
                    "source": "native",
                    "extraction_rule": "pdfplumber_table",
                },
            }
            tables.append(table_data)
        except Exception:
            logger.warning(
                "digital.table_parse_failed",
                page_number=page_number,
                table_index=idx,
            )

    return tables


def _extract_text_blocks(page, page_number: int) -> list[dict[str, object]]:  # type: ignore[type-arg]
    """Extract text blocks (words) with bounding boxes.

    Args:
        page: A pdfplumber page object.
        page_number: The 1-based page number.

    Returns:
        List of text block dictionaries with text, bbox, and provenance.
    """
    text_blocks: list[dict[str, object]] = []

    try:
        words = page.extract_words() or []
    except Exception:
        return text_blocks

    for word in words:
        block: dict[str, object] = {
            "text": word.get("text", ""),
            "bbox": [
                float(word.get("x0", 0)),
                float(word.get("top", 0)),
                float(word.get("x1", 0)),
                float(word.get("bottom", 0)),
            ],
            "provenance": {
                "page": page_number,
                "bbox": [
                    float(word.get("x0", 0)),
                    float(word.get("top", 0)),
                    float(word.get("x1", 0)),
                    float(word.get("bottom", 0)),
                ],
                "source": "native",
                "extraction_rule": "pdfplumber_word",
            },
        }
        text_blocks.append(block)

    return text_blocks
