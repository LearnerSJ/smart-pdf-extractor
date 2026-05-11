# Requirements Document

## Introduction

The PDF Ingestion Layer is a production-ready extraction service for the reconciliation product. It processes bank/custody statements and SWIFT/broker trade confirmations, extracting structured data with full provenance tracking. The system targets 500–1,000 documents per month, follows a pipeline architecture with discrete stages, and prioritises abstention over fabrication in all extraction decisions.

## Glossary

- **Pipeline**: The sequential processing chain from ingestion through packaging that transforms a raw PDF into structured JSON output
- **Ingestion_Layer**: The initial stage that validates file type, enforces size limits, computes SHA-256 for deduplication, and repairs malformed PDFs via pikepdf
- **Classifier**: The per-page component that determines whether a page is DIGITAL (native text coverage ≥ 0.80) or SCANNED (coverage < 0.80)
- **Digital_Extractor**: The component that extracts text and tables from digital PDF pages using pdfplumber
- **Camelot_Extractor**: The second-rail table extraction component using camelot-py for triangulation
- **OCR_Extractor**: The component that extracts text from scanned pages via PaddleOCR
- **Triangulation_Engine**: The component that compares pdfplumber and camelot table outputs to produce a disagreement score and routing verdict
- **Schema_Extractor**: The rule-based component that extracts fields and tables per document type (bank_statement, custody_statement, swift_confirm)
- **VLM_Fallback**: The conditional Claude 3.5 Sonnet extraction path for hard cases, gated by per-tenant consent and Presidio redaction
- **Redactor**: The Presidio-based component that removes PII from page content before VLM invocation
- **Verifier**: The post-filter component that checks VLM-extracted values exist in the original unredacted token stream
- **Validator**: The constraint-checking component that runs pure-function validators on extraction results
- **Packager**: The component that assembles the final JSON output with all metadata, provenance, and confidence summary
- **Delivery_Orchestrator**: The component that manages downstream delivery of extraction results to tenant-configured callback URLs
- **WebhookDeliveryClient**: The concrete implementation of DeliveryPort that POSTs results to tenant callback URLs with exponential backoff retry
- **Batch**: An optional grouping of multiple extraction jobs for coordinated delivery
- **Abstention**: An explicit declaration that a field or table could not be confidently extracted, with a reason referencing an ErrorCode constant
- **Provenance**: Metadata attached to every extracted field containing page number, bounding box, source type, and extraction rule
- **Tenant**: An authenticated API consumer with configurable VLM consent, redaction settings, and delivery configuration
- **ErrorCode**: A namespaced constant from the error registry (e.g., ERR_VLM_004) used in all abstention reasons and API error responses
- **APIResponse**: The standard response envelope wrapping all API responses with data, meta (request_id, timestamp), and optional error fields
- **DeliveryConfig**: Per-tenant configuration controlling downstream result delivery (callback_url, auth_header, enabled flag)
- **Chunked_Extractor**: The component that splits large documents into page-level windows for VLM processing, using a tiered strategy (targeted pages, sliding window, or two-pass) based on document size and extraction needs
- **TokenBudget**: A per-job tracker that monitors cumulative token consumption across all LLM calls and enforces configurable limits (flag, skip, or proceed)
- **PageWindow**: A contiguous range of pages sent in a single LLM call during chunked extraction, with configurable overlap between adjacent windows
- **UsageEvent**: A structured log event emitted per LLM call and per job containing token consumption, model ID, and cost attribution metadata for downstream monitoring
- **Auto_Schema_Discovery**: The component that uses VLM analysis to identify document type and extract relevant fields when no static schema matches, producing a DiscoveredSchema for the document
- **DiscoveredSchema**: A VLM-generated schema definition containing document_type_label, metadata fields, and tabular data structure (column headers and data patterns) for an unrecognised document type
- **Schema_Cache**: A persistent store of previously discovered schemas keyed by a fingerprint (institution + document_type_label), enabling reuse on future documents of the same type without repeated VLM discovery calls
- **Schema_Fingerprint**: A composite key derived from institution name and document_type_label used to look up cached DiscoveredSchemas
- **Discovery_Sample**: A subset of document pages (default first 5 pages) sent to the VLM for schema analysis, kept small to respect token budgets
- **Dynamic_Extractor**: The extraction component that uses a DiscoveredSchema (rather than hardcoded regex patterns) to drive VLM-based field and table extraction on the full document

