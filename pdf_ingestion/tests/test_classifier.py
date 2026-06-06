"""Tests for pipeline/classifier.py."""

from __future__ import annotations

from pipeline.classifier import classify_page, compute_native_text_coverage


class MockPage:
    """Mock pdfplumber page for testing."""

    def __init__(self, width: float, height: float, chars: list, page_number: int = 1):
        self.width = width
        self.height = height
        self.chars = chars
        self.page_number = page_number


def test_classify_digital_page():
    """A page with real native text (coverage >= threshold) is DIGITAL.

    Typical digital text pages have glyph-area coverage of only a few percent
    (whitespace and margins dominate), so even a sparse-but-real text page must
    classify DIGITAL.
    """
    # ~3% coverage — representative of a normal text page
    chars = [
        {"x0": 0, "top": 0, "x1": 100, "bottom": 3, "text": "x"}
    ]
    page = MockPage(width=100, height=100, chars=chars)
    assert classify_page(page) == "DIGITAL"


def test_classify_scanned_page():
    """An image-only (scanned) page has negligible native text → SCANNED.

    Scanned pages carry no extractable glyphs; at most a thin stray amount well
    below the threshold.
    """
    # 0.5% coverage — below DIGITAL_THRESHOLD, e.g. a stray artefact char
    chars = [
        {"x0": 0, "top": 0, "x1": 10, "bottom": 5, "text": "x"}
    ]
    page = MockPage(width=100, height=100, chars=chars)
    assert classify_page(page) == "SCANNED"


def test_classify_zero_chars_as_scanned():
    """Page with no characters is classified as SCANNED."""
    page = MockPage(width=100, height=100, chars=[])
    assert classify_page(page) == "SCANNED"


def test_coverage_computation():
    """Coverage is correctly computed as char area / page area."""
    # Page 200x100 = 20000 area
    # One char 100x50 = 5000 area → coverage = 0.25
    chars = [
        {"x0": 10, "top": 10, "x1": 110, "bottom": 60, "text": "A"}
    ]
    page = MockPage(width=200, height=100, chars=chars)
    coverage = compute_native_text_coverage(page)
    assert abs(coverage - 0.25) < 0.001


def test_coverage_at_threshold():
    """Page with coverage exactly at DIGITAL_THRESHOLD is classified as DIGITAL."""
    from pipeline.classifier import DIGITAL_THRESHOLD

    # chars covering exactly DIGITAL_THRESHOLD of a 100x100 page
    height_at_threshold = 100 * DIGITAL_THRESHOLD
    chars = [
        {"x0": 0, "top": 0, "x1": 100, "bottom": height_at_threshold, "text": "x"}
    ]
    page = MockPage(width=100, height=100, chars=chars)
    assert classify_page(page) == "DIGITAL"


def test_coverage_zero_area_page():
    """Page with zero area returns 0.0 coverage."""
    page = MockPage(width=0, height=100, chars=[{"x0": 0, "top": 0, "x1": 10, "bottom": 10, "text": "x"}])
    coverage = compute_native_text_coverage(page)
    assert coverage == 0.0
