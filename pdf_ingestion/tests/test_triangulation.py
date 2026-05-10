"""Tests for the table triangulation engine."""

from __future__ import annotations

from pipeline.triangulation import (
    compute_cell_disagreement,
    triangulate_table,
    _fuzzy_match,
    _normalise_cell,
)


class TestComputeCellDisagreement:
    """Tests for compute_cell_disagreement()."""

    def test_identical_tables_return_zero(self) -> None:
        """Identical tables should have 0.0 disagreement."""
        t1 = {
            "headers": ["Name", "Amount", "Date"],
            "rows": [["Alice", "100.00", "2024-01-01"], ["Bob", "200.00", "2024-01-02"]],
        }
        t2 = {
            "headers": ["Name", "Amount", "Date"],
            "rows": [["Alice", "100.00", "2024-01-01"], ["Bob", "200.00", "2024-01-02"]],
        }
        score = compute_cell_disagreement(t1, t2)
        assert score == 0.0

    def test_shape_mismatch_returns_one(self) -> None:
        """Different row counts should return 1.0."""
        t1 = {
            "headers": ["A", "B"],
            "rows": [["1", "2"]],
        }
        t2 = {
            "headers": ["A", "B"],
            "rows": [["1", "2"], ["3", "4"]],
        }
        score = compute_cell_disagreement(t1, t2)
        assert score == 1.0

    def test_column_mismatch_returns_one(self) -> None:
        """Different column counts should return 1.0."""
        t1 = {
            "headers": ["A", "B"],
            "rows": [["1", "2"]],
        }
        t2 = {
            "headers": ["A", "B", "C"],
            "rows": [["1", "2", "3"]],
        }
        score = compute_cell_disagreement(t1, t2)
        assert score == 1.0

    def test_partial_disagreement(self) -> None:
        """Some cells different should produce a score between 0 and 1."""
        t1 = {
            "headers": ["A", "B"],
            "rows": [["hello", "world"]],
        }
        t2 = {
            "headers": ["A", "B"],
            "rows": [["hello", "DIFFERENT"]],
        }
        score = compute_cell_disagreement(t1, t2)
        # 1 mismatch out of 4 total cells (2 headers + 2 data)
        assert 0.0 < score < 1.0

    def test_empty_tables(self) -> None:
        """Empty tables should return 0.0."""
        t1: dict[str, object] = {"headers": [], "rows": []}
        t2: dict[str, object] = {"headers": [], "rows": []}
        score = compute_cell_disagreement(t1, t2)
        assert score == 0.0

    def test_fuzzy_match_similar_cells(self) -> None:
        """Cells that are very similar should match (ratio >= 0.90)."""
        t1 = {
            "headers": ["Amount"],
            "rows": [["1,234.56"]],
        }
        t2 = {
            "headers": ["Amount"],
            "rows": [["1234.56"]],  # Missing comma
        }
        score = compute_cell_disagreement(t1, t2)
        # The cells are similar enough to fuzzy match
        assert score < 1.0


class TestTriangulateTable:
    """Tests for triangulate_table()."""

    def test_agreement_verdict(self) -> None:
        """Score < 0.10 should produce agreement verdict."""
        t1 = {
            "table_id": "page1_table0",
            "headers": ["A", "B", "C"],
            "rows": [["1", "2", "3"], ["4", "5", "6"]],
        }
        t2 = {
            "table_id": "page1_camelot0",
            "headers": ["A", "B", "C"],
            "rows": [["1", "2", "3"], ["4", "5", "6"]],
        }
        result = triangulate_table(t1, t2)
        assert result.verdict == "agreement"
        assert result.winner == "pdfplumber"
        assert result.disagreement_score < 0.10

    def test_hard_flag_on_shape_mismatch(self) -> None:
        """Shape mismatch should produce hard_flag with score 1.0."""
        t1 = {
            "table_id": "page1_table0",
            "headers": ["A", "B"],
            "rows": [["1", "2"]],
        }
        t2 = {
            "table_id": "page1_camelot0",
            "headers": ["A", "B", "C"],
            "rows": [["1", "2", "3"]],
        }
        result = triangulate_table(t1, t2)
        assert result.verdict == "hard_flag"
        assert result.winner == "vlm_required"
        assert result.disagreement_score == 1.0

    def test_soft_flag_moderate_disagreement(self) -> None:
        """Moderate disagreement (0.10-0.40) should produce soft_flag."""
        # Create tables where ~20% of cells disagree
        t1 = {
            "table_id": "page1_table0",
            "headers": ["A", "B", "C", "D", "E"],
            "rows": [
                ["1", "2", "3", "4", "5"],
                ["6", "7", "8", "9", "10"],
            ],
        }
        t2 = {
            "table_id": "page1_camelot0",
            "headers": ["A", "B", "C", "D", "E"],
            "rows": [
                ["1", "2", "WRONG", "4", "5"],
                ["6", "WRONG", "8", "WRONG", "10"],
            ],
        }
        result = triangulate_table(t1, t2)
        # 3 mismatches out of 15 cells = 0.20
        assert result.verdict == "soft_flag"
        assert result.winner == "pdfplumber"
        assert 0.10 <= result.disagreement_score < 0.40

    def test_methods_always_present(self) -> None:
        """Result should always include both methods."""
        t1 = {"table_id": "t1", "headers": ["A"], "rows": [["1"]]}
        t2 = {"table_id": "t2", "headers": ["A"], "rows": [["1"]]}
        result = triangulate_table(t1, t2)
        assert "pdfplumber" in result.methods
        assert "camelot" in result.methods


class TestFuzzyMatch:
    """Tests for _fuzzy_match helper."""

    def test_exact_match(self) -> None:
        assert _fuzzy_match("hello", "hello", 0.90) is True

    def test_empty_strings_match(self) -> None:
        assert _fuzzy_match("", "", 0.90) is True

    def test_completely_different(self) -> None:
        assert _fuzzy_match("abc", "xyz", 0.90) is False

    def test_similar_strings(self) -> None:
        # "hello" vs "helo" — ratio should be high
        assert _fuzzy_match("hello", "helo", 0.80) is True


class TestNormaliseCell:
    """Tests for _normalise_cell helper."""

    def test_strips_whitespace(self) -> None:
        assert _normalise_cell("  hello  ") == "hello"

    def test_lowercases(self) -> None:
        assert _normalise_cell("HELLO") == "hello"

    def test_none_returns_empty(self) -> None:
        assert _normalise_cell(None) == ""  # type: ignore[arg-type]