## Requirements

### Requirement 1: Document Ingestion and Validation

**User Story:** As a reconciliation operator, I want uploaded PDFs to be validated and deduplicated before processing, so that invalid files are rejected early and duplicate work is avoided.

#### Acceptance Criteria

1. WHEN a file is uploaded, THE Ingestion_Layer SHALL validate the file's magic bytes to confirm it is a valid PDF
2. IF the uploaded file is not a valid PDF, THEN THE Ingestion_Layer SHALL reject it with error code ERR_INGESTION_001 and HTTP status 422
3. WHEN a file exceeds the configurable maximum size (default 50 MB), THE Ingestion_Layer SHALL reject it with error code ERR_INGESTION_002 and HTTP status 413
4. WHEN a valid PDF is received, THE Ingestion_Layer SHALL compute a SHA-256 hash of the file bytes for deduplication
5. WHEN the computed SHA-256 hash matches an existing record, THE Ingestion_Layer SHALL return the cached result without re-processing
6. WHEN a PDF has structural corruption, THE Ingestion_Layer SHALL attempt repair via pikepdf before processing
7. IF a PDF is password-protected, THEN THE Ingestion_Layer SHALL reject it with error code ERR_INGESTION_003 and HTTP status 422
8. THE Ingestion_Layer SHALL produce deterministic document identifiers such that identical file bytes always produce the same doc_id

### Requirement 2: Per-Page Classification

**User Story:** As a reconciliation operator, I want each page classified independently as digital or scanned, so that the appropriate extraction method is applied per page even in mixed documents.

#### Acceptance Criteria

1. WHEN a page has native text coverage greater than or equal to 0.80, THE Classifier SHALL classify it as DIGITAL
2. WHEN a page has native text coverage less than 0.80, THE Classifier SHALL classify it as SCANNED
3. WHEN a page has no characters, THE Classifier SHALL classify it as SCANNED
4. THE Classifier SHALL compute native text coverage as the sum of character bounding box areas divided by total page area
5. THE Classifier SHALL classify each page independently, supporting mixed documents with both digital and scanned pages

### Requirement 3: Digital Text and Table Extraction

**User Story:** As a reconciliation operator, I want text and tables extracted from digital PDF pages with full provenance, so that every extracted value can be traced back to its source location.

#### Acceptance Criteria

1. WHEN a page is classified as DIGITAL, THE Digital_Extractor SHALL extract character-level text with bounding boxes and font metadata
2. WHEN a page is classified as DIGITAL, THE Digital_Extractor SHALL extract tables via pdfplumber with cell-level provenance
3. WHEN a page is classified as DIGITAL, THE Camelot_Extractor SHALL extract tables using lattice mode for ruled tables
4. IF lattice mode returns zero tables, THEN THE Camelot_Extractor SHALL fall back to stream mode for whitespace-delimited tables
5. THE Digital_Extractor SHALL tag every extracted element with page number and bounding box provenance

### Requirement 4: OCR Extraction for Scanned Pages

**User Story:** As a reconciliation operator, I want scanned pages processed through OCR with bounding box provenance, so that text from non-digital pages is still available for extraction.

#### Acceptance Criteria

1. WHEN a page is classified as SCANNED, THE OCR_Extractor SHALL send the page image to PaddleOCR and return a token grid with bounding boxes and confidence scores
2. THE OCR_Extractor SHALL cache results by page hash and model version to avoid redundant processing
3. IF the PaddleOCR service is unavailable, THEN THE OCR_Extractor SHALL abstain on all scanned pages while continuing to process digital pages

### Requirement 5: Table Triangulation

**User Story:** As a reconciliation operator, I want table extraction validated by comparing two independent methods, so that disagreement between methods surfaces as a quality signal.

#### Acceptance Criteria

1. THE Triangulation_Engine SHALL compute a cell-by-cell disagreement score between pdfplumber and camelot table outputs
2. THE Triangulation_Engine SHALL produce a disagreement score in the range [0.0, 1.0]
3. WHEN the disagreement score is less than 0.10, THE Triangulation_Engine SHALL assign verdict "agreement" and select pdfplumber as winner
4. WHEN the disagreement score is between 0.10 and 0.40 (exclusive), THE Triangulation_Engine SHALL assign verdict "soft_flag" and select pdfplumber as winner
5. WHEN the disagreement score is 0.40 or greater, THE Triangulation_Engine SHALL assign verdict "hard_flag" and set winner to "vlm_required"
6. WHEN the two tables have different shapes (row/column counts), THE Triangulation_Engine SHALL return a score of 1.0 with verdict "hard_flag"
7. WHEN a table receives a "soft_flag" or "hard_flag" verdict, THE Triangulation_Engine SHALL auto-write a feedback record to the feedback store

