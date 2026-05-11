# Implementation Plan: PDF Ingestion Layer

## Overview

This plan implements a production-ready PDF extraction service for the reconciliation product. The system processes bank/custody statements and SWIFT/broker trade confirmations, extracting structured data with full provenance tracking. The architecture follows a pipeline pattern with discrete stages: ingestion, classification, extraction, triangulation, assembly, schema extraction, VLM fallback, validation, packaging, and delivery. Implementation uses Python 3.11+ with FastAPI, pdfplumber, camelot-py, PaddleOCR, Presidio, and Claude 3.5 Sonnet on AWS Bedrock.

## Tasks

- [x] 1. Project scaffold, core interfaces, and API foundation (Week 1)
  - [x] 1.1 Set up project structure, dependencies, and configuration
    - Create directory structure matching the design (`api/`, `pipeline/`, `db/`, `tests/`, `frontend/`)
    - Create `pyproject.toml` with all dependencies (FastAPI, uvicorn, pydantic v2, pdfplumber, camelot-py, pikepdf, structlog, asyncpg, alembic, boto3, presidio-analyzer, presidio-anonymizer, httpx, pytest, pytest-asyncio, hypothesis)
    - Create `api/config.py` with `Settings(BaseSettings)` including all configuration fields from the design
    - Create `.env.example` with all required environment variables
    - Configure `mypy --strict` in `pyproject.toml`
    - _Requirements: 17.1, 17.4_

  - [x] 1.2 Define port interfaces and error registry
    - Create `pipeline/ports.py` with `VLMClientPort`, `RedactorPort`, `OCRClientPort`, `IngestionTriggerPort`, `DeliveryPort` abstract base classes
    - Create `api/errors.py` with the full `ErrorCode` registry (AUTH, INGESTION, EXTRACT, VLM, VALID, DELIVERY namespaces)
    - _Requirements: 17.1, 19.1_

  - [x] 1.3 Implement Pydantic data models
    - Create `api/models/response.py` with `APIResponse[T]`, `APIError`, `ResponseMeta`, `Field`, `Table`, `TableRow`, `Abstention`, `TriangulationInfo`, `ConfidenceSummary`, `FinalOutput`, `ExtractionResult`, `BatchStatus`, `JobSummary`, `Provenance`
    - Create `api/models/request.py` with `ExtractionRequest` (including `batch_id` optional parameter)
    - Create `api/models/tenant.py` with `TenantContext`, `TenantRedactionSettings`, `EntityRedactionConfig`, `DeliveryConfig`
    - Create `pipeline/models.py` with internal pipeline models (`Token`, `VLMFieldResult`, `RedactionLog`, `VerificationOutcome`, `PageOutput`, `IngestedDocument`, `CachedResult`, `AssembledDocument`, `TriangulationResult`, `DeliveryAttemptResult`, `IngestionEvent`)
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 13.1, 13.2, 15.1, 15.2_

  - [x] 1.4 Implement FastAPI application with structlog, auth middleware, and health checks
    - Create `api/main.py` with FastAPI app, lifespan, structlog JSON configuration, router registration, and dependency injection wiring
    - Create `api/middleware/auth.py` with `resolve_tenant()` dependency (API key validation, tenant lookup, suspension check)
    - Create `api/routes/health.py` with `GET /v1/healthz` (liveness) and `GET /v1/readyz` (readiness with dependency checks)
    - Ensure all routes are prefixed `/v1/`
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.6, 14.1, 14.5, 20.1, 20.2, 20.3_

  - [ ]* 1.5 Write property tests for API response envelope and auth
    - **Property 16: API Response Envelope Compliance** — every response conforms to APIResponse[T] with non-null request_id and valid ISO 8601 timestamp
    - **Property 18: Authentication on All Routes** — no protected route can be invoked without verified tenant identity
    - **Validates: Requirements 12.1, 12.6, 13.1, 13.2, 13.5**

  - [x] 1.6 Implement database models and migrations
    - Create `db/models.py` with SQLAlchemy models: `Job`, `Result`, `Feedback`, `VLMUsage`, `Tenant`, `Batch`, `DeliveryLog`
    - Set up Alembic migrations directory and initial migration
    - Ensure `Batch` model includes `batch_id`, `tenant_id`, `status`, `created_at`, `completed_at`, `delivery_status`
    - Add `delivery_config` field to `Tenant` model
    - _Requirements: 15.1, 15.5, 16.7_

  - [x] 1.7 Implement POST /v1/extract endpoint with trace_id generation
    - Create `api/routes/extract.py` with file upload, schema_type detection, optional `batch_id` parameter, trace_id generation, and async job dispatch
    - Generate `trace_id` at ingress and bind to structlog context
    - Return `APIResponse[JobResponse]` with HTTP 202
    - Log `extraction.submitted` event
    - _Requirements: 13.1, 14.2, 14.3, 15.1, 15.2_

  - [x] 1.8 Implement GET /v1/jobs/{id}, GET /v1/results/{id}, and GET /v1/batches/{batch_id} endpoints
    - Create `api/routes/jobs.py` with tenant-scoped job status retrieval
    - Create `api/routes/results.py` with tenant-scoped result retrieval
    - Create `api/routes/batches.py` with tenant-scoped batch status and job list
    - Ensure all queries include `tenant_id` filter
    - Return 404 with `ERR_DELIVERY_003` if batch not found for tenant
    - _Requirements: 12.5, 13.1, 15.5, 15.6_

  - [x] 1.9 Implement ingestion layer (validation, dedup, repair)
    - Create `pipeline/ingestion.py` with `ingest()` function: magic bytes validation, file size check, SHA-256 dedup, pikepdf repair
    - Reject non-PDF with `ERR_INGESTION_001` (HTTP 422)
    - Reject oversized files with `ERR_INGESTION_002` (HTTP 413)
    - Reject password-protected PDFs with `ERR_INGESTION_003` (HTTP 422)
    - Return `CachedResult` for duplicate SHA-256 hashes
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

  - [ ]* 1.10 Write property test for deduplication determinism
    - **Property 8: Deduplication Determinism** — identical file bytes always produce the same doc_id
    - **Validates: Requirements 1.4, 1.5, 1.8**

  - [x] 1.11 Implement per-page classifier
    - Create `pipeline/classifier.py` with `classify_page()`: compute native_text_coverage, threshold at 0.80
    - Handle zero-character pages as SCANNED
    - Log `page.classified` event per page
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ]* 1.12 Write property test for classification consistency
    - **Property 9: Classification Consistency** — DIGITAL implies coverage ≥ 0.80, SCANNED implies coverage < 0.80
    - **Validates: Requirements 2.1, 2.2, 2.4, 2.5**

  - [x] 1.13 Implement digital extractor
    - Create `pipeline/extractors/digital.py` with `extract_digital_page()`: character-level text with bboxes, font metadata, table extraction via pdfplumber
    - Tag every extracted element with page number and bounding box provenance
    - _Requirements: 3.1, 3.2, 3.5_

  - [x] 1.14 Implement document assembler
    - Create `pipeline/assembler.py` with `assemble()`: page ordering, XY-cut reading order, multi-page table stitching, provenance tagging
    - _Requirements: 10.1_

  - [x] 1.15 Implement mock implementations for testing
    - Create `tests/mocks.py` with `MockVLMClient`, `MockRedactor`, `MockOCRClient`, `MockDeliveryClient`
    - Ensure mocks implement all port interfaces correctly
    - _Requirements: 17.5_

