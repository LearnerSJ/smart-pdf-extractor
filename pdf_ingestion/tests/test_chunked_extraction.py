"""Unit tests for chunked VLM extraction.

Tests tier selection logic, sliding window creation, transaction deduplication,
token budget enforcement, and targeted page selection.

Validates: Requirements 22.1, 22.2, 22.3, 22.4, 22.5, 22.6, 22.7
"""

from __future__ import annotations

import pytest

from pipeline.vlm.chunked_extractor import (
    PageWindow,
    WindowConfig,
    create_sliding_windows,
    merge_window_results,
    select_extraction_tier,
    select_target_pages,
)
from pipeline.vlm.token_budget import TokenBudget
from tests.mocks import MockVLMClient


# ─── Tier Selection Tests ─────────────────────────────────────────────────────


class TestTierSelection:
    """Test select_extraction_tier with various document sizes and abstention patterns."""

    def test_small_document_returns_single(self):
        """A document that fits within 80% of context window → 'single'."""
        # MockVLMClient.max_context_tokens() = 200_000
        # 80% threshold = 160_000 tokens
        # estimate_tokens uses len(text) / 3.5
        # So text must be < 160_000 * 3.5 = 560_000 chars
        vlm_client = MockVLMClient()
        page_texts = ["Short page content."] * 5  # Very small document

        tier = select_extraction_tier(page_texts, ["institution"], vlm_client)

        assert tier == "single"

    def test_large_document_header_only_abstentions_returns_tier1(self):
        """Large document with only header fields abstained → 'tier1'."""
        vlm_client = MockVLMClient()
        # Create a document that exceeds 80% of context window
        # Need > 560_000 chars total
        page_texts = ["x" * 12000] * 50  # 600_000 chars total

        tier = select_extraction_tier(
            page_texts, ["institution", "client_name", "statement_date"], vlm_client
        )

        assert tier == "tier1"

    def test_large_document_full_extraction_under_80_pages_returns_tier2(self):
        """Large document with full extraction needed, <80 pages → 'tier2'."""
        vlm_client = MockVLMClient()
        page_texts = ["x" * 12000] * 50  # 50 pages, exceeds token threshold

        # Non-header field triggers full extraction
        tier = select_extraction_tier(page_texts, ["transactions"], vlm_client)

        assert tier == "tier2"

    def test_large_document_full_extraction_80_plus_pages_returns_tier2(self):
        """Large document with full extraction needed, >=80 pages → 'tier2' (sliding window)."""
        vlm_client = MockVLMClient()
        page_texts = ["x" * 8000] * 80  # 80 pages, exceeds token threshold

        tier = select_extraction_tier(page_texts, ["transactions"], vlm_client)

        assert tier == "tier2"

    def test_mixed_header_and_non_header_fields_not_tier1(self):
        """If abstained fields include non-header fields, tier1 is not selected."""
        vlm_client = MockVLMClient()
        page_texts = ["x" * 12000] * 50

        tier = select_extraction_tier(
            page_texts, ["institution", "transactions"], vlm_client
        )

        # "transactions" is not in HEADER_FIELDS, so not tier1
        assert tier == "tier2"

    def test_empty_abstained_fields_large_doc_returns_tier2_or_tier3(self):
        """Empty abstained fields with large doc still selects based on page count."""
        vlm_client = MockVLMClient()
        page_texts = ["x" * 12000] * 50

        # Empty set is a subset of anything, so it goes to tier1
        # Actually: empty set.issubset(HEADER_FIELDS) is True, but the condition
        # checks `abstained_set and abstained_set.issubset(HEADER_FIELDS)`
        # Empty set is falsy, so it falls through to tier2/tier3
        tier = select_extraction_tier(page_texts, [], vlm_client)

        assert tier == "tier2"


# ─── Sliding Window Tests ─────────────────────────────────────────────────────