### Requirement 6: Schema-Based Field Extraction

**User Story:** As a reconciliation operator, I want fields extracted using rule-based patterns per document type, so that extraction is deterministic, traceable, and does not depend on ML models.

#### Acceptance Criteria

1. THE Schema_Extractor SHALL support three document schemas: bank_statement, custody_statement, and swift_confirm
2. WHEN a document's structural signals do not match any known schema, THE Schema_Extractor SHALL set schema_type to "unknown" and abstain entirely with error code ERR_EXTRACT_002
3. THE Schema_Extractor SHALL extract fields using regex patterns and structural anchors, trying patterns in order with first match winning
4. WHEN a required field cannot be extracted, THE Schema_Extractor SHALL produce an Abstention with error code ERR_EXTRACT_001
5. THE Schema_Extractor SHALL apply normalisation functions (parse_amount, parse_date, normalise_iban) to raw matches while preserving the original_string
6. THE Schema_Extractor SHALL include provenance (page, bbox, source, extraction_rule) on every extracted field identifying which pattern matched

### Requirement 7: VLM Fallback Extraction

**User Story:** As a reconciliation operator, I want a VLM fallback for fields that rule-based extraction cannot resolve, so that hard cases can still be extracted while maintaining data privacy controls.

#### Acceptance Criteria

1. WHEN a required field is abstained by rule-based extraction and the tenant has vlm_enabled set to True, THE VLM_Fallback SHALL attempt extraction via Claude 3.5 Sonnet on AWS Bedrock
2. IF the tenant has vlm_enabled set to False, THEN THE VLM_Fallback SHALL abstain immediately with error code ERR_VLM_001 without making any external call
3. WHEN the VLM_Fallback is triggered, THE Redactor SHALL apply Presidio redaction to the page content before sending it to the VLM
4. THE Redactor SHALL produce a RedactionLog recording all entities redacted, their positions, and the active configuration snapshot
5. WHEN the VLM returns a value, THE Verifier SHALL check that the value exists in the original unredacted token stream using fuzzy matching with threshold 0.85
6. IF the VLM-extracted value cannot be found in the token stream, THEN THE Verifier SHALL reject it and produce an Abstention with error code ERR_VLM_004
7. IF the VLM returns null, THEN THE VLM_Fallback SHALL produce an Abstention with error code ERR_VLM_003
8. WHEN a Bedrock call is throttled or times out, THE VLM_Fallback SHALL retry once with exponential backoff before abstaining with error code ERR_VLM_005
9. THE VLM_Fallback SHALL make a maximum of 2 Bedrock API calls per field (1 initial + 1 retry)

### Requirement 8: Tenant-Configurable Redaction

**User Story:** As a tenant administrator, I want to configure which PII entity types are redacted before VLM processing, so that I can balance data privacy with extraction accuracy per document type.

#### Acceptance Criteria

1. THE Redactor SHALL support per-tenant global redaction configuration specifying which entity types to redact
2. THE Redactor SHALL support per-schema overrides allowing different redaction settings for bank_statement, custody_statement, and swift_confirm
3. WHEN no entities are enabled for redaction in the configuration, THE Redactor SHALL return the original text unchanged with an empty RedactionLog
4. WHEN redaction is applied, THE Redactor SHALL replace all detected PII entities matching enabled types with "[REDACTED]"
5. THE Redactor SHALL never mutate the original text — redaction produces a new string
6. THE system SHALL expose GET and PUT endpoints at /v1/tenants/{id}/redaction-config for managing tenant redaction settings

### Requirement 9: Extraction Validation

**User Story:** As a reconciliation operator, I want all extracted data validated against domain constraints, so that incorrect extractions are caught before delivery.

#### Acceptance Criteria

