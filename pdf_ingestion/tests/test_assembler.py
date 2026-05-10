"""Tests for pipeline/assembler.py."""

from __future__ import annotations

from pipeline.assembler import assemble, _xy_cut_order, _stitch_multi_page_tables
from pipeline.models import PageOutput, Token


def test_assemble_single_page():
    """Assembling a single page produces correct output."""
    page = PageOutput(
        page_number=1,
        classification="DIGITAL",
        tokens=[Token(text="hello", bbox=(10, 10, 50, 25), confidence=1.0)],
        tables=[],
        text_blocks=[{"text": "hello", "bbox": [10, 10, 50, 25]}],
    )
    result = assemble([page])
    assert len(result.blocks) == 1
    assert len(result.token_stream) == 1
    assert result.provenance["total_pages"] == 1


def test_assemble_preserves_page_order():
    """Pages are assembled in page number order regardless of input order."""
    page2 = PageOutput(page_number=2, classification="DIGITAL", tokens=[], tables=[], text_blocks=[{"text": "second", "bbox": [10, 10, 50, 25]}])
    page1 = PageOutput(page_number=1, classification="DIGITAL", tokens=[], tables=[], text_blocks=[{"text": "first", "bbox": [10, 10, 50, 25]}])

    result = assemble([page2, page1])
    assert result.blocks[0]["text"] == "first"
    assert result.blocks[1]["text"] == "second"


def test_assemble_multi_page_table_stitching():
    """Tables with matching headers across consecutive pages are stitched."""
    page1 = PageOutput(
        page_number=1,
        classification="DIGITAL",
        tokens=[],
        tables=[{
            "table_id": "page1_table0",
            "page_number": 1,
            "headers": ["Date", "Amount"],
            "rows": [["2024-01-01", "100.00"]],
            "bbox": [0, 0, 100, 50],
            "source": "pdfplumber",
        }],
        text_blocks=[],
    )
    page2 = PageOutput(
        page_number=2,
        classification="DIGITAL",
        tokens=[],
        tables=[{
            "table_id": "page2_table0",
            "page_number": 2,
            "headers": ["Date", "Amount"],
            "rows": [["2024-01-02", "200.00"]],
            "bbox": [0, 0, 100, 50],
            "source": "pdfplumber",
        }],
        text_blocks=[],
    )

    result = assemble([page1, page2])
    assert len(result.tables) == 1  # Stitched into one table
    assert len(result.tables[0]["rows"]) == 2


def test_xy_cut_orders_top_to_bottom():
    """XY-cut orders blocks from top to bottom."""
    blocks = [
        {"text": "bottom", "bbox": [10, 200, 50, 220]},
        {"text": "top", "bbox": [10, 10, 50, 30]},
    ]
    ordered = _xy_cut_order(blocks, page_number=1)
    assert ordered[0]["text"] == "top"
    assert ordered[1]["text"] == "bottom"


def test_assemble_empty_pages():
    """Assembling empty page list produces empty document."""
    result = assemble([])
    assert result.blocks == []
    assert result.tables == []
    assert result.token_stream == []
