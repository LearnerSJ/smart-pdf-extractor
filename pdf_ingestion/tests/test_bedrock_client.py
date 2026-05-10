"""Tests for the Bedrock VLM client and circuit breaker."""

from __future__ import annotations

import time

from api.errors import ErrorCode
from pipeline.vlm.bedrock_client import BedrockVLMClient, CircuitBreaker


class TestCircuitBreaker:
    """Tests for the CircuitBreaker class."""

    def test_starts_closed(self) -> None:
        """Circuit breaker should start in closed state."""
        cb = CircuitBreaker(failure_threshold=3, recovery_window_seconds=60.0)
        assert cb.state == "closed"
        assert cb.is_call_allowed() is True

    def test_opens_after_threshold_failures(self) -> None:
        """Circuit should open after 3 consecutive failures."""
        cb = CircuitBreaker(failure_threshold=3, recovery_window_seconds=60.0)

        cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "open"
        assert cb.is_call_allowed() is False

    def test_success_resets_failure_count(self) -> None:
        """A success should reset the failure count and close the circuit."""
        cb = CircuitBreaker(failure_threshold=3, recovery_window_seconds=60.0)

        cb.record_failure()
        cb.record_failure()
        cb.record_success()

        assert cb.failure_count == 0
        assert cb.state == "closed"

    def test_half_open_after_recovery_window(self) -> None:
        """Circuit should transition to half_open after recovery window."""
        cb = CircuitBreaker(failure_threshold=3, recovery_window_seconds=0.01)

        # Open the circuit
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"

        # Wait for recovery window
        time.sleep(0.02)

        # Should transition to half_open
        assert cb.is_call_allowed() is True
        assert cb.state == "half_open"

    def test_half_open_success_closes(self) -> None:
        """Success in half_open state should close the circuit."""
        cb = CircuitBreaker(failure_threshold=3, recovery_window_seconds=0.01)

        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.02)
        cb.is_call_allowed()  # Transitions to half_open

        cb.record_success()
        assert cb.state == "closed"

    def test_half_open_failure_reopens(self) -> None:
        """Failure in half_open state should reopen the circuit."""
        cb = CircuitBreaker(failure_threshold=3, recovery_window_seconds=0.01)

        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.02)
        cb.is_call_allowed()  # Transitions to half_open

        cb.record_failure()
        assert cb.state == "open"


class TestBedrockVLMClient:
    """Tests for BedrockVLMClient."""

    def test_vlm_disabled_returns_abstention(self) -> None:
        """When vlm_enabled=False, should abstain immediately without calling Bedrock."""
        client = BedrockVLMClient(vlm_enabled=False)

        result = client.extract_field(
            page_text="Account Number: 12345678",
            field_name="account_number",
            field_description="The account number",
            schema_type="bank_statement",
        )

        assert result.value is None
        assert result.confidence == 0.0

    def test_circuit_open_returns_abstention(self) -> None:
        """When circuit is open, should abstain immediately."""
        client = BedrockVLMClient(vlm_enabled=True)

        # Force circuit open
        client._circuit_breaker.record_failure()
        client._circuit_breaker.record_failure()
        client._circuit_breaker.record_failure()
        assert client._circuit_breaker.state == "open"

        result = client.extract_field(
            page_text="Account Number: 12345678",
            field_name="account_number",
            field_description="The account number",
            schema_type="bank_statement",
        )

        assert result.value is None
        assert "circuit_breaker_open" in result.raw_response