1. THE Validator SHALL verify arithmetic consistency for bank statements: |closing_balance - (opening_balance + sum(credits) - sum(debits))| ≤ 0.02
2. THE Validator SHALL verify IBAN values using mod-97 checksum validation
3. THE Validator SHALL verify ISIN values using ISO 6166 check digit validation
4. THE Validator SHALL verify BIC values conform to 8 or 11 character format
5. THE Validator SHALL verify dates are not in the future and not more than 10 years in the past
6. THE Validator SHALL verify currency codes against ISO 4217
7. THE Validator SHALL verify provenance integrity: every field has a page number and bounding box within page bounds
8. THE Validator SHALL execute all validators regardless of individual failures, producing a complete ValidationReport
9. THE Validator SHALL be implemented as pure functions that do not mutate the ExtractionResult or AssembledDocument

### Requirement 10: Provenance Tracking

**User Story:** As a reconciliation operator, I want every extracted field to carry provenance metadata, so that I can trace any value back to its exact source location in the original document.

#### Acceptance Criteria

1. THE Pipeline SHALL attach provenance (page number, bounding box, source type, extraction rule) to every extracted field
2. THE Pipeline SHALL ensure provenance page numbers are positive integers
3. THE Pipeline SHALL ensure provenance bounding boxes contain exactly 4 non-negative elements within page bounds
4. THE Pipeline SHALL ensure provenance source is one of: "native", "ocr", or "vlm"
5. WHEN a field is extracted via VLM, THE Pipeline SHALL set provenance source to "vlm" and include the matched token's bounding box

### Requirement 11: Abstention Integrity

**User Story:** As a reconciliation operator, I want every abstained field to carry a structured reason from the error registry, so that I can understand why extraction failed and take corrective action.

#### Acceptance Criteria

1. THE Pipeline SHALL ensure every abstention includes a non-null reason referencing an ErrorCode constant from the error registry
2. THE Pipeline SHALL ensure every abstention includes a non-null detail string explaining the failure
3. THE Pipeline SHALL ensure every required field is either present in the extracted fields or explicitly listed in abstentions — no field is silently missing
4. THE Pipeline SHALL ensure abstention reason fields reference ErrorCode constants and never contain raw strings

### Requirement 12: Authentication and Tenant Isolation

**User Story:** As a system administrator, I want all API routes protected by tenant authentication with strict data isolation, so that no tenant can access another tenant's data.

#### Acceptance Criteria

1. THE API SHALL require a valid API key in the Authorization header (Bearer token) on all protected routes
2. IF the API key is missing, THEN THE API SHALL return HTTP 401 with error code ERR_AUTH_001
3. IF the API key is invalid, THEN THE API SHALL return HTTP 401 with error code ERR_AUTH_002
4. IF the tenant is suspended, THEN THE API SHALL return HTTP 403 with error code ERR_AUTH_003
5. THE API SHALL include a tenant_id filter on every database query that touches jobs, results, or feedback data
6. THE API SHALL enforce the resolve_tenant dependency on all protected routes

### Requirement 13: API Response Envelope

**User Story:** As an API consumer, I want all responses in a consistent envelope format with request tracing, so that I can reliably parse responses and correlate them with my requests.

#### Acceptance Criteria

1. THE API SHALL wrap all responses (success and error) in the APIResponse envelope containing data, meta, and optional error fields
2. THE API SHALL include a request_id (trace_id) and ISO 8601 timestamp in the meta field of every response
3. THE API SHALL ensure error response codes reference constants from the ErrorCode registry
4. IF an error is present in the response, THEN THE API SHALL set data to None
5. THE API SHALL never return a bare Pydantic model from any route handler

### Requirement 14: Structured Logging and Tracing

**User Story:** As a system operator, I want all log output as structured JSON with trace IDs, so that I can search, filter, and correlate log events across the pipeline.

#### Acceptance Criteria

1. THE Pipeline SHALL emit all log events as valid JSON with level and ISO timestamp fields
2. THE Pipeline SHALL generate a trace_id on each POST /v1/extract request and propagate it through all pipeline stages
3. THE Pipeline SHALL bind the trace_id to the structlog context for every operation within a job
4. THE Pipeline SHALL log the following minimum events: extraction.submitted, page.classified, triangulation.result, vlm.triggered, vlm.verified, validation.failed, extraction.complete, extraction.error, delivery.triggered, delivery.success, delivery.failed, delivery.skipped, batch.complete
5. THE Pipeline SHALL never use print() or unstructured logging calls

### Requirement 15: Batch Processing and Coordinated Delivery

