# PDF Ingestion Layer — Implementation Design

> **Purpose:** Ingestion layer for the reconciliation product. Not a general-purpose PDF parser.
> **Target:** 1 developer · 4 weeks · production-ready prototype · lift-and-shift code.
> **Document types:** Bank/custody statements · SWIFT/broker trade confirmations.
> **PDF profile:** Mostly digital (selectable text). Scanned handled as a self-hosted fallback.
> **Companion file:** `RedactionSettings.jsx` — settings panel UI for redaction configuration.

---


# Section 0 — Engineering Standards

> This section is mandatory. Every instruction here applies to all code produced for this project.
> It is additive to the main design — nothing below contradicts an existing decision; it enforces
> how those decisions are implemented.

---

## 0.1 Ports & Adapters — All External Dependencies

Every external dependency — AWS Bedrock, Presidio, PaddleOCR — must be wrapped behind an
internal interface (port). No pipeline stage may import or call a vendor SDK directly.
This makes every dependency swappable and every pipeline stage unit-testable in isolation.

Define the following ports before writing any pipeline code:

```python
# pipeline/ports.py

from abc import ABC, abstractmethod
from pipeline.models import Token, VLMFieldResult, RedactionLog, EntityRedactionConfig


class VLMClientPort(ABC):
    """
    Abstraction over any vision-language model used for field extraction fallback.
    Swap implementations (Bedrock, Azure OpenAI, local) by changing the binding — not the pipeline.
    """
    @abstractmethod
    def extract_field(
        self,
        page_image: bytes,
        field_name: str,
        field_description: str,
        schema_type: str,
    ) -> VLMFieldResult: ...


class RedactorPort(ABC):
    """
    Abstraction over any PII/PI redaction engine.
    Pipeline code never imports Presidio directly.
    """
    @abstractmethod
    def redact_page_text(
        self,
        text: str,
        config: list[EntityRedactionConfig],
    ) -> tuple[str, RedactionLog]: ...


class OCRClientPort(ABC):
    """
    Abstraction over any OCR backend.
    Allows swapping PaddleOCR for a different engine without touching the pipeline.
    """
    @abstractmethod
    def extract_tokens(self, page_image: bytes) -> list[Token]: ...
```

Concrete implementations (`BedrockVLMClient`, `PageRedactor`, `PaddleOCRClient`) live in
`pipeline/vlm/` and `pipeline/extractors/` and implement these ports. The pipeline only ever
receives the port type. Bindings are wired in `api/main.py` at startup via dependency injection.

Mock implementations for testing:

```python
# tests/mocks.py

class MockVLMClient(VLMClientPort):
    """Returns fixture responses. No network calls. Used in all unit and integration tests."""
    def __init__(self, fixture: VLMFieldResult):
        self._fixture = fixture

    def extract_field(self, page_image, field_name, field_description, schema_type):
        return self._fixture
```

**Hard rule:** If a file in `pipeline/` contains `import boto3`, `import presidio_analyzer`,
or `import paddleocr`, it is in violation. Those imports belong only in the concrete adapter
files under `pipeline/vlm/` and `pipeline/extractors/`.

---

## 0.2 Authentication & Tenant Authorisation

No route handler may be invoked without a verified tenant identity. Define this before any
route is built.

### Middleware — identity verification (AuthN)

```python
# api/middleware/auth.py

from fastapi import Request, HTTPException
from api.models.tenant import TenantContext

async def resolve_tenant(request: Request) -> TenantContext:
    """
    Extracts and validates the API key from the Authorization header.
    Resolves the associated tenant record from the database.
    Attaches TenantContext to request.state for use in route handlers and business logic.
    Raises HTTP 401 if the key is missing or invalid.
    Raises HTTP 403 if the tenant is suspended.
    """
    api_key = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not api_key:
        raise HTTPException(status_code=401, detail="ERR_AUTH_001: missing credentials")
    tenant = await tenant_repo.get_by_api_key(api_key)
    if not tenant:
        raise HTTPException(status_code=401, detail="ERR_AUTH_002: invalid credentials")
    if tenant.is_suspended:
        raise HTTPException(status_code=403, detail="ERR_AUTH_003: tenant suspended")
    request.state.tenant = tenant
    return tenant
```

Register as a FastAPI dependency on all protected routes — not as optional.

### Business layer — tenant scoping (AuthZ)

Every database query that touches `jobs`, `results`, or `feedback` must include a
`tenant_id` filter sourced from `request.state.tenant.id`. This is not optional and not
inherited from a base class — it must be explicit on every query.

```python
# Correct — tenant-scoped
result = await db.execute(
    select(Result).where(Result.job_id == job_id, Result.tenant_id == tenant.id)
)

# Violation — unscoped query, never acceptable
result = await db.execute(select(Result).where(Result.job_id == job_id))
```

The `vlm_enabled` flag check is a business-layer authorisation decision. It must live in
`pipeline/vlm/bedrock_client.py` before any VLM call, not in the route handler.

---

## 0.3 Structured Logging & Distributed Tracing

Every log line in this service must be structured JSON. No `print()`. No `logging.info("string")`.

### Setup

Use `structlog` with JSON output. Configure once in `api/main.py` at startup:

```python
# api/main.py (lifespan setup)

import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
```

### TraceId propagation

A `trace_id` is generated at ingress on `POST /extract` and stored on the `Job` record.
It must be bound to the logging context for every operation that follows:

```python
# api/routes/extract.py

import structlog
import uuid

log = structlog.get_logger()

@router.post("/v1/extract")
async def submit_extraction(request: ExtractionRequest, tenant: TenantContext = Depends(resolve_tenant)):
    trace_id = str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(trace_id=trace_id, tenant_id=tenant.id)
    log.info("extraction.submitted", filename=request.filename, schema_hint=request.schema_hint)
    # trace_id stored on Job record and passed into all downstream pipeline calls
```

Every pipeline stage, VLM call, OCR call, validator, and feedback write must log its outcome
with at minimum: `trace_id`, `doc_id`, `stage`, `outcome`. No stage is silent.

### Required log events (minimum)

| Event key | Logged when |
|---|---|
| `extraction.submitted` | Job accepted |
| `page.classified` | Each page classified (digital/scanned) |
| `triangulation.result` | Per table: score + verdict |
| `vlm.triggered` | VLM fallback invoked: field + reason |
| `vlm.verified` | VLM result accepted or rejected: field + outcome |
| `validation.failed` | Per validator failure: validator name + field |
| `extraction.complete` | Job complete: fields extracted, abstained, vlm_used counts |
| `extraction.error` | Unhandled failure: error code + message |

---

## 0.4 API Conventions

### Route versioning

All routes are prefixed `/v1/`. Breaking changes require `/v2/`. Never modify an existing
versioned contract in a breaking way in place.

```
POST   /v1/extract
GET    /v1/jobs/{id}
GET    /v1/results/{id}
POST   /v1/feedback/{job_id}
GET    /v1/healthz
GET    /v1/readyz
GET    /v1/tenants/{id}/redaction-config
PUT    /v1/tenants/{id}/redaction-config
```

### Response envelope

Every response — success and error — conforms to this envelope:

