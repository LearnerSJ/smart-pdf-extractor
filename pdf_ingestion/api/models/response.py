"""API response models.

All route handlers return APIResponse[T]. Never return a bare Pydantic model from a route.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field as PydanticField

T = TypeVar("T")


class ResponseMeta(BaseModel):
    """Metadata included in every API response."""

    request_id: str  # the trace_id for this request
    timestamp: str  # ISO 8601


class APIError(BaseModel):
    """Structured error payload referencing an ErrorCode constant."""

    code: str  # e.g. "ERR_INGESTION_001" — from the error registry
    message: str  # human-readable; safe to surface to the client
    detail: str | None = None  # optional; omitted in production for sensitive errors


class APIResponse(BaseModel, Generic[T]):
    """Standard response envelope wrapping all API responses."""

    data: T | None = None
    meta: ResponseMeta
    error: APIError | None = None


class Provenance(BaseModel):
    """Provenance metadata attached to every extracted field."""

    page: int
    bbox: list[float] = PydanticField(min_length=4, max_length=4)
    source: str  # Literal["native", "ocr", "vlm"]
    extraction_rule: str


class Field(BaseModel):
    """A single extracted field with confidence and provenance."""

    value: Any
    original_string: str | None = None
    confidence: float
    vlm_used: bool
    redaction_applied: bool
    provenance: Provenance


class TableRow(BaseModel):
    """A single row in an extracted table."""

    cells: list[Any]
    row_index: int


class TriangulationInfo(BaseModel):
    """Triangulation metadata for a table."""

    score: float
    verdict: str  # "agreement", "soft_flag", "hard_flag"
    winner: str  # "pdfplumber", "camelot", "vlm_required"
    methods: list[str]


class Table(BaseModel):
    """An extracted table with triangulation metadata."""

    table_id: str
    type: str
    page_range: list[int]
    headers: list[str]
    triangulation: TriangulationInfo
    rows: list[TableRow]


class Abstention(BaseModel):
    """Explicit declaration that a field or table could not be extracted."""

    field: str | None = None
    table_id: str | None = None
    reason: str  # Must reference an ErrorCode constant
    detail: str
    vlm_attempted: bool


class ConfidenceSummary(BaseModel):
    """Summary of extraction confidence across the document."""

    mean_confidence: float
    min_confidence: float
    fields_extracted: int
    fields_abstained: int
    vlm_used_count: int


class FinalOutput(BaseModel):
    """Complete extraction output for a single document."""

    doc_id: str
    schema_type: str
    status: str  # Literal["complete", "partial", "failed"]
    fields: dict[str, Field]
    tables: list[Table]
    abstentions: list[Abstention]
    confidence_summary: ConfidenceSummary
    pipeline_version: str


class ExtractionResult(BaseModel):
    """Result payload returned by GET /v1/results/{id}."""

    job_id: str
    trace_id: str
    output: FinalOutput


class JobSummary(BaseModel):
    """Summary of a single job within a batch."""

    job_id: str
    status: str
    schema_type: str | None = None


class BatchStatus(BaseModel):
    """Status of a batch and its constituent jobs."""

    batch_id: str
    tenant_id: str
    status: str  # Literal["pending", "complete", "delivered", "delivery_failed"]
    jobs: list[JobSummary]
    created_at: str
    completed_at: str | None = None
    delivery_status: str | None = None
