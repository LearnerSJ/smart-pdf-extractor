"""Internal pipeline data models.

All pipeline models use dataclasses (not Pydantic) to keep the pipeline layer
free of web-framework dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Token:
    """A single OCR token with bounding box and confidence."""

    text: str
    bbox: tuple[float, float, float, float]
    confidence: float


@dataclass
class VLMFieldResult:
    """Result of a VLM field extraction attempt."""

    value: str | None
    confidence: float
    raw_response: str
    model_id: str


@dataclass
class RedactionLog:
    """Record of redaction operations applied before VLM invocation."""

    entities_redacted: list[dict[str, object]]
    redacted_count: int
    config_snapshot: list[dict[str, object]]


@dataclass
class EntityRedactionConfig:
    """Configuration for a single entity type to redact."""

    entity_type: str
    enabled: bool = True


@dataclass
class VerificationOutcome:
    """Result of verifying a VLM-extracted value against the token stream."""

    verified: bool
    reason: str | None = None
    matched_token: Token | None = None
    provenance: dict[str, object] | None = None


@dataclass
class PageOutput:
    """Output of processing a single page through classification and extraction."""

    page_number: int
    classification: str  # "DIGITAL" or "SCANNED"
    tokens: list[Token] = field(default_factory=list)
    tables: list[dict[str, object]] = field(default_factory=list)
    text_blocks: list[dict[str, object]] = field(default_factory=list)


@dataclass
class IngestedDocument:
    """A validated and deduplicated document ready for pipeline processing."""

    hash: str  # SHA-256 hex digest
    content: bytes
    filename: str


@dataclass
class CachedResult:
    """Reference to a previously computed result for a duplicate document."""

    hash: str  # SHA-256 hex digest matching an existing result


@dataclass
class AssembledDocument:
    """Fully assembled document with merged pages, reading order, and provenance."""

    blocks: list[dict[str, object]] = field(default_factory=list)
    tables: list[dict[str, object]] = field(default_factory=list)
    token_stream: list[Token] = field(default_factory=list)
    provenance: dict[str, object] = field(default_factory=dict)


@dataclass
class TriangulationResult:
    """Result of comparing pdfplumber and camelot table outputs."""

    disagreement_score: float
    verdict: str  # "agreement", "soft_flag", "hard_flag"
    winner: str  # "pdfplumber", "camelot", "vlm_required"
    methods: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class DeliveryAttemptResult:
    """Result of a single delivery attempt."""

    success: bool
    status_code: int | None = None
    error: str | None = None
    attempt_number: int = 1
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class IngestionEvent:
    """Trigger event representing a document to ingest."""

    file_bytes: bytes
    filename: str
    tenant_id: str
    trace_id: str
    schema_type: str | None = None
    batch_id: str | None = None