**User Story:** As a reconciliation operator, I want to group multiple extraction jobs into a batch for coordinated delivery, so that all results from a batch are delivered together when processing completes.

#### Acceptance Criteria

1. WHEN a batch_id is provided on POST /v1/extract, THE Pipeline SHALL associate the job with that batch group
2. WHEN batch_id is omitted on POST /v1/extract, THE Pipeline SHALL treat the job as standalone
3. WHEN all jobs in a batch reach terminal state (complete, failed, or partial), THE Delivery_Orchestrator SHALL trigger batch delivery
4. WHILE any job in a batch remains in a non-terminal state (submitted or processing), THE Delivery_Orchestrator SHALL not trigger delivery for that batch
5. THE API SHALL expose GET /v1/batches/{batch_id} returning batch status and job list, scoped to the authenticated tenant
6. IF a batch_id is not found for the authenticated tenant, THEN THE API SHALL return HTTP 404 with error code ERR_DELIVERY_003

### Requirement 16: Downstream Result Delivery

**User Story:** As a reconciliation operator, I want extraction results automatically pushed to my configured callback URL, so that I receive results without polling.

#### Acceptance Criteria

1. WHEN a standalone job completes and the tenant has delivery enabled with a configured callback_url, THE Delivery_Orchestrator SHALL deliver results immediately
2. WHEN a batch completes and the tenant has delivery enabled with a configured callback_url, THE Delivery_Orchestrator SHALL assemble a batch payload and deliver it
3. IF the tenant has delivery_config.enabled set to False or no callback_url configured, THEN THE Delivery_Orchestrator SHALL skip delivery and log a warning
4. WHEN delivery fails, THE WebhookDeliveryClient SHALL retry with exponential backoff and jitter up to a maximum of 3 retries
5. IF delivery fails after all retries, THEN THE Delivery_Orchestrator SHALL mark delivery_status as "delivery_failed" and log with error code ERR_DELIVERY_002
6. THE Delivery_Orchestrator SHALL ensure delivery failures never affect the extraction job status — results remain accessible via GET /v1/results
7. THE Delivery_Orchestrator SHALL log every delivery attempt (success and failure) with trace_id, status_code, and attempt_number

### Requirement 17: Ports and Adapters Architecture

**User Story:** As a developer, I want all external dependencies wrapped behind port interfaces, so that every pipeline stage is unit-testable in isolation and dependencies are swappable.

#### Acceptance Criteria

1. THE Pipeline SHALL define port interfaces (VLMClientPort, RedactorPort, OCRClientPort, IngestionTriggerPort, DeliveryPort) for all external dependencies
2. THE Pipeline SHALL ensure no file in the pipeline/ directory imports boto3, presidio_analyzer, or paddleocr directly
3. THE Pipeline SHALL place concrete implementations (BedrockVLMClient, PageRedactor, PaddleOCRClient, WebhookDeliveryClient) in dedicated adapter files
4. THE Pipeline SHALL wire port bindings via dependency injection in api/main.py at startup
5. THE Pipeline SHALL provide mock implementations (MockVLMClient, MockRedactor, MockOCRClient, MockDeliveryClient) for all ports for use in testing

### Requirement 18: Circuit Breaker Resilience

**User Story:** As a system operator, I want circuit breakers on external service calls, so that cascading failures are prevented when dependencies become unavailable.

#### Acceptance Criteria

1. WHEN BedrockVLMClient experiences 3 consecutive failures, THE circuit breaker SHALL open and reject subsequent calls immediately
2. WHEN PaddleOCRClient experiences 3 consecutive failures, THE circuit breaker SHALL open and reject subsequent calls immediately
3. WHILE the circuit breaker is open, THE system SHALL reject calls immediately without making external requests
4. WHEN the recovery window elapses (60s for Bedrock, 30s for PaddleOCR), THE circuit breaker SHALL transition to half-open state allowing a test call

### Requirement 19: Error Registry Compliance

**User Story:** As a developer, I want all errors to use namespaced codes from a central registry, so that error handling is consistent and errors are traceable across logs and API responses.

#### Acceptance Criteria

1. THE system SHALL define all error codes in a central ErrorCode registry with namespaced prefixes (ERR_AUTH_, ERR_INGESTION_, ERR_EXTRACT_, ERR_VLM_, ERR_VALID_, ERR_DELIVERY_)
2. THE system SHALL ensure every Abstention reason field references an ErrorCode constant
3. THE system SHALL ensure every API error response code references an ErrorCode constant
4. THE system SHALL never use ad-hoc error strings in abstention reasons or API error responses

