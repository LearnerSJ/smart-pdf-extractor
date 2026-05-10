"""Per-page classifier.

Classifies each page as DIGITAL or SCANNED based on native text coverage.
Coverage is computed as the sum of character bounding box areas divided by
total page area. Threshold is 0.80.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()

# Classification threshold
DIGITAL_THRESHOLD = 0.80


def classify_page(page) -> str:  # type: ignore[type-arg]
    """Classify a single pdfplumber page as DIGITAL or SCANNED.

    Args:
        page: A pdfplumber page object.

    Returns:
        "DIGITAL" if native_text_coverage >= 0.80, "SCANNED" otherwise.
    """
    coverage = compute_native_text_coverage(page)

    classification = "DIGITAL" if coverage >= DIGITAL_THRESHOLD else "SCANNED"

    page_number = page.page_number if hasattr(page, "page_number") else 0

    logger.info(
        "page.classified",
        page_number=page_number,
        classification=classification,
        coverage=round(coverage, 4),
    )

    return classification


def compute_native_text_coverage(page) -> float:  # type: ignore[type-arg]
    """Compute native text coverage for a page.

    Coverage = sum of character bounding box areas / total page area.
    If the page has zero characters or zero area, returns 0.0 (SCANNED).

    Args:
        page: A pdfplumber page object with .chars and .width/.height attributes.

    Returns:
        Float in [0.0, 1.0] representing text coverage ratio.
    """
    page_width = float(page.width)
    page_height = float(page.height)
    page_area = page_width * page_height

    if page_area <= 0:
        return 0.0

    chars = page.chars
    if not chars:
        return 0.0

    # Sum character bounding box areas
    char_area_sum = 0.0
    for char in chars:
        x0 = float(char.get("x0", 0))
        y0 = float(char.get("top", 0))
        x1 = float(char.get("x1", 0))
        y1 = float(char.get("bottom", 0))

        char_width = max(0.0, x1 - x0)
        char_height = max(0.0, y1 - y0)
        char_area_sum += char_width * char_height

    coverage = char_area_sum / page_area

    # Clamp to [0.0, 1.0]
    return min(1.0, max(0.0, coverage))