- [x] 2. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Schema extractors and validators (Week 2)
  - [x] 3.1 Implement base schema extractor
    - Create `pipeline/schemas/base.py` with `BaseSchemaExtractor` ABC: `find_field()`, `extract_table_by_header()` methods
    - Implement pattern-based field extraction with regex + structural anchors
    - Implement normalisation functions (`parse_amount`, `parse_date`, `normalise_iban`)
    - Ensure first-match-wins pattern ordering
    - Produce `Abstention` with `ERR_EXTRACT_001` when required field not found
    - _Requirements: 6.3, 6.4, 6.5, 6.6_

  - [x] 3.2 Implement bank_statement schema extractor
    - Create `pipeline/schemas/bank_statement.py` extending `BaseSchemaExtractor`
    - Extract fields: account_number, statement_date, closing_balance, opening_balance
    - Extract transactions table by header matching
    - Include provenance on all extracted fields
    - _Requirements: 6.1, 6.3, 6.5, 6.6_

  - [x] 3.3 Implement custody_statement schema extractor
    - Create `pipeline/schemas/custody_statement.py` extending `BaseSchemaExtractor`
    - Extract fields specific to custody statements (holdings, valuations, ISIN codes)
    - Include provenance on all extracted fields
    - _Requirements: 6.1, 6.3, 6.5, 6.6_

  - [x] 3.4 Implement swift_confirm schema extractor
    - Create `pipeline/schemas/swift_confirm.py` extending `BaseSchemaExtractor`
    - Extract fields specific to SWIFT/broker trade confirmations
    - Include provenance on all extracted fields
    - _Requirements: 6.1, 6.3, 6.5, 6.6_

  - [x] 3.5 Implement schema router
    - Add schema detection logic based on structural signals (no LLM)
    - Route to appropriate extractor or set schema_type to "unknown" with `ERR_EXTRACT_002`
    - _Requirements: 6.2_

  - [ ]* 3.6 Write property tests for schema extraction
    - **Property 6: No Silent Fabrication** — every required field is either extracted or explicitly abstained
    - **Property 1: Provenance Completeness** — every extracted field has valid provenance
    - **Validates: Requirements 6.4, 6.6, 10.1, 10.2, 10.3, 10.4, 11.3**

  - [x] 3.7 Implement validation engine
    - Create `pipeline/validator.py` with `run_validators()` and all validator pure functions:
      - `validate_arithmetic_totals` (±0.02 tolerance)
      - `validate_iban` (mod-97 checksum)
      - `validate_isin` (ISO 6166 check digit)
      - `validate_bic` (8 or 11 character format)
      - `validate_date_range` (not future, not >10 years past)
      - `validate_currency_codes` (ISO 4217)
      - `validate_provenance_integrity` (page + bbox within bounds)
    - Execute all validators regardless of individual failures
    - Validators must be pure functions (no mutation)
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9_

  - [ ]* 3.8 Write property tests for validators
    - **Property 7: Arithmetic Consistency for Bank Statements** — arithmetic identity holds or validation report contains failure
    - **Property 2: Abstention Integrity** — every abstention has non-null reason referencing ErrorCode and non-null detail
    - **Validates: Requirements 9.1, 11.1, 11.2, 11.4, 19.2**

  - [x] 3.9 Implement packager
    - Create `pipeline/packager.py` with `package_result()`: assemble FinalOutput with confidence summary, pipeline version, all metadata
    - Persist result to PostgreSQL
    - _Requirements: 10.1, 13.1_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Triangulation, VLM fallback, OCR, and delivery (Week 3)
  - [x] 5.1 Implement camelot extractor
    - Create `pipeline/extractors/camelot_extractor.py` with `extract_tables_camelot()`: lattice mode first, stream mode fallback
    - Log which flavour was used per table
    - Consistent output format with pdfplumber tables
    - _Requirements: 3.3, 3.4_

  - [x] 5.2 Implement table triangulation engine
    - Create `pipeline/triangulation.py` with `triangulate_table()` and `compute_cell_disagreement()`
    - Implement cell-by-cell comparison with fuzzy matching (threshold 0.90)
    - Shape mismatch → score 1.0, hard_flag
    - Score < 0.10 → agreement, pdfplumber wins
    - Score 0.10–0.40 → soft_flag, pdfplumber wins
    - Score ≥ 0.40 → hard_flag, vlm_required
    - Auto-write feedback record on soft_flag/hard_flag
    - Log `triangulation.result` event per table
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [ ]* 5.3 Write property test for triangulation
    - **Property 3: Triangulation Score Bounds and Verdict Mapping** — score in [0.0, 1.0], deterministic verdict mapping
    - **Property 11: Feedback Auto-Write on Flags** — soft_flag/hard_flag always produces feedback record
    - **Validates: Requirements 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 21.2**

  - [x] 5.4 Implement Presidio redactor
    - Create `pipeline/vlm/redactor.py` with `PageRedactor` implementing `RedactorPort`
    - Support per-tenant global config and per-schema overrides
    - Replace detected PII with "[REDACTED]"
    - Produce `RedactionLog` with positions, types, and config_snapshot
    - Never mutate original text
    - Return original text unchanged when no entities enabled
    - _Requirements: 7.3, 7.4, 8.1, 8.2, 8.3, 8.4, 8.5_

  - [ ]* 5.5 Write property test for redaction
    - **Property 10: Redaction Before VLM** — every VLM invocation has a RedactionLog with non-null config_snapshot
    - **Validates: Requirements 7.3, 7.4**

  - [x] 5.6 Implement Bedrock VLM client with circuit breaker
    - Create `pipeline/vlm/bedrock_client.py` with `BedrockVLMClient` implementing `VLMClientPort`
    - Check `vlm_enabled` flag before any call (abstain with `ERR_VLM_001` if disabled)
    - Implement circuit breaker: open after 3 consecutive failures, 60s recovery window
    - Retry once with exponential backoff on throttle/timeout, then abstain with `ERR_VLM_005`
    - Maximum 2 Bedrock API calls per field (1 initial + 1 retry)
    - Log `vlm.triggered` event
    - _Requirements: 7.1, 7.2, 7.8, 7.9, 18.1_

  - [x] 5.7 Implement VLM verifier (post-filter)
    - Create `pipeline/vlm/verifier.py` with `verify_vlm_result()`: fuzzy match against unredacted token stream (threshold 0.85)
    - Reject with `ERR_VLM_004` if value not found in token stream
    - Abstain with `ERR_VLM_003` if VLM returns null
    - Log `vlm.verified` event with outcome
    - _Requirements: 7.5, 7.6, 7.7_

  - [ ]* 5.8 Write property tests for VLM
    - **Property 4: VLM Never Called Without Consent** — vlm_used=True implies tenant vlm_enabled=True
    - **Property 5: VLM Output Always Verified Against Token Stream** — vlm_used=True implies token match ≥ 0.85
    - **Property 19: Circuit Breaker Behaviour** — after 3 failures, circuit opens and rejects immediately
    - **Validates: Requirements 7.2, 7.5, 7.6, 18.1, 18.2, 18.3, 18.4**

  - [x] 5.9 Implement PaddleOCR client with circuit breaker
    - Create `pipeline/extractors/ocr.py` with OCR extraction implementing `OCRClientPort`
    - HTTP communication with PaddleOCR Docker container
    - Cache results by (page_hash, model_version)
    - Circuit breaker: open after 3 consecutive failures, 30s recovery window
    - Abstain on all scanned pages if service unavailable (continue digital pages)
    - _Requirements: 4.1, 4.2, 4.3, 18.2_

  - [x] 5.10 Implement delivery orchestrator and webhook client
    - Create `pipeline/delivery.py` with `WebhookDeliveryClient` implementing `DeliveryPort`
    - Implement `on_job_complete()`: route to standalone delivery or batch completion check
    - Implement `check_and_deliver_batch()`: check all jobs terminal, assemble payload, deliver
    - Implement `assemble_standalone_payload()` and `assemble_batch_payload()`
    - Exponential backoff with jitter, max 3 retries
    - Mark `delivery_status` as "delivery_failed" after all retries exhausted
    - Log `delivery.triggered`, `delivery.success`, `delivery.failed`, `delivery.skipped`, `batch.complete` events
    - Delivery failures never affect job status
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7_

  - [ ]* 5.11 Write property tests for delivery
    - **Property 20: Batch Delivery Only on All Terminal** — delivery fires iff all batch jobs are terminal
    - **Property 21: Standalone Jobs Deliver Immediately** — standalone job with delivery enabled triggers immediate delivery
    - **Property 22: Delivery Failures Never Affect Job Status** — delivery_failed never mutates job status
    - **Property 23: All Delivery Attempts Logged with Trace ID** — every attempt has trace_id, timestamp, attempt_number
    - **Validates: Requirements 15.3, 15.4, 16.1, 16.6, 16.7**

  - [x] 5.12 Implement tenant redaction config endpoints
    - Create `api/routes/tenants.py` with `GET /v1/tenants/{id}/redaction-config` and `PUT /v1/tenants/{id}/redaction-config`
    - Tenant-scoped access control
    - _Requirements: 8.6_

  - [x] 5.13 Implement feedback endpoint
    - Create `api/routes/feedback.py` with `POST /v1/feedback/{job_id}` accepting corrections
    - Tenant-scoped queries
    - _Requirements: 21.1, 21.3_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Testing, hardening, and deployment (Week 4)
  - [x] 7.1 Create test fixtures
    - Create `tests/fixtures/` with one PDF per schema type (digital + scanned variant): bank_statement, custody_statement, swift_confirm
    - Create fixture data for mock responses (VLM results, OCR tokens, delivery responses)
    - _Requirements: 17.5_

  - [ ]* 7.2 Write integration tests for full pipeline
    - Test digital bank statement PDF → structured JSON with all fields and provenance
    - Test scanned custody statement → OCR path → structured output
    - Test document with hard_flag table → VLM fallback triggered (mock Bedrock)
    - Test correction API → feedback table populated correctly
    - Test dedup: same PDF submitted twice → cached result returned
    - _Requirements: 1.5, 3.5, 4.1, 5.5, 6.6, 7.1_

  - [ ]* 7.3 Write integration tests for delivery flow
    - Test batch completion → delivery: submit 3 jobs with same batch_id → all complete → batch payload assembled → webhook fired
    - Test delivery failure retry: mock 500 responses → verify exponential backoff → mark delivery_failed after 3 retries
    - Test standalone job → immediate delivery: submit job without batch_id → job completes → result pushed to callback_url
    - Test delivery with disabled config: job completes → delivery_config.enabled=False → no webhook fired, warning logged
    - _Requirements: 15.3, 16.1, 16.4, 16.5_

  - [ ]* 7.4 Write property tests for remaining properties
    - **Property 12: No Direct SDK Imports in Pipeline** — no pipeline/ file imports boto3, presidio_analyzer, or paddleocr
    - **Property 13: Tenant Scoping on All Queries** — every query on tenant-owned data includes tenant_id filter
    - **Property 14: Structured Logging Compliance** — every log event is valid JSON with level and timestamp
    - **Property 15: Trace ID Propagation** — every log event for a job carries the same trace_id
    - **Property 17: Error Codes from Registry** — all abstention reasons and API error codes reference ErrorCode constants
    - **Validates: Requirements 12.5, 14.1, 14.2, 14.3, 14.5, 17.2, 19.2, 19.3, 19.4**

  - [x] 7.5 Implement graceful shutdown and Docker configuration
    - Create `Dockerfile` for the FastAPI service (Python 3.11+, multi-stage build)
    - Create `docker-compose.yml` with services: api, postgres, paddleocr
    - Configure FastAPI lifespan to drain in-flight requests before closing DB connections
    - Configure SIGTERM handler with 30s hard kill timeout
    - Bake PaddleOCR model into Dockerfile RUN step (never fetch at startup)
    - _Requirements: 17.4, 18.2_

  - [x] 7.6 Implement RedactionSettings.jsx companion UI
    - Create `frontend/RedactionSettings.jsx` with per-entity toggle panel
    - Support global config and per-schema overrides (bank_statement, custody_statement, swift_confirm)
    - Wire to `GET/PUT /v1/tenants/{id}/redaction-config` endpoints
    - _Requirements: 8.1, 8.2, 8.6_

  - [x] 7.7 Wire complete pipeline end-to-end
    - Connect all pipeline stages in `api/main.py`: ingestion → classifier → extractor → triangulation → assembler → schema extractor → VLM fallback → validator → packager → delivery
    - Ensure dependency injection wiring for all ports
    - Ensure all structured log events are emitted at correct pipeline stages
    - Verify all routes return `APIResponse[T]` envelope
    - _Requirements: 13.5, 14.4, 17.4_

  - [x] 7.8 Create README and project documentation
    - Create `README.md` with setup instructions, API documentation, architecture overview
    - Document environment variables and configuration
    - Document Docker Compose usage
    - _Requirements: N/A (developer documentation)_