### Requirement 20: Health Check Endpoints

**User Story:** As a system operator, I want liveness and readiness health check endpoints, so that orchestration systems can determine service availability.

#### Acceptance Criteria

1. THE API SHALL expose GET /v1/healthz that returns status "ok" without checking dependencies (liveness probe)
2. THE API SHALL expose GET /v1/readyz that checks all runtime dependencies (PostgreSQL, PaddleOCR) and returns HTTP 200 if all are reachable
3. IF any dependency is unreachable during readiness check, THEN THE API SHALL return HTTP 503 with a status map showing which dependencies failed

### Requirement 21: Feedback Capture

**User Story:** As a reconciliation operator, I want to submit corrections for extraction errors and have triangulation flags auto-captured, so that the system accumulates ground truth for future improvement.

#### Acceptance Criteria

1. THE API SHALL expose POST /v1/feedback/{job_id} accepting correction submissions with field_name, correct_value, and optional notes
2. WHEN a table triangulation produces a "soft_flag" or "hard_flag" verdict, THE Triangulation_Engine SHALL automatically write a feedback record with source "triangulation"
3. THE feedback endpoint SHALL scope all queries to the authenticated tenant's data

### Requirement 22: Chunked VLM Extraction for Large Documents

**User Story:** As a reconciliation operator, I want large documents (100+ pages) to be processed through VLM without exceeding the model's context window, so that VLM fallback works reliably regardless of document size.

#### Acceptance Criteria

1. WHEN the estimated token count of the full document text exceeds 80% of the model's context window, THE VLM_Fallback SHALL split the document into page-level windows rather than sending everything in one call
2. THE VLM_Fallback SHALL never split a page across two windows — page-level granularity is mandatory to preserve table integrity
3. WHEN using sliding window extraction (Tier 2), THE VLM_Fallback SHALL use an overlap of configurable pages (default 3) between adjacent windows to catch multi-page tables spanning window boundaries
4. WHEN transactions appear in the overlap region of two adjacent windows, THE VLM_Fallback SHALL deduplicate them using the composite key (date, description, amount)
5. WHEN only header/balance fields are abstained, THE VLM_Fallback SHALL use Tier 1 (targeted page selection) sending only the 2-5 pages most likely to contain those fields
6. WHEN full extraction is needed and the document has fewer than 80 pages, THE VLM_Fallback SHALL use Tier 2 (sliding window with overlap)
7. WHEN full extraction is needed and the document has 80 or more pages, THE VLM_Fallback SHALL use Tier 3 (two-pass summarize-then-extract)
8. THE VLM_Fallback SHALL process windows in parallel using a configurable semaphore (default 3 concurrent windows) to respect Bedrock rate limits
9. WHEN merging results from multiple windows, THE VLM_Fallback SHALL take header fields from the first window (statement metadata always on pages 1-2)

### Requirement 23: Model-Aware Token Budgeting

**User Story:** As a developer, I want token estimation and context window size to be model-aware methods on the VLM client port, so that chunking logic adapts automatically when the underlying model is changed.

#### Acceptance Criteria

1. THE VLMClientPort SHALL expose an `estimate_tokens(text: str) -> int` method that returns a model-specific token estimate for the given text
2. THE VLMClientPort SHALL expose a `max_context_tokens() -> int` method that returns the model's maximum context window size in tokens
3. THE chunking logic SHALL use `estimate_tokens()` and `max_context_tokens()` from the VLM client port to make all sizing decisions — no hardcoded token estimates (e.g., `len(text) / 4`) in the chunking layer
4. THE BedrockVLMClient SHALL implement `estimate_tokens()` using a calibrated chars-per-token ratio specific to the configured model
5. THE BedrockVLMClient SHALL implement `max_context_tokens()` by looking up the model_id in a registry of known context window sizes

### Requirement 24: Per-Job Token Budget and Usage Tracking

**User Story:** As a system operator, I want per-job token budgets with configurable enforcement actions, so that runaway VLM costs are controlled without silently dropping extraction on legitimate large documents.

#### Acceptance Criteria