class TestSlidingWindows:
    """Test create_sliding_windows with different page counts and overlap settings."""

    def test_50_pages_default_config_correct_window_count(self):
        """50 pages with window_size=12, overlap=3 → correct number of windows."""
        page_texts = [f"Page {i}" for i in range(50)]
        config = WindowConfig(window_size=12, overlap=3)

        windows = create_sliding_windows(page_texts, config)

        # Step = 12 - 3 = 9
        # Windows start at: 0, 9, 18, 27, 36, 45
        # Window at 45: end = min(45+11, 49) = 49 → covers remaining
        assert len(windows) == 6

    def test_windows_are_page_aligned(self):
        """Windows start and end at correct page boundaries (1-indexed)."""
        page_texts = [f"Page {i}" for i in range(30)]
        config = WindowConfig(window_size=12, overlap=3)

        windows = create_sliding_windows(page_texts, config)

        # Step = 9, windows start at 0-indexed: 0, 9, 18, 27
        assert windows[0].start_page == 1
        assert windows[0].end_page == 12
        assert windows[1].start_page == 10
        assert windows[1].end_page == 21
        assert windows[2].start_page == 19
        assert windows[2].end_page == 30

    def test_adjacent_windows_overlap_by_configured_amount(self):
        """Adjacent windows overlap by exactly the configured overlap pages."""
        page_texts = [f"Page {i}" for i in range(50)]
        config = WindowConfig(window_size=12, overlap=3)

        windows = create_sliding_windows(page_texts, config)

        for i in range(len(windows) - 1):
            current_end = windows[i].end_page
            next_start = windows[i + 1].start_page
            overlap = current_end - next_start + 1
            assert overlap == 3, f"Windows {i} and {i+1} overlap by {overlap}, expected 3"

    def test_last_window_covers_remaining_pages(self):
        """The last window extends to cover all remaining pages."""
        page_texts = [f"Page {i}" for i in range(50)]
        config = WindowConfig(window_size=12, overlap=3)

        windows = create_sliding_windows(page_texts, config)

        assert windows[-1].end_page == 50  # 1-indexed, covers page 50

    def test_empty_page_list_returns_empty_windows(self):
        """Empty page list → empty windows list."""
        config = WindowConfig(window_size=12, overlap=3)

        windows = create_sliding_windows([], config)

        assert windows == []

    def test_single_page_returns_one_window(self):
        """A single page produces exactly one window."""
        page_texts = ["Only page"]
        config = WindowConfig(window_size=12, overlap=3)

        windows = create_sliding_windows(page_texts, config)

        assert len(windows) == 1
        assert windows[0].start_page == 1
        assert windows[0].end_page == 1

    def test_pages_fewer_than_window_size(self):
        """When pages < window_size, one window covers all pages."""
        page_texts = [f"Page {i}" for i in range(5)]
        config = WindowConfig(window_size=12, overlap=3)

        windows = create_sliding_windows(page_texts, config)

        assert len(windows) == 1
        assert windows[0].start_page == 1
        assert windows[0].end_page == 5

    def test_window_page_texts_populated(self):
        """Each window's page_texts contains the correct page content."""
        page_texts = [f"Content of page {i}" for i in range(15)]
        config = WindowConfig(window_size=5, overlap=2)

        windows = create_sliding_windows(page_texts, config)

        # First window: pages 0-4
        assert windows[0].page_texts == page_texts[0:5]
        # Second window: pages 3-7 (step=3)
        assert windows[1].page_texts == page_texts[3:8]


# ─── Transaction Deduplication Tests ──────────────────────────────────────────


