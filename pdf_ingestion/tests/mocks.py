"""Mock implementations of all port interfaces for testing.

These mocks implement the port interfaces defined in pipeline/ports.py,
enabling unit and integration tests without network calls or external services.
"""

from __future__ import annotations

from pipeline.models import (
    DeliveryAttemptResult,
    EntityRedactionConfig,
    IngestionEvent,
    RedactionLog,
    Token,
    VLMFieldResult,
)
from pipeline.ports import (
    DeliveryPort,
    IngestionTriggerPort,
    OCRClientPort,
    RedactorPort,
    VLMClientPort,
)


class MockVLMClient(VLMClientPort):
    """Returns fixture responses. No network calls.

    Used in all unit and integration tests that exercise VLM fallback paths.
    """

    def __init__(self, fixture: VLMFieldResult | None = None) -> None:
        self._fixture = fixture or VLMFieldResult(
            value="mock_value",
            confidence=0.95,
            raw_response='{"value": "mock_value"}',
            model_id="mock-model",
        )
        self.calls: list[dict[str, object]] = []

    def extract_field(
        self,
        page_text: str,
        field_name: str,
        field_description: str,
        schema_type: str,
    ) -> VLMFieldResult:
        """Return fixture VLM result without making any external call.

        When field_name is "full_extraction", returns a full extraction JSON
        response suitable for the LLM extractor module.
        """
        self.calls.append(
            {
                "field_name": field_name,
                "field_description": field_description,
                "schema_type": schema_type,
                "text_length": len(page_text),
            }
        )
        if field_name == "full_extraction":
            return VLMFieldResult(
                value='{"document_type": "bank_statement", "statement_date": "2024-01-31", "period_from": "2024-01-01", "period_to": "2024-01-31", "institution": "Mock Bank", "client_name": "Test Client", "accounts": [{"account_number": "123456789", "iban": null, "currency": "USD", "account_type": "current", "opening_balance": 1000.00, "closing_balance": 1500.00, "transactions": []}]}',
                confidence=0.9,
                raw_response="mock_full_extraction",
                model_id="mock-model",
            )
        return self._fixture

    def estimate_tokens(self, text: str) -> int:
        """Estimate tokens using a simple chars-per-token ratio of 3.5."""
        return int(len(text) / 3.5)

    def max_context_tokens(self) -> int:
        """Return a default context window of 200,000 tokens."""
        return 200_000


class MockRedactor(RedactorPort):
    """Returns text unchanged with empty redaction log.

    Used in tests where redaction behaviour is not under test.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def redact_page_text(
        self,
        text: str,
        config: list[EntityRedactionConfig],
    ) -> tuple[str, RedactionLog]:
        """Return original text unchanged with an empty RedactionLog."""
        self.calls.append({"text_length": len(text), "config": config})
        return text, RedactionLog(
            entities_redacted=[],
            redacted_count=0,
            config_snapshot=[{"entity_type": c.entity_type, "enabled": c.enabled} for c in config],
        )


class MockOCRClient(OCRClientPort):
    """Returns fixture tokens. No network calls.

    Used in tests that exercise OCR extraction paths.
    """

    def __init__(self, fixture: list[Token] | None = None) -> None:
        self._fixture = fixture or [
            Token(text="mock", bbox=(10.0, 10.0, 50.0, 25.0), confidence=0.98),
            Token(text="token", bbox=(55.0, 10.0, 100.0, 25.0), confidence=0.97),
        ]
        self.calls: list[dict[str, object]] = []

    def extract_tokens(self, page_image: bytes) -> list[Token]:
        """Return fixture tokens without making any external call."""
        self.calls.append({"image_size": len(page_image)})
        return self._fixture


class MockDeliveryClient(DeliveryPort):
    """Records delivery attempts. No network calls.

    Used in all unit and integration tests that exercise delivery paths.
    """

    def __init__(self, should_succeed: bool = True) -> None:
        self._should_succeed = should_succeed
        self.attempts: list[dict[str, object]] = []

    async def deliver(
        self,
        payload: dict,  # type: ignore[type-arg]
        callback_url: str,
        auth_header: str | None = None,
    ) -> DeliveryAttemptResult:
        """Record the delivery attempt and return success/failure based on config."""
        self.attempts.append(
            {"payload": payload, "url": callback_url, "auth": auth_header}
        )
        if self._should_succeed:
            return DeliveryAttemptResult(success=True, status_code=200)
        return DeliveryAttemptResult(
            success=False, status_code=500, error="mock failure"
        )


class MockIngestionTrigger(IngestionTriggerPort):
    """Returns a fixture ingestion event. No network calls.

    Used in tests that exercise the ingestion trigger path.
    """

    def __init__(self, fixture: IngestionEvent | None = None) -> None:
        self._fixture = fixture or IngestionEvent(
            file_bytes=b"%PDF-1.4 mock content",
            filename="test.pdf",
            tenant_id="test-tenant",
            trace_id="test-trace-id",
        )
        self.calls: list[dict[str, object]] = []

    async def receive(self) -> IngestionEvent:
        """Return fixture ingestion event."""
        self.calls.append({"received": True})
        return self._fixture
