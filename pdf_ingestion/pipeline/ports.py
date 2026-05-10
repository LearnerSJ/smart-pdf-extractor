"""Port interfaces for all external dependencies.

Every external dependency — AWS Bedrock, Presidio, PaddleOCR, delivery targets —
is wrapped behind an internal interface (port). No pipeline stage may import or
call a vendor SDK directly.

This makes every dependency swappable and every pipeline stage unit-testable
in isolation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pipeline.models import (
    DeliveryAttemptResult,
    EntityRedactionConfig,
    IngestionEvent,
    RedactionLog,
    Token,
    VLMFieldResult,
)


class VLMClientPort(ABC):
    """Abstraction over any LLM used for field extraction fallback.

    Swap implementations (Bedrock, Azure OpenAI, local) by changing the binding —
    not the pipeline.
    """

    @abstractmethod
    def extract_field(
        self,
        page_text: str,
        field_name: str,
        field_description: str,
        schema_type: str,
    ) -> VLMFieldResult:
        """Extract a single field from page text using an LLM."""
        ...

    @abstractmethod
    def estimate_tokens(self, text: str) -> int:
        """Return a model-specific token estimate for the given text.

        Used by chunking logic to determine window sizes without hardcoded ratios.
        """
        ...

    @abstractmethod
    def max_context_tokens(self) -> int:
        """Return the model's maximum context window size in tokens.

        Used by chunking logic to determine when to split documents into windows.
        """
        ...


class RedactorPort(ABC):
    """Abstraction over any PII/PI redaction engine.

    Pipeline code never imports Presidio directly.
    """

    @abstractmethod
    def redact_page_text(
        self,
        text: str,
        config: list[EntityRedactionConfig],
    ) -> tuple[str, RedactionLog]:
        """Redact PII from text according to the provided configuration.

        Returns a tuple of (redacted_text, redaction_log).
        Never mutates the original text.
        """
        ...


class OCRClientPort(ABC):
    """Abstraction over any OCR backend.

    Allows swapping PaddleOCR for a different engine without touching the pipeline.
    """

    @abstractmethod
    def extract_tokens(self, page_image: bytes) -> list[Token]:
        """Extract text tokens with bounding boxes from a page image."""
        ...


class IngestionTriggerPort(ABC):
    """Abstraction over the mechanism that triggers document ingestion.

    Initial adapter: HTTP POST /v1/extract.
    Future adapters (out of scope Month 1): S3 event notifications, webhook receiver.
    """

    @abstractmethod
    async def receive(self) -> IngestionEvent:
        """Wait for and return the next ingestion event."""
        ...


class DeliveryPort(ABC):
    """Abstraction over the outbound push mechanism for delivering extraction results.

    Initial adapter: WebhookDeliveryClient (HTTP POST to tenant callback_url).
    Future adapters (out of scope): SQS, RabbitMQ, etc.
    """

    @abstractmethod
    async def deliver(
        self,
        payload: dict,  # type: ignore[type-arg]
        callback_url: str,
        auth_header: str | None = None,
    ) -> DeliveryAttemptResult:
        """Deliver extraction results to the specified callback URL.

        Returns a DeliveryAttemptResult indicating success or failure.
        """
        ...