- [x] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Chunked VLM extraction and model-aware token budgeting (Week 5)
  - [ ] 9.1 Extend VLMClientPort with token estimation methods
    - Add `estimate_tokens(text: str) -> int` abstract method to `pipeline/ports.py`
    - Add `max_context_tokens() -> int` abstract method to `pipeline/ports.py`
    - Update `BedrockVLMClient` in `pipeline/vlm/bedrock_client.py` with concrete implementations
    - Add `MODEL_CONTEXT_WINDOWS` and `MODEL_CHARS_PER_TOKEN` registries to bedrock_client.py
    - Update `MockVLMClient` in `tests/mocks.py` with mock implementations
    - _Requirements: 23.1, 23.2, 23.4, 23.5_

  - [ ] 9.2 Implement TokenBudget tracker
    - Create `pipeline/vlm/token_budget.py` with `TokenBudget` dataclass
    - Implement `record_usage()`, `can_proceed()`, `is_exceeded`, `remaining` properties
    - Support three budget actions: "flag", "skip", "proceed"
    - _Requirements: 24.1, 24.2, 24.3, 24.4, 24.5_

  - [ ] 9.3 Add new error codes to error registry
    - Add `VLM_BUDGET_EXCEEDED = "ERR_VLM_007"` to `api/errors.py`
    - Add `VLM_WINDOW_FAILED = "ERR_VLM_008"` to `api/errors.py`
    - Add `VLM_MERGE_CONFLICT = "ERR_VLM_009"` to `api/errors.py`
    - _Requirements: 19.1, 24.4_

  - [ ] 9.4 Add chunked extraction configuration to Settings
    - Add `vlm_max_tokens_per_job: int = 100_000` to `api/config.py`
    - Add `vlm_budget_exceeded_action: str = "flag"` to `api/config.py`
    - Add `vlm_window_size: int = 12` to `api/config.py`
    - Add `vlm_window_overlap: int = 3` to `api/config.py`
    - Add `vlm_max_concurrent_windows: int = 3` to `api/config.py`
    - _Requirements: 22.3, 22.8, 24.2_

  - [ ] 9.5 Implement tier selection logic
    - Create `pipeline/vlm/chunked_extractor.py` with `select_extraction_tier()` function
    - Implement decision matrix: single (fits in window) → tier1 (header fields only) → tier2 (<80 pages) → tier3 (>=80 pages)
    - Use `vlm_client.estimate_tokens()` and `vlm_client.max_context_tokens()` for sizing decisions
    - _Requirements: 22.1, 22.5, 22.6, 22.7, 23.3_

  - [ ] 9.6 Implement Tier 1 — Targeted page selection
    - Implement `FIELD_PAGE_MAPPING` dictionary mapping field names to expected page ranges
    - Implement `select_target_pages()` function that groups abstained fields by target page ranges
    - Send only relevant 2-5 pages per field group in a single LLM call
    - _Requirements: 22.5_

  - [ ] 9.7 Implement Tier 2 — Sliding window with overlap
    - Implement `WindowConfig` dataclass with window_size, overlap, max_concurrent
    - Implement `create_sliding_windows()` function that creates overlapping page windows
    - Implement parallel window processing with asyncio.Semaphore for rate limiting
    - Ensure page-level granularity (never split mid-page)
    - Ensure overlap of configurable pages (default 3) between adjacent windows
    - _Requirements: 22.1, 22.2, 22.3, 22.6, 22.8_

  - [ ] 9.8 Implement result merging and transaction deduplication
    - Implement `merge_window_results()` function that combines results from multiple windows
    - Implement `TransactionKey` composite key (date, description, amount) for dedup
    - Header fields taken from first window; closing balance from last window
    - Transactions deduplicated by composite key in overlap regions
    - _Requirements: 22.4, 22.9_

  - [ ] 9.9 Implement Tier 3 — Two-pass summarize-then-extract
    - Implement `PAGE_SUMMARY_PROMPT` for lightweight per-page field detection
    - Implement Pass 1: send each page individually for structured summary
    - Implement Pass 2: send summaries + only pages containing target fields
    - Implement `_identify_relevant_pages()` to select pages for Pass 2
    - _Requirements: 22.7_

  - [ ] 9.10 Implement usage event emission
    - Create `pipeline/vlm/usage_events.py` with `VLMUsageEvent` and `VLMJobUsageSummary` dataclasses
    - Implement `emit_window_usage()` — structured log event per LLM call
    - Implement `emit_job_usage_summary()` — aggregate log event at job completion
    - Include cost attribution metadata (tenant_id, job_id, schema_type, model_id)
    - _Requirements: 24.6, 24.7, 24.8_

  - [ ] 9.11 Integrate chunked extraction into pipeline runner
    - Update `_vlm_fallback()` in `pipeline/runner.py` to use chunked extraction when document exceeds context window
    - Wire `TokenBudget` initialization from Settings
    - Wire tier selection and dispatch to appropriate extraction tier
    - Emit `vlm.tier_selected` log event
    - Handle budget exceeded action (flag/skip/proceed)
    - _Requirements: 22.1, 24.2, 24.3, 24.4, 24.5_

  - [ ] 9.12 Write unit tests for chunked extraction
    - Test tier selection logic with various document sizes and abstention patterns
    - Test sliding window creation with different page counts and overlap settings
    - Test transaction deduplication with overlap scenarios
    - Test token budget enforcement for all three actions (flag, skip, proceed)
    - Test targeted page selection for header-only abstentions
    - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5, 22.6, 22.7_

  - [ ]* 9.13 Write property tests for chunked extraction
    - **Property 24: Token Budget Enforcement** — skip action stops calls after budget exceeded; flag action continues but marks job
    - **Property 25: Page Window Integrity** — windows contain only complete pages; adjacent windows overlap by configured amount
    - **Property 26: Transaction Deduplication** — overlap transactions appear exactly once in merged result
    - **Property 27: Model-Aware Token Estimation** — estimate_tokens returns positive int; max_context_tokens returns model's actual window
    - **Property 28: Usage Event Completeness** — every LLM call emits window_usage; every job emits job_usage_summary
    - **Validates: Requirements 22.1, 22.2, 22.4, 23.1, 23.2, 24.1, 24.6, 24.7**