class TestTransactionDeduplication:
    """Test merge_window_results with overlap scenarios."""

    def test_duplicate_transactions_are_deduplicated(self):
        """Transactions with same (date, description, amount) appear only once."""
        window1 = {
            "header_fields": {"institution": "Bank A", "opening_balance": 1000},
            "transactions": [
                {"date": "2024-01-01", "description": "Payment", "debit": 100, "credit": None, "balance": 900},
                {"date": "2024-01-02", "description": "Deposit", "debit": None, "credit": 200, "balance": 1100},
            ],
        }
        window2 = {
            "header_fields": {"closing_balance": 1500},
            "transactions": [
                # Duplicate from overlap
                {"date": "2024-01-02", "description": "Deposit", "debit": None, "credit": 200, "balance": 1100},
                # New transaction
                {"date": "2024-01-03", "description": "Transfer", "debit": 50, "credit": None, "balance": 1050},
            ],
        }

        merged = merge_window_results([window1, window2])

        assert len(merged["transactions"]) == 3

    def test_different_transactions_are_preserved(self):
        """Transactions with different keys are all preserved."""
        window1 = {
            "header_fields": {"institution": "Bank A"},
            "transactions": [
                {"date": "2024-01-01", "description": "Payment A", "debit": 100, "credit": None},
                {"date": "2024-01-02", "description": "Payment B", "debit": 200, "credit": None},
            ],
        }
        window2 = {
            "header_fields": {},
            "transactions": [
                {"date": "2024-01-03", "description": "Payment C", "debit": 300, "credit": None},
                {"date": "2024-01-04", "description": "Payment D", "debit": 400, "credit": None},
            ],
        }

        merged = merge_window_results([window1, window2])

        assert len(merged["transactions"]) == 4

    def test_header_fields_from_first_window(self):
        """Header fields are taken from the first window."""
        window1 = {
            "header_fields": {
                "institution": "First Bank",
                "client_name": "Client A",
                "opening_balance": 5000,
            },
            "transactions": [],
        }
        window2 = {
            "header_fields": {
                "institution": "Should be ignored",
                "closing_balance": 6000,
            },
            "transactions": [],
        }

        merged = merge_window_results([window1, window2])

        assert merged["header_fields"]["institution"] == "First Bank"
        assert merged["header_fields"]["client_name"] == "Client A"
        assert merged["header_fields"]["opening_balance"] == 5000

    def test_closing_balance_from_last_window(self):
        """Closing balance is taken from the last window."""
        window1 = {
            "header_fields": {"institution": "Bank A", "closing_balance": 1000},
            "transactions": [],
        }
        window2 = {
            "header_fields": {"closing_balance": 2000},
            "transactions": [],
        }
        window3 = {
            "header_fields": {"closing_balance": 3000},
            "transactions": [],
        }

        merged = merge_window_results([window1, window2, window3])

        assert merged["header_fields"]["closing_balance"] == 3000

    def test_single_window_returns_as_is(self):
        """A single window result is returned unchanged."""
        window = {
            "header_fields": {"institution": "Bank A"},
            "transactions": [{"date": "2024-01-01", "description": "Pay", "debit": 50}],
        }

        merged = merge_window_results([window])

        assert merged == window

    def test_empty_results_returns_empty_dict(self):
        """Empty window results list returns empty dict."""
        merged = merge_window_results([])

        assert merged == {}


# ─── Token Budget Tests ───────────────────────────────────────────────────────