```python
# api/models/response.py

from pydantic import BaseModel
from typing import Generic, TypeVar

T = TypeVar("T")

class ResponseMeta(BaseModel):
    request_id: str      # the trace_id for this request
    timestamp: str       # ISO 8601

class APIResponse(BaseModel, Generic[T]):
    data: T | None
    meta: ResponseMeta
    error: APIError | None = None

class APIError(BaseModel):
    code: str            # e.g. "ERR_INGESTION_001" — from the error registry
    message: str         # human-readable; safe to surface to the client
    detail: str | None   # optional; omitted in production for sensitive errors
```

All route handlers return `APIResponse[T]`. Never return a bare Pydantic model from a route.

### Health check endpoints

Both endpoints must be implemented in Week 1 alongside the API scaffold:

```python
@router.get("/v1/healthz")
async def liveness():
    """Process is alive. No dependency checks."""
    return {"status": "ok"}

@router.get("/v1/readyz")
async def readiness(db: AsyncSession = Depends(get_db)):
    """
    Checks all runtime dependencies before reporting ready.
    Returns 503 if any dependency is unreachable — prevents traffic routing to broken instances.
    """
    checks = {
        "postgres": await check_postgres(db),
        "paddleocr": await check_paddleocr(),   # HTTP ping to OCR container
    }
    is_ready = all(checks.values())
    status_code = 200 if is_ready else 503
    return JSONResponse(status_code=status_code, content={"status": checks})
```

---

## 0.5 Error Registry

All errors emitted by this service use namespaced codes. Codes appear in log entries,
API error responses, and abstention reasons. They must never be ad-hoc strings.

Define centrally and expand as needed:

```python
# api/errors.py

class ErrorCode:
    # Authentication
    AUTH_MISSING_CREDENTIALS    = "ERR_AUTH_001"
    AUTH_INVALID_CREDENTIALS    = "ERR_AUTH_002"
    AUTH_TENANT_SUSPENDED       = "ERR_AUTH_003"

    # Ingestion
    INGESTION_INVALID_FILE_TYPE = "ERR_INGESTION_001"
    INGESTION_FILE_TOO_LARGE    = "ERR_INGESTION_002"
    INGESTION_ENCRYPTED_PDF     = "ERR_INGESTION_003"
    INGESTION_ZERO_PAGES        = "ERR_INGESTION_004"

    # Extraction
    EXTRACTION_PATTERN_NOT_FOUND    = "ERR_EXTRACT_001"
    EXTRACTION_SCHEMA_UNKNOWN       = "ERR_EXTRACT_002"
    EXTRACTION_TABLE_ABSTAINED      = "ERR_EXTRACT_003"

    # VLM
    VLM_DISABLED_FOR_TENANT         = "ERR_VLM_001"
    VLM_REDACTION_CONFIDENCE_LOW    = "ERR_VLM_002"
    VLM_RETURNED_NULL               = "ERR_VLM_003"
    VLM_VALUE_UNVERIFIABLE          = "ERR_VLM_004"
    VLM_BEDROCK_THROTTLED           = "ERR_VLM_005"
    VLM_PARSE_ERROR                 = "ERR_VLM_006"

    # Validation
    VALIDATION_ARITHMETIC_MISMATCH  = "ERR_VALID_001"
    VALIDATION_INVALID_IBAN         = "ERR_VALID_002"
    VALIDATION_INVALID_ISIN         = "ERR_VALID_003"
    VALIDATION_INVALID_BIC          = "ERR_VALID_004"
    VALIDATION_DATE_OUT_OF_RANGE    = "ERR_VALID_005"
    VALIDATION_INVALID_CURRENCY     = "ERR_VALID_006"
    VALIDATION_PROVENANCE_BROKEN    = "ERR_VALID_007"
```

Every `Abstention` reason field must reference an `ErrorCode` constant, not a raw string.

---

## 0.6 Additional Week-by-Week Checklist Items

The following items are additions to the existing build plan checklists. They do not replace
any existing items — append them to the relevant week.

### Week 1 additions
- [ ] `pipeline/ports.py`: define `VLMClientPort`, `RedactorPort`, `OCRClientPort`
- [ ] `api/errors.py`: define `ErrorCode` registry (seed with ingestion + auth codes)
- [ ] `api/middleware/auth.py`: API key resolution + `TenantContext` binding
- [ ] `structlog` configured in `api/main.py`; `trace_id` generated on `POST /v1/extract`
- [ ] `GET /v1/healthz` and `GET /v1/readyz` implemented and tested
- [ ] All routes prefixed `/v1/`; all responses wrapped in `APIResponse[T]` envelope
- [ ] `mypy --strict` added to `pyproject.toml` and passing on the Week 1 codebase
- [ ] `tests/mocks.py`: `MockVLMClient`, `MockRedactor`, `MockOCRClient` implemented

### Week 3 additions
- [ ] Circuit breaker on `BedrockVLMClient`: open after 3 consecutive failures; 60s recovery window
- [ ] Circuit breaker on `PaddleOCRClient`: open after 3 consecutive failures; 30s recovery window
- [ ] Retry policy on all external calls: exponential backoff with jitter; max 2 retries
- [ ] Failed VLM calls routed to abstention with `ERR_VLM_*` code — never silently dropped
- [ ] `trace_id` bound to structlog context in every pipeline stage

### Week 4 additions
- [ ] Graceful shutdown: FastAPI lifespan drains in-flight requests before closing DB connections
- [ ] SIGTERM handler configured in Docker Compose with 30s hard kill timeout
- [ ] Verify all queries in `jobs.py`, `results.py`, `feedback.py` include `tenant_id` filter
- [ ] Verify no `pipeline/` file imports `boto3`, `presidio_analyzer`, or `paddleocr` directly
- [ ] `mypy --strict` passing on full codebase with zero suppression comments
- [ ] All abstention `reason` fields reference `ErrorCode` constants — no raw strings


---

## Table of Contents