- [ ] 10. Checkpoint - Ensure all chunked extraction tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Auto-schema discovery data models and error codes (Week 6)
  - [ ] 11.1 Add discovery data models to pipeline/models.py
    - Add `SchemaFingerprint` dataclass with `institution`, `document_type_label`, `key` property, and `from_key()` classmethod
    - Add `DiscoveredFieldDefinition` dataclass with `field_name`, `description`, `location_hint`
    - Add `DiscoveredTableDefinition` dataclass with `table_type`, `expected_headers`, `data_pattern`, `location_hint`
    - Add `DiscoveredSchema` dataclass with `document_type_label`, `institution`, `metadata_fields`, `table_definitions`, and auto-computed `fingerprint`
    - Add `DiscoverySample` dataclass with `page_texts`, `page_numbers`, `estimated_tokens`, `page_count` property, and `combined_text` property
    - _Requirements: 25.1, 26.1, 26.2, 26.3, 28.1_

  - [ ] 11.2 Add discovery error codes to api/errors.py
    - Add `DISCOVERY_SCHEMA_ANALYSIS_FAILED = "ERR_DISCOVERY_001"` to `ErrorCode`
    - Add `DISCOVERY_DYNAMIC_EXTRACTION_FAILED = "ERR_DISCOVERY_002"` to `ErrorCode`
    - Add `DISCOVERY_CACHE_LOOKUP_FAILED = "ERR_DISCOVERY_003"` to `ErrorCode`
    - _Requirements: 30.1_

  - [ ] 11.3 Add discovery configuration to api/config.py
    - Add `discovery_sample_pages: int = 5` to `Settings`
    - Add `discovery_max_context_ratio: float = 0.80` to `Settings`
    - Add `discovery_cache_enabled: bool = True` to `Settings`
    - _Requirements: 26.1, 26.6, 28.2_

