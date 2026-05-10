"""Per-job token budget tracker for VLM extraction.

Monitors cumulative token consumption across all LLM calls within a single job
and enforces configurable limits via three budget actions: flag, skip, proceed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TokenBudget:
    """Tracks token consumption against a per-job budget.

    Budget-based approach: a 200-page PDF still gets VLM on the specific
    pages it needs; only hits budget limit if actual token consumption
    is excessive.
    """

    max_tokens: int
    budget_exceeded_action: str  # "flag" | "skip" | "proceed"
    consumed_input_tokens: int = 0
    consumed_output_tokens: int = 0
    windows_processed: int = 0

    @property
    def total_consumed(self) -> int:
        """Total tokens consumed (input + output) across all LLM calls."""
        return self.consumed_input_tokens + self.consumed_output_tokens

    @property
    def remaining(self) -> int:
        """Tokens remaining before budget is reached. Never negative."""
        return max(0, self.max_tokens - self.total_consumed)

    @property
    def is_exceeded(self) -> bool:
        """Whether total consumption has exceeded the budget."""
        return self.total_consumed > self.max_tokens

    def record_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Record token consumption from a single LLM call."""
        self.consumed_input_tokens += input_tokens
        self.consumed_output_tokens += output_tokens
        self.windows_processed += 1

    def can_proceed(self) -> bool:
        """Check if another LLM call is allowed within budget.

        When action is "flag": always returns True (mark for review but continue)
        When action is "skip": returns False once budget exceeded
        When action is "proceed": always returns True (no enforcement)
        """
        if self.budget_exceeded_action == "proceed":
            return True
        if self.budget_exceeded_action == "flag":
            return True  # continue but flag
        # "skip"
        return not self.is_exceeded