1. THE Pipeline SHALL track cumulative token consumption (input + output) across all LLM calls within a single job
2. THE Pipeline SHALL enforce a configurable per-job token budget (default 100,000 tokens) with a configurable action when exceeded
3. WHEN the token budget is exceeded and action is "flag", THE Pipeline SHALL continue extraction but emit a `vlm.budget_exceeded` log event and mark the job metadata with `budget_exceeded: true`
4. WHEN the token budget is exceeded and action is "skip", THE Pipeline SHALL stop further VLM calls and abstain remaining fields with error code ERR_VLM_007
5. WHEN the token budget is exceeded and action is "proceed", THE Pipeline SHALL continue extraction without enforcement
6. THE Pipeline SHALL emit a structured `vlm.window_usage` log event per LLM call containing job_id, tenant_id, model_id, input_tokens, output_tokens, and window metadata
7. THE Pipeline SHALL emit a `vlm.job_usage_summary` log event at job completion containing aggregate token totals, tier used, and budget status
8. THE usage events SHALL include cost attribution metadata (tenant_id, job_id, schema_type) for downstream consumption by a future admin dashboard

### Requirement 25: Auto-Schema Discovery Trigger

**User Story:** As a reconciliation operator, I want the pipeline to automatically discover the document type and relevant fields when a document doesn't match any known schema, so that unknown document types (e.g., futures trade confirmations, derivative statements) are still processed instead of being rejected outright.

#### Acceptance Criteria

1. WHEN the Schema_Extractor detects schema_type "unknown" and the tenant has vlm_enabled set to True, THE Auto_Schema_Discovery SHALL be triggered instead of producing an immediate ERR_EXTRACT_002 abstention
2. IF the tenant has vlm_enabled set to False, THEN THE Pipeline SHALL retain the existing behaviour: abstain with error code ERR_EXTRACT_002 without invoking Auto_Schema_Discovery
3. WHEN Auto_Schema_Discovery is triggered, THE Pipeline SHALL log a structured `discovery.triggered` event containing job_id, tenant_id, and document filename
4. THE Auto_Schema_Discovery SHALL respect the per-job TokenBudget — discovery VLM calls count toward the same budget as extraction calls
5. WHILE the circuit breaker for BedrockVLMClient is open, THE Auto_Schema_Discovery SHALL abstain immediately with error code ERR_VLM_005 without attempting discovery

### Requirement 26: VLM-Based Schema Analysis

**User Story:** As a reconciliation operator, I want the VLM to analyse a sample of the unknown document and identify its structure, so that extraction can proceed with the correct field definitions rather than guessing bank statement fields.

#### Acceptance Criteria

1. WHEN Auto_Schema_Discovery is triggered, THE Auto_Schema_Discovery SHALL send a Discovery_Sample (default first 5 pages) to the VLM for structural analysis
2. THE Auto_Schema_Discovery SHALL request the VLM to identify: document_type_label (a human-readable type name), institution name, metadata fields present (with field names and locations), and tabular data structure (column headers and data patterns)
3. THE Auto_Schema_Discovery SHALL produce a DiscoveredSchema object containing document_type_label, institution, a list of metadata field definitions, and a list of table definitions with expected headers
4. IF the VLM returns null or an unparseable response during schema analysis, THEN THE Auto_Schema_Discovery SHALL abstain with error code ERR_VLM_003 and detail "Schema discovery failed: VLM returned no usable schema"
5. THE Auto_Schema_Discovery SHALL apply Presidio redaction to the Discovery_Sample before sending it to the VLM, using the tenant's configured redaction settings
6. WHEN the Discovery_Sample exceeds 80% of the model's context window, THE Auto_Schema_Discovery SHALL reduce the sample size (fewer pages) until it fits within budget

### Requirement 27: Dynamic Extraction Using Discovered Schema

**User Story:** As a reconciliation operator, I want the discovered schema to drive extraction of the full document, so that fields and tables are extracted using the correct structure rather than hardcoded bank statement patterns.

#### Acceptance Criteria