- [ ] 12. Schema cache database and component (Week 6)
  - [ ] 12.1 Create schema cache database migration
    - Create `db/migrations/versions/20250XXX_auto_schema_cache.py` with `discovered_schemas` table
    - Table columns: `id` (UUID PK), `tenant_id` (UUID FK), `fingerprint_key` (VARCHAR 512), `institution` (VARCHAR 256), `document_type_label` (VARCHAR 256), `schema_json` (JSONB), `created_at` (TIMESTAMPTZ), `updated_at` (TIMESTAMPTZ), `usage_count` (INTEGER DEFAULT 1)
    - Add UNIQUE constraint on `(tenant_id, fingerprint_key)`
    - Add indexes: `idx_discovered_schemas_tenant`, `idx_discovered_schemas_fingerprint`
    - _Requirements: 28.1, 28.3, 28.6_

  - [ ] 12.2 Implement SchemaCache component
    - Create `pipeline/discovery/schema_cache.py` with `SchemaCache` class
    - Implement `lookup(fingerprint, tenant_id)` — returns `DiscoveredSchema | None`, increments `usage_count` on hit
    - Implement `store(schema, fingerprint, tenant_id)` — upserts schema, sets `created_at` and `usage_count`
    - Implement `invalidate(fingerprint, tenant_id)` — deletes entry, returns `True` if existed
    - Implement `list_for_tenant(tenant_id)` — returns all cached schemas for admin/debug
    - Ensure all queries include `tenant_id` filter for tenant isolation
    - _Requirements: 28.1, 28.2, 28.3, 28.4, 28.6_

