"""Tests for the TokenBudget tracker.

**Validates: Requirements 24.1, 24.2, 24.3, 24.4, 24.5**
"""

from __future__ import annotations

import pytest

from pipeline.vlm.token_budget import TokenBudget


class TestTokenBudget:
    """Tests for the TokenBudget class."""

    def test_initial_state(self) -> None:
        """TokenBudget should initialize with zero consumption."""
        budget = TokenBudget(max_tokens=100_000, budget_exceeded_action="flag")

        assert budget.consumed_input_tokens == 0
        assert budget.consumed_output_tokens == 0
        assert budget.windows_processed == 0
        assert budget.total_consumed == 0
        assert budget.remaining == 100_000
        assert budget.is_exceeded is False

    def test_record_usage(self) -> None:
        """record_usage should track token consumption from a single LLM call."""
        budget = TokenBudget(max_tokens=100_000, budget_exceeded_action="flag")

        budget.record_usage(input_tokens=5000, output_tokens=2000)

        assert budget.consumed_input_tokens == 5000
        assert budget.consumed_output_tokens == 2000
        assert budget.total_consumed == 7000
        assert budget.windows_processed == 1

    def test_record_usage_accumulates(self) -> None:
        """Multiple record_usage calls should accumulate consumption."""
        budget = TokenBudget(max_tokens=100_000, budget_exceeded_action="flag")

        budget.record_usage(input_tokens=5000, output_tokens=2000)
        budget.record_usage(input_tokens=3000, output_tokens=1000)

        assert budget.consumed_input_tokens == 8000
        assert budget.consumed_output_tokens == 3000
        assert budget.total_consumed == 11000
        assert budget.windows_processed == 2

    def test_remaining_never_negative(self) -> None:
        """remaining should never return a negative value."""
        budget = TokenBudget(max_tokens=10_000, budget_exceeded_action="flag")

        budget.record_usage(input_tokens=8000, output_tokens=5000)

        assert budget.remaining == 0  # Should be max(0, 15000 - 10000) = 0
        assert budget.total_consumed == 13000

    def test_is_exceeded_false_before_limit(self) -> None:
        """is_exceeded should be False when under budget."""
        budget = TokenBudget(max_tokens=100_000, budget_exceeded_action="flag")

        budget.record_usage(input_tokens=50_000, output_tokens=40_000)

        assert budget.is_exceeded is False
        assert budget.remaining == 10_000

    def test_is_exceeded_true_when_over(self) -> None:
        """is_exceeded should be True when consumption exceeds budget."""
        budget = TokenBudget(max_tokens=100_000, budget_exceeded_action="flag")

        budget.record_usage(input_tokens=60_000, output_tokens=50_000)

        assert budget.is_exceeded is True

    def test_can_proceed_flag_action_always_true(self) -> None:
        """With 'flag' action, can_proceed should always return True."""
        budget = TokenBudget(max_tokens=100_000, budget_exceeded_action="flag")

        budget.record_usage(input_tokens=60_000, output_tokens=50_000)

        # Even after exceeding, flag action allows continuation
        assert budget.can_proceed() is True

    def test_can_proceed_skip_action_false_when_exceeded(self) -> None:
        """With 'skip' action, can_proceed should return False when exceeded."""
        budget = TokenBudget(max_tokens=100_000, budget_exceeded_action="skip")

        # Before exceeding
        assert budget.can_proceed() is True

        budget.record_usage(input_tokens=60_000, output_tokens=50_000)

        # After exceeding
        assert budget.is_exceeded is True
        assert budget.can_proceed() is False

    def test_can_proceed_proceed_action_always_true(self) -> None:
        """With 'proceed' action, can_proceed should always return True."""
        budget = TokenBudget(max_tokens=100_000, budget_exceeded_action="proceed")

        budget.record_usage(input_tokens=60_000, output_tokens=50_000)

        assert budget.can_proceed() is True

    def test_exactly_at_limit_not_exceeded(self) -> None:
        """When exactly at limit, is_exceeded should be False."""
        budget = TokenBudget(max_tokens=100_000, budget_exceeded_action="flag")

        budget.record_usage(input_tokens=60_000, output_tokens=40_000)

        assert budget.is_exceeded is False
        assert budget.remaining == 0

    def test_over_by_one_is_exceeded(self) -> None:
        """Exceeding by one token should mark budget as exceeded."""
        budget = TokenBudget(max_tokens=100_000, budget_exceeded_action="flag")

        budget.record_usage(input_tokens=60_001, output_tokens=40_000)

        assert budget.is_exceeded is True


