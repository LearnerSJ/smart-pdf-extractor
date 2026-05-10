"""Camelot table extractor — second rail for triangulation.

Extracts tables using camelot-py with lattice mode first (ruled tables),
falling back to stream mode (whitespace-delimited) if lattice returns zero tables.

Output format is consistent with pdfplumber tables from digital.py.
"""

from __future__ import annotations

import tempfile
from typing import Any

try:
    import camelot  # type: ignore[import-untyped]
    CAMELOT_AVAILABLE = True
except ImportError:
    CAMELOT_AVAILABLE = False
import structlog

logger = structlog.get_logger()


def extract_tables_camelot(
    pdf_bytes: bytes,
    page_number: int,
) -> list[dict[str, object]]:
    """Extract tables from a single PDF page using camelot-py.

    Tries lattice mode first (for ruled/bordered tables). If lattice returns
    zero tables, falls back to stream mode (whitespace-delimited tables).

    Args:
        pdf_bytes: Raw PDF file bytes.
        page_number: 1-based page number to extract from.

    Returns:
        List of table dicts with same structure as pdfplumber tables in digital.py:
        {
            "table_id": str,
            "page_number": int,
            "headers": list[str],
            "rows": list[list[str]],
            "bbox": list[float],
            "source": "camelot",
            "flavour": "lattice" | "stream",
            "provenance": {...},
        }
    """
    tables: list[dict[str, object]] = []

    if not CAMELOT_AVAILABLE:
        logger.warning("camelot.not_installed", page_number=page_number)
        return tables

    # camelot requires a file path, so write to a temp file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        tmp_path = tmp.name

        # Try lattice mode first
        flavour_used = "lattice"
        try:
            camelot_tables = camelot.read_pdf(
                tmp_path,
                pages=str(page_number),
                flavor="lattice",
            )
        except Exception as e:
            logger.warning(
                "camelot.lattice_failed",
                page_number=page_number,
                error=str(e),
            )
            camelot_tables = None

        # Fall back to stream mode if lattice returned zero tables
        if camelot_tables is None or len(camelot_tables) == 0:
            flavour_used = "stream"
            try:
                camelot_tables = camelot.read_pdf(
                    tmp_path,
                    pages=str(page_number),
                    flavor="stream",
                )
            except Exception as e:
                logger.warning(
                    "camelot.stream_failed",
                    page_number=page_number,
                    error=str(e),
                )
                return tables

    if camelot_tables is None or len(camelot_tables) == 0:
        return tables

    for idx, ct in enumerate(camelot_tables):
        table_data = _convert_camelot_table(ct, page_number, idx, flavour_used)
        if table_data is not None:
            tables.append(table_data)
            logger.info(
                "camelot.table_extracted",
                page_number=page_number,
                table_index=idx,
                flavour=flavour_used,
                rows=len(table_data.get("rows", [])),
            )

    return tables


def _convert_camelot_table(
    ct: Any,
    page_number: int,
    idx: int,
    flavour: str,
) -> dict[str, object] | None:
    """Convert a camelot TableList entry to the standard table dict format.

    Args:
        ct: A camelot Table object.
        page_number: 1-based page number.
        idx: Table index on the page.
        flavour: "lattice" or "stream".

    Returns:
        Table dict matching pdfplumber format, or None if table is empty.
    """
    try:
        df = ct.df
        if df.empty:
            return None

        # First row as headers, rest as data rows
        all_rows = df.values.tolist()
        headers: list[str] = [str(cell) if cell is not None else "" for cell in all_rows[0]]
        rows: list[list[str]] = [
            [str(cell) if cell is not None else "" for cell in row]
            for row in all_rows[1:]
        ]

        # Extract bounding box from camelot table
        # camelot uses (x0, y0, x1, y1) in PDF coordinates
        bbox: list[float] = []
        if hasattr(ct, "_bbox") and ct._bbox:
            bbox = list(ct._bbox)
        elif hasattr(ct, "cells") and ct.cells:
            # Fallback: compute from cells
            bbox = [0.0, 0.0, 0.0, 0.0]
        else:
            bbox = [0.0, 0.0, 0.0, 0.0]

        table_data: dict[str, object] = {
            "table_id": f"page{page_number}_camelot{idx}",
            "page_number": page_number,
            "headers": headers,
            "rows": rows,
            "bbox": bbox,
            "source": "camelot",
            "flavour": flavour,
            "provenance": {
                "page": page_number,
                "bbox": bbox,
                "source": "native",
                "extraction_rule": f"camelot_{flavour}",
            },
        }
        return table_data
    except Exception as e:
        logger.warning(
            "camelot.table_conversion_failed",
            page_number=page_number,
            table_index=idx,
            error=str(e),
        )
        return None