- [ ] 13. AutoSchemaDiscovery component implementation (Week 6)
  - [ ] 13.1 Implement sample selection and VLM prompt construction
    - Create `pipeline/discovery/auto_discovery.py` with `AutoSchemaDiscovery` class
    - Implement `_select_sample(doc, max_pages)` — selects first N pages (default 5), adaptively reduces if token estimate exceeds 80% of context window
    - Implement `_build_analysis_prompt(sample_text)` — constructs the `SCHEMA_ANALYSIS_PROMPT` with page content
    - Use `vlm_client.estimate_tokens()` for token estimation and `vlm_client.max_context_tokens()` for budget check
    - _Requirements: 26.1, 26.2, 26.6_

  - [ ] 13.2 Implement VLM response parsing
    - Implement `_parse_schema_response(raw_response)` — parses JSON into `DiscoveredSchema`
    - Return `None` for null, empty, or malformed JSON responses
    - Validate that parsed schema has non-empty `document_type_label`, `institution`, and at least one field or table definition
    - _Requirements: 26.3, 26.4_

  - [ ] 13.3 Implement main discovery flow
    - Implement `discover(doc, tenant, token_budget, trace_id)` method
    - Step 1: Check circuit breaker — abstain with ERR_VLM_005 if open
    - Step 2: Check schema cache for existing match (by partial fingerprint from doc signals)
    - Step 3: If cache miss — select sample, redact via `RedactorPort`, send to VLM
    - Step 4: Parse response — abstain with ERR_DISCOVERY_001 if unparseable
    - Step 5: Store in cache, return `DiscoveredSchema`
    - Record all VLM token usage in `TokenBudget`
    - Emit `discovery.triggered`, `discovery.cache_hit`/`discovery.cache_miss`, `discovery.schema_analysed` log events
    - _Requirements: 25.1, 25.3, 25.4, 25.5, 26.1, 26.4, 26.5, 28.2, 28.5, 30.2, 30.3_

- [ ] 14. DynamicExtractor component implementation (Week 6)
  - [ ] 14.1 Implement DynamicExtractor class
    - Create `pipeline/discovery/dynamic_extractor.py` with `DynamicExtractor` class
    - Implement `extract(doc, schema, tenant, token_budget, trace_id)` method
    - Use DiscoveredSchema field definitions to build extraction prompts
    - Use DiscoveredSchema table definitions (expected headers) to guide table extraction
    - Apply same chunked extraction strategy (Tier 1/2/3) as standard VLM_Fallback based on document size
    - Apply Presidio redaction before each VLM call using tenant config
    - Verify each extracted value against token stream via Verifier (threshold 0.85)
    - _Requirements: 27.1, 27.2, 27.3, 27.4, 27.5, 27.6_

  - [ ] 14.2 Implement output format compliance
    - Set `provenance.source = "vlm"` on all extracted fields
    - Set `provenance.extraction_rule = "discovered:{field_name}"` on all fields
    - Set `schema_type = "discovered:{document_type_label}"` on the extraction result
    - Include confidence score derived from VLM confidence and Verifier match score
    - Produce Abstention with ERR_EXTRACT_001 for fields that cannot be extracted
    - Emit `discovery.extraction_complete` log event with counts
    - _Requirements: 27.7, 29.1, 29.2, 29.3, 29.4, 30.4_