class TestTokenBudget:
    """Test token budget enforcement for all three actions."""

    def test_proceed_action_can_proceed_always_true(self):
        """'proceed' action: can_proceed() always returns True regardless of budget."""
        budget = TokenBudget(max_tokens=100, budget_exceeded_action="proceed")
        budget.record_usage(80, 80)  # 160 total, exceeds 100

        assert budget.can_proceed() is True
        assert budget.is_exceeded is True

    def test_flag_action_can_proceed_always_true(self):
        """'flag' action: can_proceed() always returns True (continue but flag)."""
        budget = TokenBudget(max_tokens=100, budget_exceeded_action="flag")
        budget.record_usage(80, 80)  # 160 total, exceeds 100

        assert budget.can_proceed() is True

    def test_flag_action_is_exceeded_tracks_correctly(self):
        """'flag' action: is_exceeded tracks whether budget was exceeded."""
        budget = TokenBudget(max_tokens=100, budget_exceeded_action="flag")

        assert budget.is_exceeded is False
        budget.record_usage(50, 40)  # 90 total, under budget
        assert budget.is_exceeded is False
        budget.record_usage(10, 5)  # 105 total, over budget
        assert budget.is_exceeded is True

    def test_skip_action_can_proceed_false_after_exceeded(self):
        """'skip' action: can_proceed() returns False after budget exceeded."""
        budget = TokenBudget(max_tokens=100, budget_exceeded_action="skip")

        assert budget.can_proceed() is True
        budget.record_usage(60, 50)  # 110 total, exceeds 100
        assert budget.can_proceed() is False

    def test_skip_action_can_proceed_true_before_exceeded(self):
        """'skip' action: can_proceed() returns True while under budget."""
        budget = TokenBudget(max_tokens=100, budget_exceeded_action="skip")
        budget.record_usage(30, 20)  # 50 total, under budget

        assert budget.can_proceed() is True

    def test_record_usage_accumulates_correctly(self):
        """record_usage() accumulates input and output tokens correctly."""
        budget = TokenBudget(max_tokens=1000, budget_exceeded_action="proceed")

        budget.record_usage(100, 50)
        assert budget.consumed_input_tokens == 100
        assert budget.consumed_output_tokens == 50
        assert budget.total_consumed == 150
        assert budget.windows_processed == 1

        budget.record_usage(200, 75)
        assert budget.consumed_input_tokens == 300
        assert budget.consumed_output_tokens == 125
        assert budget.total_consumed == 425
        assert budget.windows_processed == 2

    def test_remaining_never_negative(self):
        """remaining property never goes below zero."""
        budget = TokenBudget(max_tokens=100, budget_exceeded_action="proceed")
        budget.record_usage(200, 200)  # 400 total, way over budget

        assert budget.remaining == 0


# ─── Targeted Page Selection Tests ────────────────────────────────────────────


class TestTargetedPageSelection:
    """Test select_target_pages for header-only abstentions."""

    def test_header_only_fields_target_first_pages(self):
        """Header-only fields (institution, client_name) → pages 1-2."""
        windows = select_target_pages(["institution", "client_name"], total_pages=20)

        assert len(windows) >= 1
        # All windows should target early pages
        for w in windows:
            assert w.start_page <= 2

    def test_closing_balance_targets_last_pages(self):
        """Closing balance → last pages of the document."""
        windows = select_target_pages(["closing_balance"], total_pages=20)

        assert len(windows) >= 1
        # Should target pages near the end
        for w in windows:
            assert w.end_page >= 19  # Near the end (1-indexed)

    def test_mixed_fields_produce_merged_windows(self):
        """Mixed fields (header + closing) → separate windows for different page ranges."""
        windows = select_target_pages(
            ["institution", "closing_balance"], total_pages=20
        )

        # Should have at least 2 windows: one for first pages, one for last
        assert len(windows) >= 2

        # Check that we have both early and late page coverage
        start_pages = [w.start_page for w in windows]
        end_pages = [w.end_page for w in windows]
        assert min(start_pages) <= 2  # Early pages covered
        assert max(end_pages) >= 19  # Late pages covered

    def test_unknown_fields_default_to_first_3_pages(self):
        """Unknown fields → default to first 3 pages."""
        windows = select_target_pages(["unknown_field_xyz"], total_pages=20)

        assert len(windows) >= 1
        # Should cover first few pages
        assert windows[0].start_page <= 3

    def test_empty_abstained_fields_returns_empty(self):
        """Empty abstained fields → no windows."""
        windows = select_target_pages([], total_pages=20)

        assert windows == []

    def test_zero_pages_returns_empty(self):
        """Zero total pages → no windows."""
        windows = select_target_pages(["institution"], total_pages=0)

        assert windows == []

    def test_target_fields_populated_in_windows(self):
        """Each window has target_fields populated with the relevant field names."""
        windows = select_target_pages(["institution", "statement_date"], total_pages=20)

        all_target_fields = []
        for w in windows:
            all_target_fields.extend(w.target_fields)

        assert "institution" in all_target_fields
        assert "statement_date" in all_target_fields