1. [Design Principles](#1-design-principles)
2. [Architecture Overview](#2-architecture-overview)
3. [Tech Stack](#3-tech-stack)
4. [Project Structure](#4-project-structure)
5. [Output Schema](#5-output-schema)
6. [Pipeline Stages](#6-pipeline-stages)
7. [Table Triangulation](#7-table-triangulation)
8. [VLM Fallback — Claude on AWS Bedrock](#8-vlm-fallback--claude-on-aws-bedrock)
9. [Schema Extractors](#9-schema-extractors)
10. [Validation & Constraint Solver](#10-validation--constraint-solver)
11. [Feedback Capture](#11-feedback-capture)
12. [Four-Week Build Plan](#12-four-week-build-plan)
13. [AWS Bedrock Setup Checklist](#13-aws-bedrock-setup-checklist)
14. [What Is Explicitly Out of Scope](#14-what-is-explicitly-out-of-scope)
15. [Known Risks & Mitigations](#15-known-risks--mitigations)
16. [Appendix — Key Library Notes](#16-appendix--key-library-notes)

---

## 1. Design Principles

Five principles drive every decision in this document and keep the build achievable in four weeks.

1. **No custom ML.** Use well-maintained open-source libraries and managed APIs. Train nothing.
2. **Rules before heuristics.** Every extracted field must be traceable to a rule, regex, or structural anchor — no guessing.
3. **Abstain, don't fabricate.** If a field can't be confidently extracted, emit `status: "abstained"` with a reason. Never silently fill a field. A wrong value in a reconciliation context is worse than a missing one.
4. **Provenance on everything.** Every field and every table row carries the page number and bounding box it came from. This is non-negotiable for the reconciliation use case and for audit.
5. **Disagreement is a signal.** Where two independent extraction methods diverge, that divergence is surfaced as a quality metric — not hidden. It is the primary internal quality signal before any human sees the output.

---

## 2. Architecture Overview

```
Client / Reconciliation Product
          │
          │  POST /extract
          │  GET  /jobs/{id}
          │  GET  /results/{id}
          │  POST /feedback/{job_id}
          ▼
┌─────────────────────────────────────────────────────────┐
│                     FastAPI Service                     │
│             async · Pydantic models · Docker            │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                    Ingestion Layer                      │
│      file validation · SHA-256 dedup · pikepdf repair   │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                  Per-Page Classifier                    │
│      native_text_coverage ≥ 0.80  →  DIGITAL            │
│      native_text_coverage  < 0.80  →  SCANNED           │
└───────────────┬──────────────────────────┬──────────────┘
                │                          │
┌───────────────▼────────────┐  ┌──────────▼─────────────┐
│     DIGITAL EXTRACTOR      │  │   SCANNED EXTRACTOR    │
│  pdfplumber + camelot-py   │  │  PaddleOCR (on-prem)   │
│  ~200 ms/page              │  │  ~2–4 s/page           │
└───────────────┬────────────┘  └──────────┬─────────────┘
                │                          │
┌───────────────▼──────────────────────────▼─────────────┐
│                  Table Triangulation                    │
│   pdfplumber result  vs  camelot result  per table      │
│   → disagreement_score  (0.0 – 1.0)                     │
│   → verdict:  agreement / soft_flag / hard_flag         │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                  Document Assembler                     │
│   merge pages · XY-cut reading order                    │
│   multi-page table stitching · provenance tagging       │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│             Schema Extractor  (rule-based)              │
│   bank_statement.py  ·  custody_statement.py            │
│   swift_confirm.py                                      │
│   regex + structural anchors · no LLM                  │
└──────────────────────────┬──────────────────────────────┘
                           │
             ┌─────────────▼────────────┐
             │  Required field abstained │
             │  OR hard_flag table       │
             └─────────────┬────────────┘
                           │ YES · vlm_enabled = True
┌──────────────────────────▼──────────────────────────────┐
│              VLM Fallback — Claude on Bedrock           │
│   Presidio redaction (tenant-configurable)              │
│   → redacted full page  →  Claude 3.5 Sonnet            │
│   → post-filter: verify value exists in token stream    │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│            Validation & Constraint Solver               │
│   arithmetic totals · required fields                   │
│   ISIN / BIC / IBAN · date plausibility · ISO 4217      │
└──────────┬───────────────────────────────┬──────────────┘
           │ PASS                          │ FAIL
┌──────────▼──────────┐      ┌─────────────▼─────────────┐
│   Package Output    │      │     Abstain + Flag        │
│   fields + tables   │      │  { status:"abstained",    │
│   + provenance      │      │    reason:"…" }           │
└──────────┬──────────┘      └─────────────┬─────────────┘
           └────────────────┬──────────────┘
┌───────────────────────────▼──────────────────────────────┐
│                      JSON Output                         │
│  doc_id · schema · fields · tables · abstentions         │
│  triangulation scores · vlm_used · confidence_summary    │
└───────────────────────────┬──────────────────────────────┘
                            │
              ┌─────────────▼────────────┐
              │     Feedback Capture      │
              │  triangulation flags      │
              │  + correction API writes  │
              │  → feedback table         │
              └───────────────────────────┘
```

---

## 3. Tech Stack

| Component | Library / Service | Reason |
|---|---|---|
| API framework | FastAPI + uvicorn | Async, fast, auto-generates OpenAPI docs |
| Request/response models | Pydantic v2 | Runtime validation, serialisation, schema export |
| Primary text + table extraction | pdfplumber | Character-level bboxes; reliable on digital PDFs |
| Table triangulation (second rail) | camelot-py (lattice mode) | Different algorithm to pdfplumber — disagreement between them is meaningful |
| PDF repair / normalise | pikepdf | Fixes malformed PDFs before extraction |
| Self-hosted OCR | PaddleOCR PP-OCRv4 (CPU) | Strong accuracy; Docker-friendly; fully on-prem; no third-party API |
| PII/PI redaction | Microsoft Presidio | Self-hosted; financial entity support; structured redaction log |
| VLM fallback | Claude 3.5 Sonnet via AWS Bedrock | Grounded extraction for hard cases; data stays within AWS |
| Job state + results | PostgreSQL (asyncpg) | Reliable; reuse existing infra if available |
| Containerisation | Docker + Docker Compose | `docker compose up` deploys the full stack |
| Testing | pytest + pytest-asyncio | Standard; fixtures per doc type |

**Python version:** 3.11+

**Infrastructure note on PaddleOCR:** Allocate a dedicated container with at least 2 GB RAM per worker. On CPU, expect 2–4 seconds per scanned page. This is acceptable given scanned pages are the minority of the workload. Bake model download into the Dockerfile `RUN` step — never fetch at container startup.

---

## 4. Project Structure

```
pdf_ingestion/
├── api/
│   ├── main.py                    # FastAPI app, lifespan, routers
│   ├── config.py                  # Settings (Pydantic BaseSettings)
│   ├── routes/
│   │   ├── extract.py             # POST /extract
│   │   ├── jobs.py                # GET  /jobs/{id}
│   │   ├── results.py             # GET  /results/{id}
│   │   └── feedback.py            # POST /feedback/{job_id}
│   └── models/
│       ├── request.py             # ExtractionRequest
│       └── response.py            # Field, Table, Abstention, TriangulationResult,
│                                  # ExtractionResult, ConfidenceSummary
│
├── pipeline/
│   ├── ingestion.py               # file validation, SHA-256 dedup, pikepdf repair
│   ├── classifier.py              # per-page native_text_coverage
│   ├── extractors/
│   │   ├── digital.py             # pdfplumber integration
│   │   ├── camelot_extractor.py   # camelot integration (table triangulation rail)
│   │   └── ocr.py                 # PaddleOCR wrapper
│   ├── triangulation.py           # disagreement score + routing verdict
│   ├── assembler.py               # merge pages, reading order, table stitch, provenance
│   ├── schemas/
│   │   ├── base.py                # BaseSchemaExtractor (ABC): find_field(), extract_table_by_header()
│   │   ├── bank_statement.py
│   │   ├── custody_statement.py
│   │   └── swift_confirm.py
│   ├── vlm/
│   │   ├── redactor.py            # Presidio wrapper, reads TenantRedactionSettings
│   │   ├── bedrock_client.py      # Claude 3.5 Sonnet on Bedrock
│   │   └── verifier.py            # post-filter: value must exist in token stream
│   ├── validator.py               # constraint solver (pure functions)
│   └── packager.py                # assemble FinalOutput
│
├── db/
│   ├── models.py                  # Job, Result, Feedback, VLMUsage, Tenant
│   └── migrations/                # Alembic
│
├── frontend/
│   └── RedactionSettings.jsx      # Redaction toggle settings panel (companion file)
│
├── tests/
│   ├── fixtures/                  # one PDF per schema type (digital + scanned variant)
│   ├── test_digital.py
│   ├── test_ocr.py
│   ├── test_triangulation.py
│   ├── test_vlm.py                # uses mock Bedrock client
│   ├── test_schemas.py
│   └── test_validators.py
│
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```

---

## 5. Output Schema

Every response from `GET /results/{id}` conforms to this structure. All types are Pydantic models — validation is enforced at the boundary.

```json
{
  "doc_id": "sha256:9f2c…",
  "schema_type": "bank_statement",
  "status": "complete",
  "fields": {
    "account_number": {
      "value": "GB29 NWBK 6016 1331 9268 19",
      "confidence": 0.99,
      "vlm_used": false,
      "provenance": {
        "page": 1,
        "bbox": [36, 120, 280, 134],
        "source": "native",
        "extraction_rule": "ACCOUNT_PATTERNS[0]"
      }
    },
    "closing_balance": {
      "value": 1204355.20,
      "original_string": "1,204,355.20",
      "confidence": 0.94,
      "vlm_used": true,
      "redaction_applied": true,
      "provenance": {
        "page": 3,
        "bbox": [512, 720, 574, 734],
        "source": "vlm",
        "extraction_rule": "bedrock_claude_3_5_sonnet"
      }
    }
  },
  "tables": [
    {
      "table_id": "t_01",
      "type": "transactions",
      "page_range": [2, 3],
      "headers": ["Date", "Description", "Debit", "Credit", "Balance"],
      "triangulation": {
        "disagreement_score": 0.04,
        "verdict": "agreement",
        "methods": ["pdfplumber", "camelot"]
      },
      "rows": [
        {
          "Date": "2024-11-01",
          "Description": "BACS PAYMENT",
          "Debit": null,
          "Credit": 50000.00,
          "Balance": 1150000.00,
          "provenance": { "page": 2, "bbox": [36, 200, 576, 214] }
        }
      ]
    }
  ],
  "abstentions": [
    {
      "field": "sort_code",
      "reason": "pattern_not_found",
      "detail": "regex XX-XX-XX matched 0 candidates on page 1",
      "vlm_attempted": false
    }
  ],
  "confidence_summary": {
    "overall": 0.96,
    "fields_extracted": 12,
    "fields_abstained": 1,
    "fields_via_vlm": 1,
    "tables_hard_flagged": 0,
    "pages_scanned": 0,
    "pages_digital": 3
  },
  "pipeline_version": "0.1.0"
}
```

---

## 6. Pipeline Stages

Each stage is a discrete module. The pipeline runs sequentially within a document; pages within a document are processed in parallel.

### Stage 1 — Ingestion

```python
# pipeline/ingestion.py

def ingest(file_bytes: bytes, filename: str) -> IngestedDocument:
    validate_file_type(file_bytes)           # magic bytes check — must be PDF
    validate_file_size(file_bytes)           # configurable max (default 50 MB)
    doc_hash = sha256(file_bytes).hexdigest()

    if cache.exists(doc_hash):
        return CachedResult(doc_hash)        # dedup: return prior result

    repaired = repair_pdf(file_bytes)        # pikepdf: fixes ~80% of malformed PDFs
    return IngestedDocument(hash=doc_hash, content=repaired, filename=filename)
```

`pikepdf` repair: `pikepdf.open(path, suppress_warnings=True)` then re-save. Log when repair was needed — it is itself a signal about document quality.

### Stage 2 — Per-Page Classification

```python
# pipeline/classifier.py

DIGITAL_THRESHOLD = 0.80   # configurable in Settings

def classify_page(page: pdfplumber.Page) -> PageClass:
    chars = page.chars
    if not chars:
        return PageClass.SCANNED

    page_area = page.width * page.height
    covered = sum((c["x1"] - c["x0"]) * (c["top"] - c["bottom"]) for c in chars)
    coverage = covered / page_area

    return PageClass.DIGITAL if coverage >= DIGITAL_THRESHOLD else PageClass.SCANNED
```

Classification is per page, not per document. A single document can have mixed page types.

### Stage 3 — Extraction Rails

**Digital rail (`extractors/digital.py`):**
- Uses `pdfplumber` for text runs (character-level bboxes, font info).
- Uses `pdfplumber.extract_table()` for initial table pass.
- Uses `camelot-py` (lattice mode) as the second table extraction rail for triangulation.
- Falls back to camelot stream mode if lattice returns zero tables.

**Scanned rail (`extractors/ocr.py`):**
- Sends page image to PaddleOCR service (separate Docker container, HTTP call).
- Returns token grid with bboxes and confidence scores.
- Result cached by `(page_hash, model_version)`.

### Stage 4 — Table Triangulation

Runs on every detected table. See §7 for full detail.

### Stage 5 — Document Assembly

```python
# pipeline/assembler.py

def assemble(pages: list[PageOutput]) -> AssembledDocument:
    ordered_pages = sort_by_page_number(pages)
    blocks = xy_cut_reading_order(ordered_pages)    # XY-cut for simple layouts
    tables = stitch_multipage_tables(blocks)        # match last/first row headers
    provenance = tag_all_nodes(blocks, tables)      # attach page + bbox to every node
    return AssembledDocument(blocks=blocks, tables=tables, provenance=provenance)
```

Multi-page table stitching: only stitch when the last row of page N and first row of page N+1 share the same header structure. Abstain rather than incorrectly merge.

### Stage 6 — Schema Extraction

See §9 for full detail.

### Stage 7 — VLM Fallback (conditional)

Triggered only when a required field is abstained or a table receives a `hard_flag`. See §8 for full detail.

### Stage 8 — Validation

See §10 for full detail.

### Stage 9 — Packaging

Assembles `FinalOutput`: schema payload + provenance + triangulation scores + VLM usage + confidence summary. Writes result to Postgres. Returns `job_id` for polling.

---

## 7. Table Triangulation

Triangulation is scoped to table regions only. Key-value field extraction uses a single rule-based rail — triangulation at the field level adds complexity without meaningful signal at this stage.

### Why it works

pdfplumber and camelot use fundamentally different approaches:
- **pdfplumber** reconstructs tables from character geometry (bounding boxes of individual characters).
- **camelot** detects tables from ruling lines (lattice mode) or whitespace column projections (stream mode).

For the same table region, disagreement between the two methods is a reliable signal that something structural is ambiguous or wrong — without requiring any human input and before the output leaves the parser.

### Implementation

```python
# pipeline/triangulation.py

from dataclasses import dataclass
from typing import Literal

@dataclass
class TriangulationResult:
    disagreement_score: float                          # 0.0 = full agreement, 1.0 = full disagreement
    verdict: Literal["agreement", "soft_flag", "hard_flag"]
    winner: Literal["pdfplumber", "camelot", "vlm_required"]
    methods: list[str]
    detail: str                                        # human-readable; logged for debugging


def triangulate_table(
    pdfplumber_table: Table,
    camelot_table: Table,
) -> TriangulationResult:
    score = compute_cell_disagreement(pdfplumber_table, camelot_table)

    if score < 0.10:
        return TriangulationResult(score, "agreement",  "pdfplumber",   [...], "High agreement.")
    elif score < 0.40:
        return TriangulationResult(score, "soft_flag",  "pdfplumber",   [...], "Moderate disagreement — flagged.")
    else:
        return TriangulationResult(score, "hard_flag",  "vlm_required", [...], "High disagreement — VLM required.")


def compute_cell_disagreement(t1: Table, t2: Table) -> float:
    if t1.shape != t2.shape:
        return 1.0                                     # shape mismatch is itself a hard signal

    mismatches, total = 0, t1.rows * t1.cols
    for r in range(t1.rows):
        for c in range(t1.cols):
            v1 = normalise_cell(t1.cells[r][c].text)
            v2 = normalise_cell(t2.cells[r][c].text)
            if not fuzzy_match(v1, v2, threshold=0.90):
                mismatches += 1

    return mismatches / total if total > 0 else 0.0
```

### Routing decisions

| Disagreement score | Verdict | Action |
|---|---|---|
| 0.00 – 0.10 | `agreement` | Use pdfplumber output; log score |
| 0.10 – 0.40 | `soft_flag` | Use pdfplumber output; flag in output; write to feedback store |
| 0.40 – 1.00 | `hard_flag` | Trigger VLM if `vlm_enabled = True`; else abstain the table |
| Shape mismatch | `hard_flag` | Always trigger VLM or abstain |

`soft_flag` and `hard_flag` verdicts are written to the feedback table automatically (§11).

---

## 8. VLM Fallback — Claude on AWS Bedrock

### When it triggers

VLM is called in exactly two cases:

1. A **required field** in the schema has been abstained after rule-based extraction.
2. A table has a **`hard_flag`** triangulation verdict.

VLM is never called for optional fields or `soft_flag` tables. This keeps call volume low and predictable. At 500–1,000 docs/month with a ~5–10% VLM rate, cost is negligible (sub-£5/month at current Bedrock pricing).

### Per-tenant consent gate

```python
# Hard stop — checked before any VLM call.
if not tenant_config.vlm_enabled:
    return Abstention(field=field_name, reason="vlm_disabled_for_tenant")
```

`vlm_enabled` defaults to `False`. It must be explicitly set to `True` per tenant. Some clients will not consent to sending document content outside their own systems regardless of redaction — the flag ensures this is always a deliberate opt-in, not a default.

---

### Step 1 — Presidio Redaction (tenant-configurable)

Before any content leaves the system, pages are redacted using Microsoft Presidio running fully on-prem.

**The redaction entity list is not hardcoded.** It is configurable per tenant and per schema type via the settings UI (`RedactionSettings.jsx`).

This is essential because `DATE_TIME` — which defaults to redacted — must be disabled for schemas where date fields are the target of VLM fallback (e.g. settlement date on `swift_confirm`, statement date on `bank_statement`). A hardcoded list would silently cause VLM to abstain on date fields when date extraction is precisely why VLM was called.

#### Redaction settings UI (`RedactionSettings.jsx`)

The companion settings panel exposes each Presidio entity as a toggle with two types of warning icon:

| Icon | Colour | Shown when |
|---|---|---|
| `i` — Data exposure risk | Red | A PII/PI entity is toggled **off** — it will be visible to the VLM |
| `!` — Extraction risk | Amber | An entity (e.g. `DATE_TIME`) is toggled **on** — VLM may be unable to recover that field type |

Tabs allow configuration at global level or per schema type. Schema-level settings override global settings for matching documents. A status bar shows current protection level: `FULLY PROTECTED`, `PARTIAL EXPOSURE`, or `HIGH EXPOSURE`. Changes apply to new jobs only.

#### Default entity configuration

| Entity | Default | Warning type | Risk if changed |
|---|---|---|---|
| `PERSON` | Redacted | PII exposure if OFF | Individual names visible to VLM |
| `EMAIL_ADDRESS` | Redacted | PII exposure if OFF | Email addresses visible to VLM |
| `PHONE_NUMBER` | Redacted | PII exposure if OFF | Phone numbers visible to VLM |
| `LOCATION` | Redacted | PII exposure if OFF | Address data visible to VLM |
| `IBAN_CODE` | Redacted | PII exposure if OFF | Account numbers visible to VLM |
| `CREDIT_CARD` | Redacted | PII exposure if OFF | Card numbers visible to VLM |
| `DATE_TIME` | Redacted | **Extraction risk if ON** | Dates hidden from VLM — disable for date-heavy schemas |

Never in the redaction list (hardcoded exclusions — these are extraction targets):
`CURRENCY`, `MONEY`, `ISIN` (custom recogniser), `BIC` (custom recogniser), `ORG`.

#### Tenant redaction config data model

```python
# db/models.py

class EntityRedactionConfig(BaseModel):
    entity_id: str    # e.g. "DATE_TIME", "PERSON", "IBAN_CODE"
    enabled: bool     # True = redact before VLM call

class TenantRedactionSettings(BaseModel):
    global_config: list[EntityRedactionConfig]
    schema_overrides: dict[str, list[EntityRedactionConfig]]
    # Keys: "bank_statement" | "custody_statement" | "swift_confirm"
    # Schema-level overrides replace global settings for that entity on matching docs.
    # Stored as JSONB on the Tenant table.
    # Resolved at job time: effective = global + schema_overrides[schema_type]
```

#### Redactor implementation

```python
# pipeline/vlm/redactor.py

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

class PageRedactor:
    def __init__(self):
        self.analyzer = AnalyzerEngine()
        self.anonymizer = AnonymizerEngine()

    def redact_page_text(
        self,
        text: str,
        redaction_config: list[EntityRedactionConfig],    # resolved at job time
    ) -> tuple[str, RedactionLog]:
        entities_to_redact = [e.entity_id for e in redaction_config if e.enabled]

        if not entities_to_redact:
            return text, RedactionLog(entities_redacted=[], redacted_count=0)

        results = self.analyzer.analyze(text=text, language="en", entities=entities_to_redact)
        redacted = self.anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators={"DEFAULT": OperatorConfig("replace", {"new_value": "[REDACTED]"})}
        )
        log = RedactionLog(
            entities_redacted=[(r.entity_type, r.start, r.end, r.score) for r in results],
            redacted_count=len(results),
            config_snapshot=entities_to_redact,    # what was active — stored for debugging
        )
        return redacted.text, log
```

The `RedactionLog` is stored with every job result. It is the primary debugging artefact when a VLM result is wrong — over-redaction is the most common cause of unexpected VLM abstention.

---

### Step 2 — Claude 3.5 Sonnet on AWS Bedrock

```python
# pipeline/vlm/bedrock_client.py

import boto3, json, base64

BEDROCK_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"

class BedrockVLMClient:
    def __init__(self, region: str, model_id: str = BEDROCK_MODEL_ID):
        self.client = boto3.client("bedrock-runtime", region_name=region)
        self.model_id = model_id

    def extract_field(
        self,
        redacted_page_image: bytes,    # PNG of the redacted full page
        field_name: str,
        field_description: str,        # e.g. "closing balance: final balance at statement end"
        schema_type: str,
    ) -> VLMFieldResult:

        image_b64 = base64.standard_b64encode(redacted_page_image).decode("utf-8")

        prompt = f"""You are extracting a specific field from a {schema_type}.

Field to extract: {field_name}
Description: {field_description}

Rules:
- Extract ONLY what is explicitly present on the page. Do not infer or calculate.
- Return the value exactly as it appears on the page (preserve original formatting).
- If the field is not present, return null for value.
- Your confidence should reflect how certain you are the value is correct.

Respond with ONLY a JSON object, no other text:
{{
  "value": "<extracted value or null>",
  "original_string": "<exact text as it appears on page>",
  "confidence": <0.0 to 1.0>,
  "rationale": "<one sentence: where on the page you found this>"
}}"""

        response = self.client.invoke_model(
            modelId=self.model_id,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 256,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64
                            }
                        },
                        {"type": "text", "text": prompt}
                    ]
                }]
            })
        )

        body = json.loads(response["body"].read())
        raw = body["content"][0]["text"]
        return self._parse(raw, field_name)

    def _parse(self, raw: str, field_name: str) -> VLMFieldResult:
        try:
            parsed = json.loads(raw.strip())
            return VLMFieldResult(
                field=field_name,
                value=parsed.get("value"),
                original_string=parsed.get("original_string"),
                confidence=float(parsed.get("confidence", 0.0)),
                rationale=parsed.get("rationale", ""),
                raw_response=raw
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            return VLMFieldResult(
                field=field_name, value=None, confidence=0.0,
                rationale=f"parse_error: {e}", raw_response=raw
            )
```

**Prompt discipline note:** The phrase "Extract ONLY what is explicitly present on the page. Do not infer or calculate." is load-bearing. For financial extraction, a hallucinated balance or ISIN is worse than an abstention. Do not soften this instruction.

---

### Step 3 — Post-filter: verify before accepting

The VLM output is never accepted blindly. The extracted value must be verifiable against the original (unredacted) token stream from pdfplumber.

```python
# pipeline/vlm/verifier.py

def verify_vlm_result(
    vlm_result: VLMFieldResult,
    token_stream: list[Token],          # from pdfplumber, unredacted
    fuzzy_threshold: float = 0.85,
) -> VerificationOutcome:
    """
    Check that the VLM's extracted value is actually present in the document.
    Prevents hallucinated values from entering the output.
    """
    if vlm_result.value is None:
        return VerificationOutcome(verified=False, reason="vlm_returned_null")

    normalised = normalise_for_comparison(vlm_result.value)

    for token in token_stream:
        if fuzzy_match(normalise_for_comparison(token.text), normalised, fuzzy_threshold):
            return VerificationOutcome(
                verified=True,
                matched_token=token,
                provenance=Provenance(
                    page=token.page,
                    bbox=token.bbox,
                    source="vlm",
                    extraction_rule=f"bedrock_{BEDROCK_MODEL_ID}"
                )
            )

    # Value not found in token stream — abstain rather than emit unverified output
    return VerificationOutcome(verified=False, reason="value_not_found_in_token_stream")
```

If verification fails, the field is emitted as `{ status: "abstained", reason: "vlm_value_unverifiable" }`. It is never silently accepted.

### VLM cost logging

```sql
CREATE TABLE vlm_usage (
    id              SERIAL PRIMARY KEY,
    job_id          UUID NOT NULL,
    tenant_id       TEXT NOT NULL,
    field_name      TEXT,
    model_id        TEXT NOT NULL,
    input_tokens    INT,
    output_tokens   INT,
    verified        BOOLEAN,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### VLM failure modes

| Failure | Response |
|---|---|
| `vlm_enabled = False` for tenant | Abstain immediately; do not call |
| Redaction confidence below threshold | Do not call VLM; abstain with `reason: redaction_confidence_low` |
| Bedrock throttling / timeout | Retry once with exponential backoff; then abstain |
| VLM returns null | Abstain; do not retry |
| VLM value fails post-filter | Abstain with `reason: vlm_value_unverifiable` |

---

## 9. Schema Extractors

### Base class

```python
# pipeline/schemas/base.py

class BaseSchemaExtractor(ABC):

    @abstractmethod
    def extract(self, doc: AssembledDocument) -> ExtractionResult: ...

    def find_field(
        self,
        doc: AssembledDocument,
        patterns: list[str],            # ordered list of regex patterns; tried in order
        label: str,                     # field name — used in provenance and abstention
        normaliser: Callable = None,    # e.g. parse_amount, parse_date, normalise_iban
        required: bool = True,
    ) -> Field | Abstention:
        """
        Searches token stream for the first pattern match.
        Returns Field (with page + bbox + extraction_rule) or Abstention (with reason).
        normaliser applied to raw string; original_string always preserved.
        """
        ...

    def extract_table_by_header(
        self,
        doc: AssembledDocument,
        expected_headers: list[str],    # fuzzy-matched against detected headers
        table_type: str,
    ) -> Table | Abstention:
        """
        Finds the table whose header row best matches expected_headers.
        Returns structured Table with per-row provenance.
        """
        ...
```

### Bank statement extractor (example)

```python
# pipeline/schemas/bank_statement.py

class BankStatementExtractor(BaseSchemaExtractor):

    ACCOUNT_PATTERNS = [
        r"(?i)account\s+(?:number|no\.?)[:\s]+([A-Z]{2}\d{2}[\w\s]{11,30})",  # IBAN
        r"(?i)account[:\s]+(\d{8,12})",                                         # domestic
    ]
    BALANCE_PATTERNS = [
        r"(?i)closing\s+balance[:\s]+([\d,]+\.\d{2})",
        r"(?i)balance\s+carried\s+forward[:\s]+([\d,]+\.\d{2})",
    ]

    FIELD_SPECS = [
        ("account_number", ACCOUNT_PATTERNS,  normalise_iban,  True),
        ("statement_date", [r"(?i)statement\s+date[:\s]+(\d{1,2}[\\/\-\.]\d{1,2}[\\/\-\.]\d{2,4})"], parse_date, True),
        ("closing_balance", BALANCE_PATTERNS, parse_amount,    True),
        ("opening_balance", [...],            parse_amount,    False),
    ]

    def extract(self, doc: AssembledDocument) -> ExtractionResult:
        fields, abstentions = {}, []

        for label, patterns, normaliser, required in self.FIELD_SPECS:
            result = self.find_field(doc, patterns, label, normaliser, required)
            if isinstance(result, Abstention):
                abstentions.append(result)
            else:
                fields[label] = result

        tx_table = self.extract_table_by_header(
            doc,
            expected_headers=["Date", "Description", "Debit", "Credit", "Balance"],
            table_type="transactions"
        )
        if isinstance(tx_table, Abstention):
            abstentions.append(tx_table)

        return ExtractionResult(fields=fields, tables=[tx_table] if isinstance(tx_table, Table) else [],
                                abstentions=abstentions)
```

### Schema router

Doc type is detected from structural signals — not an LLM. Structural signals include: presence of SWIFT message type tags (`{1:`, `{4:`), keyword density (e.g. "custody", "portfolio", "ISIN" vs "statement date", "sort code"), and page layout features.

If detection confidence is below threshold, the router returns `schema_type: "unknown"` and the job abstains entirely rather than applying the wrong schema.

---

## 10. Validation & Constraint Solver

Validators run after schema extraction (and after VLM if triggered). All validators are pure functions — easy to add, test, and audit independently.

```python
# pipeline/validator.py

VALIDATORS = [
    validate_arithmetic_totals,     # sum(debits) - sum(credits) ≈ closing - opening (±0.02 tolerance)
    validate_required_fields,       # abstain if required field still missing after VLM pass
    validate_iban,                  # mod-97 checksum
    validate_isin,                  # ISO 6166 check digit
    validate_bic,                   # format + length (8 or 11 characters)
    validate_date_range,            # not in the future; not more than 10 years ago
    validate_currency_codes,        # ISO 4217 three-letter codes
    validate_provenance_integrity,  # every field has page + bbox; bbox within page bounds
    validate_triangulation_flags,   # hard_flag tables without VLM resolution → abstain the table
]

def run_validators(
    result: ExtractionResult,
    doc: AssembledDocument,
) -> ValidationReport:
    failures = []
    for validator in VALIDATORS:
        outcome = validator(result, doc)
        if not outcome.passed:
            failures.append(outcome)
    return ValidationReport(failures=failures, passed=len(failures) == 0)
```

Arithmetic tolerance of ±0.02 covers rounding differences common in financial statements (e.g. lines rounded to 2dp that don't sum exactly).

---

## 11. Feedback Capture

### Design philosophy

At 500–1,000 docs/month, the feedback loop's primary value in Month 1 is **visibility** — surfacing extraction failures early, in one place, before they propagate to a reconciliation break. Automated improvement from feedback is a Month 2 exercise.

Reconciliation engine mismatches are deliberately excluded as direct feedback signals. A reconciliation mismatch has too many possible causes (data mapping, reference data, timing, counterparty data) to reliably attribute to the parser. The two signals chosen are both attributable directly to the extraction step.

### Signal sources

| Signal | Source | Quality | When it fires |
|---|---|---|---|
| **Triangulation flag** | Internal — pipeline | High (quantitative) | During extraction, before output is returned |
| **Correction** | External — correction API | Very high (ground truth) | When a downstream system or user identifies a wrong extracted value |

### Database schema

```sql
CREATE TABLE feedback (
    id                  SERIAL PRIMARY KEY,
    job_id              UUID        NOT NULL REFERENCES jobs(id),
    tenant_id           TEXT        NOT NULL,
    field_name          TEXT,                  -- null for table-level feedback
    table_id            TEXT,                  -- null for field-level feedback
    extracted_value     TEXT,                  -- what the parser produced
    correct_value       TEXT,                  -- null if flagging without a known answer
    source              TEXT        NOT NULL,  -- 'triangulation' | 'correction_api'
    triangulation_score FLOAT,
    vlm_was_used        BOOLEAN     DEFAULT FALSE,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_feedback_tenant ON feedback(tenant_id);
CREATE INDEX idx_feedback_job    ON feedback(job_id);
CREATE INDEX idx_feedback_field  ON feedback(field_name);
```

### Correction API endpoint

```python
# api/routes/feedback.py

class CorrectionRequest(BaseModel):
    field_name: str | None = None
    table_id: str | None = None
    correct_value: str | None = None    # omit to flag without knowing the correct answer
    notes: str | None = None

@router.post("/feedback/{job_id}", status_code=202)
async def submit_correction(
    job_id: UUID,
    payload: CorrectionRequest,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_tenant),
):
    """
    Accept a correction or flag from any downstream system.
    No UI required — callable programmatically.
    extracted_value is resolved from the stored job result automatically.
    Designed now so Month 2 UI integration requires no schema changes.
    """
    job_result = await db.get(Result, job_id)
    extracted_value = resolve_extracted_value(job_result, payload.field_name, payload.table_id)

    db.add(Feedback(
        job_id=job_id,
        tenant_id=tenant.id,
        field_name=payload.field_name,
        table_id=payload.table_id,
        extracted_value=str(extracted_value) if extracted_value else None,
        correct_value=payload.correct_value,
        source="correction_api",
        notes=payload.notes,
    ))
    await db.commit()
    return {"status": "accepted"}
```

### Triangulation auto-write

```python
# In assembler.py — fires automatically; no external trigger needed.

if tri_result.verdict in ("soft_flag", "hard_flag"):
    await feedback_store.write(
        job_id=job_id,
        tenant_id=tenant_id,
        table_id=table.table_id,
        extracted_value=table.to_summary_string(),
        source="triangulation",
        triangulation_score=tri_result.disagreement_score,
    )
```

### Month 2 — feedback review query (not built in Month 1)

```sql
-- Fields with the highest error signal, by schema type — run monthly by analyst.
SELECT
    j.schema_type,
    f.field_name,
    COUNT(*)                                                    AS signal_count,
    AVG(f.triangulation_score)                                  AS avg_disagreement,
    COUNT(CASE WHEN f.correct_value IS NOT NULL THEN 1 END)     AS corrections_with_answer
FROM feedback f
JOIN jobs j ON j.id = f.job_id
WHERE f.created_at > NOW() - INTERVAL '30 days'
GROUP BY j.schema_type, f.field_name
ORDER BY signal_count DESC;
```

This drives: which regex patterns to tighten, which fields to route to VLM by default, and which abstention thresholds to recalibrate.

---

## 12. Four-Week Build Plan

### Week 1 — API + Digital Extraction Foundation

- [ ] Project scaffold: `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `pytest` config
- [ ] FastAPI app: all four endpoints wired (extract, jobs, results, feedback stub)
- [ ] `Job`, `Result`, `Feedback`, `VLMUsage`, `Tenant` DB models + Alembic migration
- [ ] `ingestion.py`: file validation, SHA-256 dedup, pikepdf repair
- [ ] `classifier.py`: per-page `native_text_coverage` using pdfplumber
- [ ] `digital.py`: pdfplumber text + table extraction with provenance
- [ ] `assembler.py`: merge pages, XY-cut reading order, provenance tagging
- [ ] Pydantic response models: `Field`, `Table`, `Abstention`, `ExtractionResult`
- [ ] End-to-end test: digital bank statement PDF → structured JSON with provenance
- [ ] **Confirm AWS Bedrock access and Claude model opt-in** (takes 24–48h in some regions — do not leave this to Week 3)

**Milestone:** Clean digital PDF → structured JSON with provenance. Fast path end-to-end.

---

### Week 2 — Schema Extractors + Validators

- [ ] `base.py`: `find_field()`, `extract_table_by_header()`, abstention logic
- [ ] `bank_statement.py`: account number, dates, balances, transaction table
- [ ] `custody_statement.py`: portfolio ID, valuation date, positions table (ISIN, quantity, value)
- [ ] `swift_confirm.py`: trade date, settlement date, ISIN, quantity, price, counterparty BIC
- [ ] Schema router: detect doc type from structural signals (no LLM)
- [ ] `validator.py`: arithmetic, required fields, IBAN/ISIN/BIC checksums, date range, ISO 4217, provenance integrity
- [ ] `ValidationReport` model; wire into packager
- [ ] Tests for each schema extractor and each validator

**Milestone:** All three schema types extracting and validating end-to-end, including abstentions.

---

### Week 3 — Triangulation + VLM + OCR Fallback

- [ ] `camelot_extractor.py`: camelot lattice + stream extraction; same output interface as pdfplumber
- [ ] `triangulation.py`: cell disagreement score, routing verdict
- [ ] Wire triangulation into assembler; triangulation scores in output; auto-write to feedback
- [ ] `redactor.py`: Presidio setup, custom recognisers for ISIN + BIC, redaction log
- [ ] `TenantRedactionSettings` model; resolution logic (global + schema override)
- [ ] `bedrock_client.py`: Claude 3.5 Sonnet on Bedrock, structured JSON prompt, retry + error handling
- [ ] `verifier.py`: post-filter against unredacted token stream
- [ ] VLM trigger logic: abstained required field + hard_flag → redact → VLM → verify → emit or abstain
- [ ] `vlm_usage` table + logging
- [ ] PaddleOCR Docker service; `ocr.py` HTTP wrapper; wire into page classifier routing
- [ ] Multi-page table stitching in assembler
- [ ] Error handling: malformed PDF, password-protected, zero pages, oversized file
- [ ] `test_triangulation.py`: agreement / soft_flag / hard_flag / shape mismatch cases
- [ ] `test_vlm.py`: mock Bedrock client; verify post-filter rejects hallucinated values

**Milestone:** Triangulation on all tables; VLM recovering hard-abstained fields; scanned pages handled; OCR fallback working.

---

### Week 4 — Testing, Hardening, Deployment

- [ ] Test fixtures: digital + scanned variant for each schema type
- [ ] `test_schemas.py`: field extraction per schema; abstention on missing fields; normalisation
- [ ] `test_validators.py`: arithmetic pass/fail; IBAN/ISIN/BIC format cases; date edge cases
- [ ] Load test: 50-page document; measure p50/p95 latency per page; memory profile PaddleOCR
- [ ] `feedback.py` endpoint: wired and tested (stores correctly; returns 202)
- [ ] `docker compose up` deploys API + Postgres + PaddleOCR in one command
- [ ] `RedactionSettings.jsx` connected to `GET/PUT /api/tenants/{id}/redaction-config`
- [ ] README: setup, env vars, adding a new schema, running tests, Bedrock IAM setup
- [ ] OpenAPI docs: review and annotate all endpoints
- [ ] Smoke test against real document samples from target clients (if available)

**Milestone:** Fully tested, containerised, documented service. Ready for integration with the reconciliation product.

---

## 13. AWS Bedrock Setup Checklist

Must be confirmed before Week 3 begins. Ideally completed by end of Week 1 to avoid blocking.

- [ ] AWS account with Bedrock enabled in target region (`eu-west-1` recommended for UK data residency)
- [ ] Claude 3.5 Sonnet model access enabled via Bedrock model access console (requires explicit opt-in — not automatic)
- [ ] IAM role or user with `bedrock:InvokeModel` permission scoped to `anthropic.claude-3-5-sonnet-20241022-v2:0`
- [ ] AWS credentials available inside Docker container (IAM role if EC2/ECS; `~/.aws/credentials` for local dev)
- [ ] Bedrock VPC endpoint configured if network policy requires it
- [ ] `AWS_REGION` and `BEDROCK_MODEL_ID` in `.env` / environment config

```python
# api/config.py

class Settings(BaseSettings):
    # AWS / Bedrock
    aws_region: str = "eu-west-1"
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    vlm_confidence_threshold: float = 0.80       # minimum to accept VLM output

    # Triangulation thresholds
    triangulation_soft_flag_threshold: float = 0.10
    triangulation_hard_flag_threshold: float = 0.40

    # Services
    paddleocr_endpoint: str = "http://paddleocr:8080"
    database_url: str

    # Extraction
    digital_page_threshold: float = 0.80         # native_text_coverage cutoff
    vlm_verifier_fuzzy_threshold: float = 0.85   # min match to accept VLM value

    class Config:
        env_file = ".env"
```

---

## 14. What Is Explicitly Out of Scope

These are deferred, not forgotten. Add them when volume or client requirements justify the investment.

| Deferred | Rationale |
|---|---|
| Full dual-rail fusion (native + vision on all regions) | Triangulation covers the meaningful case (tables); full fusion adds ~1.5× compute for marginal gain on digital docs |
| Custom ML models (layout, table structure) | No training data, no infrastructure, no timeline for Month 1 |
| Canonical Document Graph (CDG) | Pydantic models are sufficient for the rule-based approach; CDG adds schema migration overhead |
| Differentiable rendering alignment | Only needed for bulletproof provenance on ambiguous scanned docs at scale |
| Active learning loop | Requires labelled production data and annotation tooling; Month 2+ |
| Feedback review UI / tooling | Endpoint is ready; SQL query is defined; UI is Month 2 |
| Multi-tenant physical isolation | Add when regulated-client requirements demand dedicated pools or separate KMS keys |
| Streaming / incremental results | Add when documents routinely exceed ~50 pages |
| VLM as primary extractor (non-fallback) | Too slow and costly as a first pass; VLM on failure only |
| Fine-tuning Claude on Bedrock | Unnecessary at this volume and doc type |
| Reconciliation mismatch as feedback signal | Too noisy; too many possible causes; excluded by design |

---

## 15. Known Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Presidio over-redacts → VLM abstains on date fields | Medium | `DATE_TIME` toggle in `RedactionSettings.jsx`; redaction log is the first debugging step; per-schema overrides allow date redaction off for `swift_confirm` by default |
| Bedrock IAM not configured before Week 3 | Medium | Start this in Week 1; mock Bedrock client in tests means Week 3 is not blocked even if access is delayed |
| camelot fails on borderless tables | Medium | `soft_flag` uses pdfplumber; `hard_flag` routes to VLM. Borderless tables rarely reach `hard_flag` unless genuinely ambiguous |
| New client PDF format breaks regex patterns | Medium | Schema modules are isolated; one pattern change is a one-line edit. Abstention rate per client per field is the early-warning metric |
| PaddleOCR RAM pressure | Low-Medium | Dedicated Docker container; 1 worker per 2 GB RAM; scanned pages are the minority of workload |
| VLM post-filter too strict → abstains a verifiable value | Low | Tune `vlm_verifier_fuzzy_threshold` on fixture documents; start at 0.85, adjust to 0.80 if needed |
| Triangulation adds unacceptable latency | Low | camelot adds ~100–300ms per table on digital PDFs. Acceptable at this volume. Confirm in Week 4 load test |
| Schema router misclassifies doc type | Low-Medium | Return `schema_type: "unknown"` and abstain entirely rather than applying the wrong schema silently |

---

## 16. Appendix — Key Library Notes

**pdfplumber vs PyMuPDF:** pdfplumber is preferred — it exposes character-level bboxes and `extract_table()` directly. PyMuPDF is faster but table extraction requires more manual work. Keep PyMuPDF as a fallback if pdfplumber fails on a specific PDF variant.

**camelot-py flavour selection:** Start with `lattice` (ruled tables — common in bank statements and SWIFT confirms). Fall back to `stream` (whitespace-delimited — common in some custody reports) if lattice returns zero tables. Log which flavour was used; it reveals which document types need stream mode by default.

**Presidio custom recognisers:** Install `presidio-analyzer`, `presidio-anonymizer`, and `en_core_web_lg` (spaCy). Add custom pattern recognisers for ISIN (12-character alphanumeric with check digit) and BIC (8 or 11 characters, SWIFT format) so these are never accidentally redacted.

**PaddleOCR model download:** Bake model download into the `Dockerfile RUN` step using `paddleocr --lang en` to pre-fetch. Never fetch at container startup — it makes cold starts unpredictable and fails in environments without outbound internet access.

**pikepdf repair pattern:**
```python
import pikepdf
with pikepdf.open(input_path, suppress_warnings=True) as pdf:
    pdf.save(output_path)
```
Repairs ~80% of malformed PDFs silently. Log when repair was applied — a document needing repair is a signal about source quality worth tracking per client.

**Claude prompt for financial extraction:** The constraint "Extract ONLY what is explicitly present. Do not infer or calculate." is load-bearing. A hallucinated closing balance or ISIN that passes the post-filter fuzzy match (because a similar number exists elsewhere on the page) is the worst failure mode. Do not soften this instruction and do not add "helpful" examples that show inference.

**Arithmetic validator tolerance:** Use ±0.02 as the default tolerance for balance checks. Financial statements commonly have rows rounded to 2 decimal places that don't sum to exactly the stated total due to rounding. A tighter tolerance produces false failures; a looser tolerance misses real extraction errors.
