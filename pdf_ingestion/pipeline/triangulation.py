"""Table triangulation engine.

Compares pdfplumber and camelot table outputs cell-by-cell to produce a
disagreement score and routing verdict. Auto-writes feedback records on
soft_flag and hard_flag verdicts.
"""

from __future__ import annotations

from difflib import SequenceMatcher

import structlog

from pipeline.models import TriangulationResult

logger = structlog.get_logger()

# Fuzzy matching threshold for cell comparison
CELL_FUZZY_THRESHOLD = 0.90


def triangulate_table(
    pdfplumber_table: dict[str, object],
    camelot_table: dict[str, object],
    job_id: str | None = None,
    tenant_id: str | None = None,
) -> TriangulationResult:
    """Compare pdfplumber and camelot table outputs and produce a verdict.

    Scoring rules:
    - Shape mismatch → score 1.0, hard_flag
    - Score < 0.10 → agreement, pdfplumber wins
    - Score 0.10–0.40 → soft_flag, pdfplumber wins
    - Score ≥ 0.40 → hard_flag, vlm_required

    Auto-writes a feedback record on soft_flag or hard_flag.

    Args:
        pdfplumber_table: Table dict from pdfplumber extraction.
        camelot_table: Table dict from camelot extraction.
        job_id: Optional job ID for feedback record.
        tenant_id: Optional tenant ID for feedback record.

    Returns:
        TriangulationResult with score, verdict, and winner.
    """
    score = compute_cell_disagreement(pdfplumber_table, camelot_table)

    methods = ["pdfplumber", "camelot"]

    if score < 0.10:
        result = TriangulationResult(
            disagreement_score=score,
            verdict="agreement",
            winner="pdfplumber",
            methods=methods,
            detail="High agreement between extraction methods.",
        )
    elif score < 0.40:
        result = TriangulationResult(
            disagreement_score=score,
            verdict="soft_flag",
            winner="pdfplumber",
            methods=methods,
            detail="Moderate disagreement between extraction methods.",
        )
    else:
        result = TriangulationResult(
            disagreement_score=score,
            verdict="hard_flag",
            winner="vlm_required",
            methods=methods,
            detail="High disagreement between extraction methods — VLM review required.",
        )

    # Log triangulation result
    table_id = pdfplumber_table.get("table_id", "unknown")
    logger.info(
        "triangulation.result",
        table_id=table_id,
        score=score,
        verdict=result.verdict,
        winner=result.winner,
        job_id=job_id,
    )

    # Auto-write feedback record on soft_flag or hard_flag
    if result.verdict in ("soft_flag", "hard_flag"):
        _write_feedback_record(
            table_id=str(table_id),
            score=score,
            verdict=result.verdict,
            job_id=job_id,
            tenant_id=tenant_id,
        )

    return result


def compute_cell_disagreement(
    t1: dict[str, object],
    t2: dict[str, object],
) -> float:
    """Compute cell-by-cell disagreement score between two tables.

    Uses fuzzy matching (SequenceMatcher ratio >= 0.90) for cell comparison.
    Shape mismatch returns 1.0 immediately.

    Args:
        t1: First table dict (pdfplumber format).
        t2: Second table dict (camelot format).

    Returns:
        Disagreement score in [0.0, 1.0].
    """
    headers1 = _get_headers(t1)
    headers2 = _get_headers(t2)
    rows1 = _get_rows(t1)
    rows2 = _get_rows(t2)

    # Include headers as a row for comparison
    all_rows1 = [headers1] + rows1
    all_rows2 = [headers2] + rows2

    # Shape mismatch check
    num_rows1 = len(all_rows1)
    num_rows2 = len(all_rows2)
    num_cols1 = len(headers1) if headers1 else (len(all_rows1[0]) if all_rows1 else 0)
    num_cols2 = len(headers2) if headers2 else (len(all_rows2[0]) if all_rows2 else 0)

    if num_rows1 != num_rows2 or num_cols1 != num_cols2:
        return 1.0

    total_cells = num_rows1 * num_cols1
    if total_cells == 0:
        return 0.0

    mismatches = 0
    for r in range(num_rows1):
        row1 = all_rows1[r] if r < len(all_rows1) else []
        row2 = all_rows2[r] if r < len(all_rows2) else []

        for c in range(num_cols1):
            v1 = _normalise_cell(row1[c] if c < len(row1) else "")
            v2 = _normalise_cell(row2[c] if c < len(row2) else "")

            if not _fuzzy_match(v1, v2, CELL_FUZZY_THRESHOLD):
                mismatches += 1

    return mismatches / total_cells


def _get_headers(table: dict[str, object]) -> list[str]:
    """Extract headers from a table dict."""
    headers = table.get("headers", [])
    if isinstance(headers, list):
        return [str(h) for h in headers]
    return []


def _get_rows(table: dict[str, object]) -> list[list[str]]:
    """Extract rows from a table dict."""
    rows = table.get("rows", [])
    if isinstance(rows, list):
        return [[str(cell) for cell in row] if isinstance(row, list) else [] for row in rows]
    return []


def _normalise_cell(value: str) -> str:
    """Normalise a cell value for comparison.

    Strips whitespace, lowercases, and removes common formatting differences.
    """
    if value is None:
        return ""
    return str(value).strip().lower()


def _fuzzy_match(v1: str, v2: str, threshold: float) -> bool:
    """Check if two strings match above the fuzzy threshold.

    Uses difflib.SequenceMatcher ratio for comparison.
    Empty strings matching empty strings count as a match.
    """
    if v1 == v2:
        return True
    if not v1 and not v2:
        return True
    ratio = SequenceMatcher(None, v1, v2).ratio()
    return ratio >= threshold


def _write_feedback_record(
    table_id: str,
    score: float,
    verdict: str,
    job_id: str | None = None,
    tenant_id: str | None = None,
) -> None:
    """Write a feedback record for triangulation flags.

    This is a placeholder that logs the event. In production, this would
    write to the feedback table in the database.

    Args:
        table_id: The table identifier.
        score: The disagreement score.
        verdict: The triangulation verdict.
        job_id: Optional job ID.
        tenant_id: Optional tenant ID.
    """
    logger.info(
        "triangulation.feedback_written",
        table_id=table_id,
        score=score,
        verdict=verdict,
        job_id=job_id,
        tenant_id=tenant_id,
        source="triangulation",
    )