- [ ] 15. Schema router modification (Week 6)
  - [ ] 15.1 Integrate auto-discovery into route_and_extract
    - Modify `pipeline/schemas/router.py` `route_and_extract()` function
    - When `detect_schema()` returns "unknown" and `tenant.vlm_enabled` is True: delegate to `AutoSchemaDiscovery`
    - If discovery returns `DiscoveredSchema`: create `DynamicExtractor` and extract
    - If discovery returns `Abstention`: return the abstention result
    - When `vlm_enabled` is False: retain existing ERR_EXTRACT_002 abstention behaviour
    - Pass `schema_cache`, `token_budget`, and `trace_id` through to discovery
    - _Requirements: 25.1, 25.2_

- [ ] 16. Checkpoint - Ensure discovery core components work
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 17. API endpoints and validator modification (Week 7)
  - [ ] 17.1 Implement schema cache API endpoints
    - Create `api/routes/schema_cache.py` with router
    - Implement `DELETE /v1/tenants/{tenant_id}/schema-cache/{fingerprint}` — invalidates a cached schema
    - Implement `GET /v1/tenants/{tenant_id}/schema-cache` — lists all cached schemas for the tenant
    - Enforce `resolve_tenant` dependency and tenant_id match check
    - Return `APIResponse` envelope on all responses
    - Return 404 if fingerprint not found on DELETE
    - Register router in `api/main.py`
    - _Requirements: 28.4, 28.6_

  - [ ] 17.2 Modify Validator for discovered schemas
    - Add `select_validators(schema_type)` function to `pipeline/validators.py`
    - When `schema_type.startswith("discovered:")`: return only generic validators (date_range, currency_code, provenance_integrity)
    - When schema_type is a known static type: return full validator suite including IBAN, ISIN, BIC, arithmetic_balance
    - Update `run_validators()` to use `select_validators()` for validator selection
    - _Requirements: 29.6_

  - [ ] 17.3 Modify Packager for discovered schemas
    - Update `pipeline/packager.py` to handle `schema_type` values prefixed with `"discovered:"`
    - Include the `DiscoveredSchema` definition in the output metadata when schema_type is discovered
    - _Requirements: 29.5_

- [ ] 18. Structured log events for discovery (Week 7)
  - [ ] 18.1 Implement discovery log events
    - Emit `discovery.triggered` with job_id, tenant_id, filename when auto-discovery starts
    - Emit `discovery.cache_hit` with job_id, tenant_id, fingerprint, usage_count when cached schema reused
    - Emit `discovery.cache_miss` with job_id, tenant_id when no cached schema found
    - Emit `discovery.schema_analysed` with job_id, document_type_label, institution, fields_count, tables_count
    - Emit `discovery.extraction_complete` with job_id, tenant_id, schema_type, fields_extracted, fields_abstained, tables_extracted
    - Emit `discovery.failed` with job_id, tenant_id, error_code, detail on any failure
    - Emit `discovery.sample_reduced` with job_id, original_pages, reduced_pages, estimated_tokens when sample is adaptively reduced
    - Set `schema_type = "discovery"` in usage events for cost attribution
    - _Requirements: 25.3, 28.5, 30.2, 30.3, 30.4, 30.6_

- [ ] 19. Unit tests for auto-schema discovery (Week 7)
  - [ ] 19.1 Write unit tests for data models and schema cache
    - Test `SchemaFingerprint.key` property normalisation (lowercase, stripped, spaces→underscores)
    - Test `SchemaFingerprint.from_key()` round-trip parsing
    - Test `DiscoveredSchema.__post_init__` auto-computes fingerprint
    - Test `DiscoverySample.combined_text` concatenation with page markers
    - Test `SchemaCache.lookup()` returns None on miss, schema on hit, increments usage_count
    - Test `SchemaCache.store()` upserts correctly
    - Test `SchemaCache.invalidate()` returns True/False appropriately
    - _Requirements: 28.1, 28.2, 28.3_

  - [ ] 19.2 Write unit tests for AutoSchemaDiscovery
    - Test sample selection with documents of varying page counts (1, 5, 50, 500 pages)
    - Test adaptive sample reduction when token estimate exceeds 80% of context window
    - Test VLM prompt construction includes correct page markers and schema structure
    - Test response parsing with valid JSON → produces DiscoveredSchema
    - Test response parsing with null/empty/malformed JSON → returns None
    - Test circuit breaker open → immediate abstention with ERR_VLM_005
    - Test cache hit path → no VLM call made, cached schema returned
    - Test token budget exhausted → abstention with ERR_VLM_007
    - _Requirements: 25.1, 25.4, 25.5, 26.1, 26.3, 26.4, 26.6_

  - [ ] 19.3 Write unit tests for DynamicExtractor
    - Test field extraction prompt uses discovered field definitions
    - Test table extraction prompt uses discovered expected headers
    - Test output format: provenance.source="vlm", extraction_rule="discovered:{name}", schema_type prefix
    - Test verification failure → field appears in abstentions with ERR_VLM_004
    - Test all fields abstained → correct ERR_EXTRACT_001 abstentions produced
    - _Requirements: 27.1, 27.2, 27.3, 27.6, 27.7, 29.1, 29.2, 29.3_

  - [ ] 19.4 Write unit tests for schema router and validator
    - Test routing: schema_type="unknown" + vlm_enabled=True → discovery triggered
    - Test routing: schema_type="unknown" + vlm_enabled=False → ERR_EXTRACT_002 abstention
    - Test routing: known schema_type → static extractor used (unchanged behaviour)
    - Test `select_validators("discovered:futures_trade_confirmation")` → only generic validators
    - Test `select_validators("bank_statement")` → full validator suite
    - _Requirements: 25.1, 25.2, 29.6_