class TestTokenBudgetProperty24:
    """Property-based tests for token budget enforcement.

    **Property 24: Token Budget Enforcement**
    - skip action stops calls after budget exceeded
    - flag action continues but marks job
    - proceed action always allows calls
    """

    @pytest.mark.parametrize("action", ["flag", "skip", "proceed"])
    def test_record_usage_always_increments_counters(self, action: str) -> None:
        """record_usage should always increment counters regardless of action."""
        budget = TokenBudget(max_tokens=10_000, budget_exceeded_action=action)

        budget.record_usage(input_tokens=1000, output_tokens=500)

        assert budget.consumed_input_tokens == 1000
        assert budget.consumed_output_tokens == 500
        assert budget.windows_processed == 1

    @pytest.mark.parametrize("action", ["flag", "skip", "proceed"])
    def test_total_consumed_equals_input_plus_output(self, action: str) -> None:
        """total_consumed should always equal input + output tokens."""
        budget = TokenBudget(max_tokens=100_000, budget_exceeded_action=action)

        budget.record_usage(input_tokens=12345, output_tokens=6789)

        assert budget.total_consumed == 12345 + 6789

    def test_flag_action_allows_proceed_after_exceeded(self) -> None:
        """Flag action: can_proceed returns True even after budget exceeded."""
        budget = TokenBudget(max_tokens=1000, budget_exceeded_action="flag")

        # Exceed the budget
        budget.record_usage(input_tokens=600, output_tokens=500)

        assert budget.is_exceeded is True
        assert budget.can_proceed() is True  # Continue but flag

    def test_skip_action_blocks_proceed_after_exceeded(self) -> None:
        """Skip action: can_proceed returns False after budget exceeded."""
        budget = TokenBudget(max_tokens=1000, budget_exceeded_action="skip")

        # Exceed the budget
        budget.record_usage(input_tokens=600, output_tokens=500)

        assert budget.is_exceeded is True
        assert budget.can_proceed() is False  # Stop further calls

    def test_skip_action_allows_proceed_before_exceeded(self) -> None:
        """Skip action: can_proceed returns True before budget exceeded."""
        budget = TokenBudget(max_tokens=1000, budget_exceeded_action="skip")

        # Use less than budget
        budget.record_usage(input_tokens=500, output_tokens=400)

        assert budget.is_exceeded is False
        assert budget.can_proceed() is True  # Can continue

    def test_proceed_action_always_allows_proceed(self) -> None:
        """Proceed action: can_proceed always returns True."""
        budget = TokenBudget(max_tokens=1000, budget_exceeded_action="proceed")

        # Exceed the budget
        budget.record_usage(input_tokens=600, output_tokens=500)

        assert budget.is_exceeded is True
        assert budget.can_proceed() is True  # Ignore budget, continue

    def test_remaining_decreases_with_consumption(self) -> None:
        """remaining should decrease as consumption increases."""
        budget = TokenBudget(max_tokens=100_000, budget_exceeded_action="flag")

        initial_remaining = budget.remaining
        budget.record_usage(input_tokens=10_000, output_tokens=5_000)

        assert budget.remaining == initial_remaining - 15_000

    def test_windows_processed_counts_calls(self) -> None:
        """windows_processed should increment with each record_usage call."""
        budget = TokenBudget(max_tokens=100_000, budget_exceeded_action="flag")

        assert budget.windows_processed == 0

        budget.record_usage(input_tokens=1000, output_tokens=500)
        assert budget.windows_processed == 1

        budget.record_usage(input_tokens=2000, output_tokens=1000)
        assert budget.windows_processed == 2