1. WHEN a DiscoveredSchema is produced, THE Dynamic_Extractor SHALL use it to extract metadata fields and tables from the full document via VLM calls
2. THE Dynamic_Extractor SHALL use the DiscoveredSchema's field definitions as the extraction prompt — requesting only the fields identified during discovery
3. THE Dynamic_Extractor SHALL use the DiscoveredSchema's table definitions (expected headers) to guide tabular data extraction
4. THE Dynamic_Extractor SHALL apply the same chunked extraction strategy (Tier 1/2/3) as the standard VLM_Fallback based on document size and token budget
5. THE Dynamic_Extractor SHALL apply Presidio redaction before each VLM call using the tenant's configured redaction settings
6. THE Dynamic_Extractor SHALL verify each VLM-extracted value against the original token stream using the Verifier with fuzzy threshold 0.85
7. IF a field from the DiscoveredSchema cannot be extracted, THEN THE Dynamic_Extractor SHALL produce an Abstention with error code ERR_EXTRACT_001 and detail referencing the discovered field name

### Requirement 28: Discovered Schema Caching and Reuse

**User Story:** As a system operator, I want discovered schemas cached and reused for future documents of the same type, so that repeated VLM discovery calls are avoided for documents from the same institution with the same structure.

#### Acceptance Criteria

1. WHEN a DiscoveredSchema is successfully produced, THE Schema_Cache SHALL store it keyed by Schema_Fingerprint (institution + document_type_label), scoped to the tenant
2. WHEN Auto_Schema_Discovery is triggered, THE Schema_Cache SHALL be checked first — if a matching DiscoveredSchema exists for the tenant, the cached schema SHALL be used without making a VLM discovery call
3. THE Schema_Cache SHALL store a created_at timestamp and a usage_count on each cached entry
4. THE Schema_Cache SHALL support cache invalidation via a DELETE endpoint at /v1/tenants/{id}/schema-cache/{fingerprint}
5. THE Pipeline SHALL log a structured `discovery.cache_hit` event when a cached schema is reused, and `discovery.cache_miss` event when a new discovery is performed
6. THE Schema_Cache SHALL be tenant-isolated — no tenant can access or reuse another tenant's discovered schemas

### Requirement 29: Auto-Discovery Output Format Compliance

**User Story:** As a reconciliation operator, I want auto-discovered extraction results in the same output format as static extractors, so that downstream systems process all results uniformly regardless of how the schema was determined.

#### Acceptance Criteria

1. THE Dynamic_Extractor SHALL produce output in the same structure as static schema extractors: fields (with value, original_string, confidence, provenance), tables (with headers, rows, triangulation info), and abstentions
2. THE Dynamic_Extractor SHALL set provenance source to "vlm" and extraction_rule to "discovered:{field_name}" for all extracted fields
3. THE Dynamic_Extractor SHALL set schema_type in the extraction result to "discovered:{document_type_label}" (e.g., "discovered:futures_trade_confirmation")
4. THE Dynamic_Extractor SHALL include a confidence score on every extracted field, derived from the VLM's stated confidence and the Verifier match score
5. THE Packager SHALL handle schema_type values prefixed with "discovered:" and include the DiscoveredSchema definition in the output metadata
6. THE Validator SHALL run applicable validators (date range, currency code, provenance integrity) on discovered-schema results — validators that require schema-specific knowledge (IBAN checksum, arithmetic balance) SHALL be skipped for discovered schemas

### Requirement 30: Auto-Discovery Error Codes and Observability

**User Story:** As a system operator, I want dedicated error codes and structured log events for the auto-discovery path, so that discovery failures are distinguishable from standard extraction failures in monitoring and alerting.

#### Acceptance Criteria

1. THE system SHALL define error codes ERR_DISCOVERY_001 (schema analysis failed), ERR_DISCOVERY_002 (dynamic extraction failed), and ERR_DISCOVERY_003 (cache lookup failed) in the central ErrorCode registry
2. THE Pipeline SHALL emit structured log events: `discovery.triggered`, `discovery.schema_analysed`, `discovery.cache_hit`, `discovery.cache_miss`, `discovery.extraction_complete`, and `discovery.failed`
3. THE `discovery.schema_analysed` log event SHALL include the discovered document_type_label, institution, number of fields identified, and number of tables identified
4. THE `discovery.extraction_complete` log event SHALL include job_id, tenant_id, schema_type, fields_extracted count, fields_abstained count, and tables_extracted count
5. WHEN Auto_Schema_Discovery fails at any stage, THE Pipeline SHALL produce an Abstention with the appropriate ERR_DISCOVERY_* code and a detail string describing the failure point
6. THE usage events emitted during discovery SHALL set schema_type to "discovery" for cost attribution, distinguishing discovery token spend from standard extraction spend