- [ ] 20. Property tests for auto-schema discovery (Week 7)
  - [ ]* 20.1 Write property test for discovery routing decision
    - **Property 1: Discovery routing decision is determined by vlm_enabled**
    - Generate random `(schema_type, vlm_enabled)` pairs; assert routing matches spec
    - **Validates: Requirements 25.1, 25.2**

  - [ ]* 20.2 Write property test for token budget accounting
    - **Property 2: Token budget accounting includes discovery calls**
    - Generate random sequences of (input_tokens, output_tokens); assert total_consumed == sum(all pairs)
    - **Validates: Requirements 25.4**

  - [ ]* 20.3 Write property test for discovery sample context window
    - **Property 3: Discovery sample respects context window**
    - Generate random page texts of varying lengths; assert sample token estimate ≤ 80% of max_context_tokens
    - **Validates: Requirements 26.1, 26.6**

  - [ ]* 20.4 Write property test for valid VLM response parsing
    - **Property 4: Valid VLM response produces complete DiscoveredSchema**
    - Generate random valid JSON via `st.fixed_dictionaries`; assert parsed schema has non-empty label, institution, and ≥1 field or table
    - **Validates: Requirements 26.3**

  - [ ]* 20.5 Write property test for invalid VLM response handling
    - **Property 5: Invalid VLM response produces correct abstention**
    - Generate null, empty, malformed JSON; assert Abstention with ERR_DISCOVERY_001
    - **Validates: Requirements 26.4**

  - [ ]* 20.6 Write property test for schema cache round-trip
    - **Property 6: Schema cache round-trip**
    - Generate random DiscoveredSchema, store, lookup by same fingerprint+tenant; assert equivalence
    - **Validates: Requirements 28.1, 28.2**

  - [ ]* 20.7 Write property test for schema cache tenant isolation
    - **Property 7: Schema cache tenant isolation**
    - Generate random tenant pairs and schemas; store under tenant A, lookup under tenant B; assert miss
    - **Validates: Requirements 28.6**

  - [ ]* 20.8 Write property test for dynamic extraction output format
    - **Property 8: Dynamic extraction output format compliance**
    - Generate random DiscoveredSchema + mock VLM responses; assert provenance.source="vlm", extraction_rule starts with "discovered:", confidence in [0,1], schema_type prefix correct
    - **Validates: Requirements 29.1, 29.2, 29.3, 29.4**

  - [ ]* 20.9 Write property test for validator selection
    - **Property 9: Validator selection for discovered schemas**
    - Generate random schema_type strings with/without "discovered:" prefix; assert correct validator set
    - **Validates: Requirements 29.6**

  - [ ]* 20.10 Write property test for discovery failure error codes
    - **Property 10: Discovery failure produces correct error codes**
    - Generate random failure scenarios; assert Abstention references ERR_DISCOVERY_001/002/003 only
    - **Validates: Requirements 30.5**

  - [ ]* 20.11 Write property test for dynamic extractor verification
    - **Property 11: Dynamic extractor verifies all values**
    - Generate random field values and token streams; assert verified values in fields, unverified in abstentions with ERR_VLM_004
    - **Validates: Requirements 27.6**

- [ ] 21. Integration test for end-to-end discovery flow (Week 7)
  - [ ]* 21.1 Write integration test for auto-schema discovery end-to-end
    - Submit a document with unknown schema_type and vlm_enabled=True
    - Mock VLM to return valid schema analysis JSON
    - Assert: discovery triggered → schema cached → dynamic extraction runs → output has "discovered:" prefix
    - Assert: second submission of same type → cache hit → no VLM discovery call
    - Assert: DELETE schema-cache endpoint → cache invalidated → next submission triggers fresh discovery
    - Assert: all structured log events emitted (discovery.triggered, discovery.schema_analysed, discovery.extraction_complete)
    - _Requirements: 25.1, 26.3, 27.1, 28.1, 28.2, 28.4, 28.5, 29.3, 30.2_

- [ ] 22. Final checkpoint - Ensure all auto-schema discovery tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at the end of each week
- Property tests validate universal correctness properties from the design document using the `hypothesis` library
- Unit tests validate specific examples and edge cases
- The design uses Python throughout — all implementations use Python 3.11+ with type hints and `mypy --strict`
- No file in `pipeline/` may import `boto3`, `presidio_analyzer`, or `paddleocr` directly — all external SDK usage goes through port abstractions
- Week 5 tasks (chunked extraction) build on the existing VLM fallback infrastructure from Week 3
- The `estimate_tokens()` and `max_context_tokens()` methods are added to the existing `VLMClientPort` ABC — all existing implementations and mocks must be updated
- New error codes (ERR_VLM_007, ERR_VLM_008, ERR_VLM_009) follow the existing namespaced pattern in `api/errors.py`
- Week 6–7 tasks (auto-schema discovery) build on the chunked extraction infrastructure from Week 5 and the VLM fallback from Week 3
- Auto-schema discovery introduces a new `pipeline/discovery/` directory containing `auto_discovery.py`, `dynamic_extractor.py`, and `schema_cache.py`
- Discovery error codes (ERR_DISCOVERY_001/002/003) follow the existing namespaced pattern and are added to the central `ErrorCode` registry in `api/errors.py`
- The `SchemaCache` is backed by PostgreSQL (same DB as jobs/results) with a dedicated `discovered_schemas` table
- Discovery VLM calls count toward the same per-job `TokenBudget` as standard extraction calls — no separate budget
- The `DynamicExtractor` reuses the same chunked extraction tiers (1/2/3) and `Verifier` as the standard VLM fallback path
- Schema cache is tenant-isolated: all queries include `tenant_id` filter, no cross-tenant schema reuse
- The 11 property tests for auto-schema discovery are defined in the design's Correctness Properties section and validate requirements 25–30
