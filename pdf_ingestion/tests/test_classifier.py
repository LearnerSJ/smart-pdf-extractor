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
    """Page with coverage >= 0.80 is classified as DIGITAL."""
    # Create chars that cover 85% of the page
    # Page is 100x100 = 10000 area
    # Need chars covering 8500 area
    chars = [
        {"x0": 0, "top": 0, "x1": 100, "bottom": 85, "text": "x"}
    ]
    page = MockPage(width=100, height=100, chars=chars)
    assert classify_page(page) == "DIGITAL"


def test_classify_scanned_page():
    """Page with coverage < 0.80 is classified as SCANNED."""
    # Create chars that cover 50% of the page
    chars = [
        {"x0": 0, "top": 0, "x1": 100, "bottom": 50, "text": "x"}
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
    """Page with exactly 0.80 coverage is classified as DIGITAL."""
    # Page 100x100 = 10000 area, chars covering 8000 area
    chars = [
        {"x0": 0, "top": 0, "x1": 100, "bottom": 80, "text": "x"}
    ]
    page = MockPage(width=100, height=100, chars=chars)
    assert classify_page(page) == "DIGITAL"


def test_coverage_zero_area_page():
    """Page with zero area returns 0.0 coverage."""
    page = MockPage(width=0, height=100, chars=[{"x0": 0, "top": 0, "x1": 10, "bottom": 10, "text": "x"}])
    coverage = compute_native_text_coverage(page)
    assert coverage == 0.0
