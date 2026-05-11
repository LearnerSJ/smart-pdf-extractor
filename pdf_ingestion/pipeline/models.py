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


# ─── Auto-Schema Discovery Models ────────────────────────────────────────────


@dataclass
class SchemaFingerprint:
    """Composite key for schema cache lookup.

    Derived from institution name (normalised lowercase, stripped) and
    document_type_label. Together these identify a unique document structure.
    """

    institution: str  # normalised: lowercase, stripped, spaces→underscores
    document_type_label: str  # as returned by VLM (e.g., "futures_trade_confirmation")

    @property
    def key(self) -> str:
        """String representation for DB storage and URL paths."""
        inst = self.institution.lower().strip().replace(" ", "_")
        return f"{inst}::{self.document_type_label}"

    @classmethod
    def from_key(cls, key: str) -> "SchemaFingerprint":
        """Parse a fingerprint key string back into components."""
        parts = key.split("::", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid fingerprint key: {key}")
        return cls(institution=parts[0], document_type_label=parts[1])


@dataclass
class DiscoveredFieldDefinition:
    """A single field definition discovered by VLM analysis."""

    field_name: str  # snake_case identifier
    description: str  # what the field contains
    location_hint: str  # "header", "footer", "first_page", "last_page"


@dataclass
class DiscoveredTableDefinition:
    """A table structure discovered by VLM analysis."""

    table_type: str  # e.g., "trades", "balance_summary"
    expected_headers: list[str] = field(default_factory=list)  # column headers
    data_pattern: str = ""  # description of row content
    location_hint: str = ""  # "body_repeating", "last_page", "first_page"


@dataclass
class DiscoveredSchema:
    """VLM-generated schema definition for an unrecognised document type.

    Produced by Auto_Schema_Discovery and consumed by Dynamic_Extractor.
    Cached in Schema_Cache keyed by SchemaFingerprint.
    """

    document_type_label: str  # e.g., "futures_trade_confirmation"
    institution: str  # e.g., "Société Générale"
    metadata_fields: list[DiscoveredFieldDefinition] = field(default_factory=list)
    table_definitions: list[DiscoveredTableDefinition] = field(default_factory=list)
    fingerprint: SchemaFingerprint = field(init=False)

    def __post_init__(self) -> None:
        self.fingerprint = SchemaFingerprint(
            institution=self.institution,
            document_type_label=self.document_type_label,
        )


@dataclass
class DiscoverySample:
    """A subset of document pages sent to VLM for schema analysis.

    Kept small to respect token budgets. Default: first 5 pages.
    Adaptively reduced if estimated tokens exceed 80% of context window.
    """

    page_texts: list[str] = field(default_factory=list)  # text content of each sampled page
    page_numbers: list[int] = field(default_factory=list)  # which pages were sampled (1-indexed)
    estimated_tokens: int = 0  # token estimate for the combined sample

    @property
    def page_count(self) -> int:
        return len(self.page_texts)

    @property
    def combined_text(self) -> str:
        """Concatenate all page texts with page markers."""
        parts = []
        for num, text in zip(self.page_numbers, self.page_texts):
            parts.append(f"--- PAGE {num} ---\n{text}")
        return "\n\n".join(parts)
