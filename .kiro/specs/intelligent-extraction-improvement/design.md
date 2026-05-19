# Design Document: Intelligent Extraction Improvement

## Overview

This feature adds three tightly coupled improvements to the PDF ingestion platform:

1. **Auto Quality Check → LLM Escalation** — a `QualityScorer` evaluates `text_table_parser` output using five internal consistency signals and automatically escalates to LLM extraction when quality fails.
2. **Document-Scoped Chat Panel** — a conversational interface on `ResultsViewerScreen` that lets operators describe extraction problems and trigger re-extraction directly from the conversation.
3. **User-Approved Schema Caching** — discovered schemas enter a "pending" state and are only persisted to the approved cache when the user explicitly accepts them.

The three improvements share a common data flow: quality failure or chat re-extraction both produce a `pending_schema_id`, which the `SchemaApprovalBanner` uses to gate schema persistence.

---

## Architecture

```mermaid
flowchart TD
    subgraph Pipeline [pipeline/runner.py]
        TTP[text_table_parser] --> QS[quality_scorer.score_tables]
        QS -->|verdict=fail & vlm_enabled| LLM[extract_document_with_llm]
        QS -->|verdict=pass| OUT[job result]
        LLM --> PSS[pending_schema_store.store_pending]
        LLM --> OUT
        PSS --> OUT
    end

    subgraph API [api/routes/chat.py]
        CHAT[POST /v1/jobs/{id}/chat]
        REEX[POST /v1/jobs/{id}/reextract-table]
        APPR[POST /v1/jobs/{id}/approve-schema]
    end

    subgraph Store [pipeline/discovery/]
        SC[SchemaCache\napproved only]
        PS[PendingSchemaStore\n24h TTL]
    end

    REEX --> LLM
    REEX --> PSS
    APPR --> SC
    APPR --> PS

    subgraph Frontend [frontend/src/]
        RVS[ResultsViewerScreen]
        CP[ChatPanel]
        SAB[SchemaApprovalBanner]
    end

    RVS --> CP
    RVS --> SAB
    CP --> CHAT
    CP --> REEX
    SAB --> APPR
```

### Key Design Decisions

**Quality scorer as a pure function** — `score_tables(tables) -> QualityResult` takes only the table list and returns a deterministic result. No I/O, no side effects. This makes it trivially testable and easy to call from the runner without async overhead.

**Pending schema store separate from SchemaCache** — keeping pending entries in a dedicated `PendingSchemaStore` means `SchemaCache.lookup()` never needs to filter by approval status at query time. The approved cache stays fast and simple; the pending store handles TTL expiry independently.

**Chat endpoint builds system prompt server-side** — the client sends only `message` and `history`; the server constructs the full system prompt from the stored job result. This prevents prompt injection and ensures the LLM always has accurate document context.

**LLM escalation reuses `extract_document_with_llm`** — the same function used for VLM fallback in the main pipeline is reused for both auto-escalation and chat re-extraction. No new LLM call path is introduced.

---

## Components and Interfaces

### 1. `pipeline/quality_scorer.py` (new)

```python
@dataclass
class CheckResult:
    name: str          # one of the five check names
    passed: bool
    metric: float      # the measured value (e.g. fragmentation ratio)
    threshold: float   # the threshold that was compared against

@dataclass
class QualityResult:
    verdict: str                  # "pass" | "fail"
    failed_checks: list[str]      # names of failed checks
    checks: list[CheckResult]     # one entry per check, always 5

def score_tables(tables: list[Table]) -> QualityResult:
    """Pure function. Evaluates five quality checks on extracted tables."""
```

The five checks and their thresholds:

| Check | Metric | Threshold | Fail condition |
|---|---|---|---|
| `cell_fragmentation` | fraction of cells with ≤3 chars | 0.40 | metric > threshold |
| `header_fragmentation` | any header token is a substring of a known keyword and shorter | boolean | any match found |
| `date_column_incoherence` | fraction of non-null date-column values failing ISO parse | 0.50 | metric > threshold |
| `row_uniformity` | std dev of non-null cell count per row | 2.0 | metric > threshold |
| `numeric_column_incoherence` | fraction of non-null numeric-column values failing number parse | 0.30 | metric > threshold |

Known financial keywords for header fragmentation: `SETTL`, `TRADE`, `DESC`, `ISIN`, `CUSIP`, `AMOUNT`, `DEBIT`, `CREDIT`, `BALANCE`, `QTY`, `PRICE`, `DATE`, `BUY`, `SELL`, `NET`.

### 2. `pipeline/discovery/pending_schema_store.py` (new)

```python
@dataclass
class PendingEntry:
    pending_id: str          # UUID4
    schema: DiscoveredSchema
    fingerprint: SchemaFingerprint
    tenant_id: str
    job_id: str
    created_at: datetime

class PendingSchemaStore:
    def store_pending(
        self,
        schema: DiscoveredSchema,
        fingerprint: SchemaFingerprint,
        tenant_id: str,
        job_id: str,
    ) -> str:
        """Store schema in pending state. Returns pending_id (UUID)."""

    def get_pending(self, pending_id: str, tenant_id: str) -> PendingEntry | None:
        """Retrieve a pending entry. Returns None if expired or not found."""

    def discard(self, pending_id: str, tenant_id: str) -> bool:
        """Delete a pending entry. Returns True if it existed."""

    def expire_stale(self) -> int:
        """Remove entries older than 24h. Returns count removed."""
```

Auto-expiry is enforced lazily: `get_pending()` checks `created_at` and returns `None` (without deleting) if the entry is older than 24 hours. A background sweep via `expire_stale()` can be called periodically from the lifespan hook.

### 3. `SchemaCache` modifications (`pipeline/discovery/schema_cache.py`)

Two changes to the existing class:

- `store()` gains an `approved: bool = False` parameter. Entries stored without `approved=True` are treated as cache misses by `lookup()`.
- `lookup()` checks `entry["approved"]` and returns `None` if the flag is absent or `False`.

The `POST /v1/jobs/{id}/approve-schema` endpoint calls `SchemaCache.store(..., approved=True)` after retrieving the schema from `PendingSchemaStore`.

### 4. `pipeline/runner.py` modifications

After the text-table-parser fallback block (currently gated on `not tenant.vlm_enabled`), add a quality-scoring + escalation path for the case where `vlm_enabled` is `True`:

```python
# Existing: text parser runs when vlm_enabled is False
if not section_tables and not tenant.vlm_enabled:
    ...  # unchanged

# New: quality scoring + escalation when vlm_enabled is True
elif section_tables and tenant.vlm_enabled:
    from pipeline.quality_scorer import score_tables
    import time as _time
    _qs_start = _time.time()
    quality_result = score_tables(section_tables)
    duration_ms = (_time.time() - _qs_start) * 1000

    logger.info(
        "quality_scorer.result",
        job_id=job_id,
        verdict=quality_result.verdict,
        failed_checks=quality_result.failed_checks,
        checks=[c.__dict__ for c in quality_result.checks],
        duration_ms=round(duration_ms, 2),
    )

    if quality_result.verdict == "fail":
        discarded_count = len(section_tables)
        logger.info(
            "quality_scorer.escalated",
            job_id=job_id,
            failed_checks=quality_result.failed_checks,
            tables_discarded=discarded_count,
        )
        section_tables = []  # discard text-parser output
        llm_result = await extract_document_with_llm(
            document_text="\n\n".join(section_page_texts),
            vlm_client=ports.vlm_client,
            page_texts=section_page_texts,
        )
        # ... convert llm_result tables to Table objects and set llm_escalated flag
    else:
        logger.info("quality_scorer.escalation_skipped", reason="quality_pass")
```

The `llm_escalated` flag is added to `FinalOutput` (or stored in `_RESULTS` metadata) so the frontend can show the `SchemaApprovalBanner`.

### 5. `api/routes/chat.py` (new)

Three endpoints, all requiring tenant auth via `Depends(resolve_tenant)`:

#### `POST /v1/jobs/{id}/chat`

```
Request:  { "message": str, "history": [{"role": str, "content": str}] }
Response: { "reply": str, "action_buttons": [...] | null, "pending_schema_id": str | null }
```

Handler logic:
1. Look up job result from `_RESULTS` (404 if not found or wrong tenant).
2. Validate `message` is non-empty (400 if empty).
3. Call `build_chat_system_prompt(job_result, filename)` to construct the system prompt.
4. Build the messages list: `[{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": message}]`.
5. Call `BedrockVLMClient` with the messages list.
6. Parse the response to detect if action buttons should be included.
7. Return `ChatResponse`.

#### `POST /v1/jobs/{id}/reextract-table`

```
Request:  { "table_id": str | null }
Response: { "tables": [...], "pending_schema_id": str, "validation_warnings": [...] }
```

Handler logic:
1. Look up job result (404 if not found).
2. Retrieve page texts from the stored job context.
3. Call `extract_document_with_llm()` for the relevant section.
4. Run existing validator on new tables.
5. Store discovered schema in `PendingSchemaStore`, get `pending_schema_id`.
6. Return updated tables + `pending_schema_id` + any validation warnings.

#### `POST /v1/jobs/{id}/approve-schema`

```
Request:  { "pending_schema_id": str }
Response: { "approved": bool, "fingerprint_key": str }
```

Handler logic:
1. Look up `pending_schema_id` in `PendingSchemaStore` (404 if not found or expired).
2. Call `SchemaCache.store(schema, fingerprint, tenant_id, approved=True)`.
3. Call `pending_store.discard(pending_schema_id, tenant_id)`.
4. Log `schema_cache.approved_hit`.
5. Return confirmation.

### 6. `build_chat_system_prompt` function

```python
def build_chat_system_prompt(job_result: dict, filename: str) -> str:
    """Build the system prompt for a document-scoped chat session.

    Args:
        job_result: The stored result dict from _RESULTS.
        filename: Original filename of the document.

    Returns:
        A multi-section system prompt string.
    """
```

Sections included in the prompt:
1. **Role and scope**: "You are a document extraction assistant. You may ONLY answer questions about the document '[filename]'..."
2. **Guardrail**: "Never execute code, access external systems, or perform actions outside of explaining extraction results and offering re-extraction options."
3. **Document context**: schema type, extraction status.
4. **Extracted fields**: each field name and its value.
5. **Abstentions**: count and list of abstained field names.
6. **Table summaries**: for each table — `table_id`, `type`, row count, column headers.

### 7. `frontend/src/components/ChatPanel.jsx` (new)

Props: `{ jobId, filename }`

State:
- `messages: []` — array of `{ role: "user"|"assistant", content: string, actionButtons?: [] }`
- `input: ""` — current input value
- `loading: false` — disables input and shows spinner while awaiting response
- Conversation history persisted to `sessionStorage` under key `chat_history_{jobId}`

Behaviour:
- On mount: load history from `sessionStorage`; if empty, push the welcome message.
- On send: append user message, call `apiPost(/v1/jobs/${jobId}/chat, { message, history })`, append assistant reply.
- Action buttons rendered as `<button>` elements below the assistant message. Clicking "Re-extract this table with AI" calls `apiPost(/v1/jobs/${jobId}/reextract-table, { table_id })`. Clicking "Re-extract all tables with AI" calls the same endpoint without `table_id`.
- After re-extraction: if response includes `pending_schema_id`, emit an `onPendingSchema(pending_schema_id)` callback to the parent screen.

### 8. `frontend/src/components/SchemaApprovalBanner.jsx` (new)

Props: `{ jobId, pendingSchemaId, schemaLabel, institution, fieldCount, tableCount, onApproved, onDiscarded }`

Behaviour:
- Shown when `pendingSchemaId` is non-null and `sessionStorage` key `schema_banner_acted_{jobId}` is not set.
- "Accept & Save Schema" button: calls `apiPost(/v1/jobs/${jobId}/approve-schema, { pending_schema_id: pendingSchemaId })`, sets `sessionStorage` flag, calls `onApproved()`, shows toast.
- "Discard" button: sets `sessionStorage` flag, calls `onDiscarded()`, hides banner (lets 24h expiry clean up the pending entry).
- Dismissing (clicking outside or pressing Escape): treated as Discard.

---

## Data Models

### New Python models

```python
# pipeline/quality_scorer.py
@dataclass
class CheckResult:
    name: str
    passed: bool
    metric: float
    threshold: float

@dataclass
class QualityResult:
    verdict: str           # "pass" | "fail"
    failed_checks: list[str]
    checks: list[CheckResult]

# pipeline/discovery/pending_schema_store.py
@dataclass
class PendingEntry:
    pending_id: str
    schema: DiscoveredSchema
    fingerprint: SchemaFingerprint
    tenant_id: str
    job_id: str
    created_at: datetime
```

### New API response models

```python
# api/models/response.py additions

class ActionButton(BaseModel):
    label: str
    action: str   # "reextract_table" | "reextract_all" | "accept" | "ask_again"
    table_id: str | None = None

class ChatResponse(BaseModel):
    reply: str
    action_buttons: list[ActionButton] | None = None
    pending_schema_id: str | None = None

class ReextractResponse(BaseModel):
    tables: list[Table]
    pending_schema_id: str
    validation_warnings: list[str]

class ApproveSchemaResponse(BaseModel):
    approved: bool
    fingerprint_key: str
```

### `FinalOutput` extension

Add `llm_escalated: bool = False` to `FinalOutput` in `api/models/response.py`. This flag is set by the runner when auto-escalation occurs and is read by the frontend to decide whether to show the `SchemaApprovalBanner` on initial load.

### `SchemaCache` entry schema change

Add `"approved": bool` field to the internal `_store` dict entries. Default is `False` for backward compatibility. `lookup()` returns `None` when `approved` is `False`.

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Quality scorer always returns exactly five checks

*For any* list of tables (including empty lists with at least one table having at least one row), `score_tables()` returns a `QualityResult` with exactly five `CheckResult` entries, one for each named check (`cell_fragmentation`, `header_fragmentation`, `date_column_incoherence`, `row_uniformity`, `numeric_column_incoherence`), and each entry contains `name`, `passed`, `metric`, and `threshold` fields.

**Validates: Requirements 1.1, 1.9**

### Property 2: Cell fragmentation threshold is exact

*For any* list of tables, the `cell_fragmentation` check passes if and only if the fraction of cells with 3 or fewer characters is ≤ 0.40, and fails if and only if that fraction exceeds 0.40.

**Validates: Requirements 1.2**

### Property 3: Header fragmentation detects partial keywords

*For any* list of tables, the `header_fragmentation` check fails if and only if at least one header token is a proper substring of a known financial keyword (case-insensitive), and passes otherwise.

**Validates: Requirements 1.3**

### Property 4: Date column incoherence threshold is exact

*For any* list of tables containing a column whose name contains DATE, SETTL, or TRADE, the `date_column_incoherence` check fails if and only if more than 50% of non-null values in that column cannot be parsed as a date in any of the four accepted formats.

**Validates: Requirements 1.4**

### Property 5: Row uniformity threshold is exact

*For any* list of tables, the `row_uniformity` check fails if and only if the standard deviation of non-null cell count per row across all tables exceeds 2.0.

**Validates: Requirements 1.5**

### Property 6: Numeric column incoherence threshold is exact

*For any* list of tables containing a column whose name contains BUY, SELL, QTY, AMOUNT, or NET, the `numeric_column_incoherence` check fails if and only if more than 30% of non-null values in that column cannot be parsed as a number after stripping commas and currency symbols.

**Validates: Requirements 1.6**

### Property 7: Overall verdict is fail iff any check fails

*For any* list of tables, `score_tables()` returns `verdict == "fail"` if and only if at least one of the five checks has `passed == False`, and `verdict == "pass"` if and only if all five checks have `passed == True`. The `failed_checks` list contains exactly the names of checks where `passed == False`.

**Validates: Requirements 1.7, 1.8**

### Property 8: vlm_enabled=False prevents escalation

*For any* quality verdict (including "fail") and any tenant with `vlm_enabled == False`, the pipeline never calls `extract_document_with_llm` as a result of quality scoring, and the text-parser tables are retained in the output unchanged.

**Validates: Requirements 2.5**

### Property 9: Empty text-parser output bypasses quality scoring

*For any* pipeline run where `text_table_parser` produces zero tables (or all tables have zero rows), `score_tables()` is never invoked.

**Validates: Requirements 2.7**

### Property 10: System prompt contains all required sections for any job result

*For any* job result (varying fields, tables, abstentions, schema types), `build_chat_system_prompt(job_result, filename)` returns a string that contains: the filename, the schema type, every extracted field name and its value, the abstention count, and for each table its `table_id`, `type`, row count, and column headers. The prompt also contains the scoping instruction and the guardrail instruction.

**Validates: Requirements 4.1, 4.2, 4.3**

### Property 11: System prompt includes full conversation history

*For any* history list of message objects, `build_chat_system_prompt` (or the chat handler that incorporates history) produces a messages array that includes every message from the history in the correct order before the new user message.

**Validates: Requirements 4.5**

### Property 12: Pending store round-trip preserves schema and metadata

*For any* `DiscoveredSchema`, `SchemaFingerprint`, `tenant_id`, and `job_id`, calling `store_pending()` returns a UUID string, and `get_pending(uuid, tenant_id)` returns an entry with the same schema, fingerprint, tenant_id, and job_id.

**Validates: Requirements 8.1, 8.3**

### Property 13: Pending schemas are never returned by SchemaCache.lookup()

*For any* schema stored via `PendingSchemaStore.store_pending()` (and not yet moved to the approved cache), `SchemaCache.lookup()` with the matching fingerprint and tenant_id returns `None`.

**Validates: Requirements 8.2, 8.6**

### Property 14: Pending entries expire after 24 hours

*For any* pending entry whose `created_at` is more than 24 hours in the past, `get_pending()` returns `None` without requiring explicit deletion.

**Validates: Requirements 8.5**

### Property 15: SchemaCache.lookup() only returns approved entries

*For any* schema stored in `SchemaCache` without `approved=True`, `lookup()` with the matching fingerprint and tenant_id returns `None`. Only entries stored with `approved=True` are returned.

**Validates: Requirements 10.5**

### Property 16: Row-count warning when re-extraction produces fewer rows

*For any* re-extraction result where the new table has fewer rows than the original table, the API response includes a warning string containing both the new row count and the original row count.

**Validates: Requirements 12.4**

---

## Error Handling

### Quality scorer errors

`score_tables()` is a pure function with no I/O. If the input is malformed (e.g. rows contain unexpected types), individual checks catch exceptions internally and return `passed=True` with `metric=0.0` (fail-safe: don't escalate on scorer errors). The runner logs a `quality_scorer.check_error` event if any check raises.

### LLM escalation errors

If `extract_document_with_llm` raises during auto-escalation, the runner catches the exception, logs `quality_scorer.escalation_failed`, and falls back to the discarded text-parser tables (re-instates them). The job result is not marked as failed.

### Chat endpoint errors

- `message` empty or missing → HTTP 400 with `ERR_CHAT_001`.
- Job not found or wrong tenant → HTTP 404 with `ERR_CHAT_002`.
- LLM call fails → HTTP 502 with `ERR_CHAT_003`; the error message is safe to surface to the client.

### Re-extract endpoint errors

- Job not found → HTTP 404.
- `table_id` provided but not found in job result → HTTP 404 with `ERR_REEXTRACT_001`.
- LLM call fails → HTTP 502; include `validation_warnings: ["Re-extraction failed. Original data retained."]`.

### Approve-schema endpoint errors

- `pending_schema_id` not found or expired → HTTP 404 with `ERR_SCHEMA_001`.
- Wrong tenant → HTTP 404 (same response, no information leakage).

### Pending schema store

`get_pending()` returns `None` for expired entries rather than raising. Callers treat `None` as "not found" and return HTTP 404.

---

## Testing Strategy

### Unit tests (example-based)

- `test_quality_scorer.py`: concrete examples for each of the five checks at boundary values (exactly at threshold, one above, one below). Verify `failed_checks` list contents and `verdict`.
- `test_pending_schema_store.py`: store/retrieve round-trip, expiry at exactly 24h boundary, discard removes entry.
- `test_build_chat_system_prompt.py`: verify all required sections appear in the prompt for a representative job result.
- `test_chat_routes.py`: HTTP 400 on empty message, HTTP 404 on unknown job, happy-path response structure.
- `test_schema_cache_approved.py`: verify `lookup()` returns `None` for unapproved entries, returns schema for approved entries.

### Property-based tests (Hypothesis)

The project uses Python; the property-based testing library is **Hypothesis**.

Each property test runs a minimum of **100 examples** (configured via `@settings(max_examples=100)`).

Each test is tagged with a comment referencing the design property:
```python
# Feature: intelligent-extraction-improvement, Property N: <property_text>
```

**`tests/pbt/test_quality_scorer_pbt.py`**

```python
from hypothesis import given, settings, strategies as st

# Feature: intelligent-extraction-improvement, Property 1: scorer always returns 5 checks
@given(tables=st.lists(table_strategy(), min_size=1))
@settings(max_examples=100)
def test_scorer_returns_five_checks(tables): ...

# Feature: intelligent-extraction-improvement, Property 2: cell fragmentation threshold
@given(tables=tables_with_short_cell_ratio())
@settings(max_examples=100)
def test_cell_fragmentation_threshold(tables, ratio): ...

# Feature: intelligent-extraction-improvement, Property 7: verdict = fail iff any check fails
@given(tables=st.lists(table_strategy(), min_size=1))
@settings(max_examples=100)
def test_verdict_fail_iff_any_check_fails(tables): ...
```

**`tests/pbt/test_pending_schema_store_pbt.py`**

```python
# Feature: intelligent-extraction-improvement, Property 12: pending store round-trip
@given(schema=schema_strategy(), fingerprint=fingerprint_strategy(), ...)
@settings(max_examples=100)
def test_pending_store_round_trip(schema, fingerprint, tenant_id, job_id): ...

# Feature: intelligent-extraction-improvement, Property 14: pending entries expire after 24h
@given(age_hours=st.floats(min_value=24.001, max_value=720.0))
@settings(max_examples=100)
def test_pending_entry_expires_after_24h(age_hours): ...
```

**`tests/pbt/test_schema_cache_pbt.py`**

```python
# Feature: intelligent-extraction-improvement, Property 13: pending not returned by lookup
@given(schema=schema_strategy(), fingerprint=fingerprint_strategy())
@settings(max_examples=100)
def test_pending_not_returned_by_lookup(schema, fingerprint): ...

# Feature: intelligent-extraction-improvement, Property 15: lookup only returns approved
@given(schema=schema_strategy(), approved=st.booleans())
@settings(max_examples=100)
def test_lookup_only_returns_approved(schema, approved): ...
```

**`tests/pbt/test_chat_prompt_pbt.py`**

```python
# Feature: intelligent-extraction-improvement, Property 10: prompt contains all required sections
@given(job_result=job_result_strategy(), filename=st.text(min_size=1))
@settings(max_examples=100)
def test_prompt_contains_all_required_sections(job_result, filename): ...

# Feature: intelligent-extraction-improvement, Property 11: prompt includes full history
@given(history=st.lists(message_strategy()), job_result=job_result_strategy())
@settings(max_examples=100)
def test_prompt_includes_full_history(history, job_result): ...
```

### Integration tests

- `test_pipeline_escalation.py`: mock `extract_document_with_llm` and `score_tables`; verify that when scorer returns "fail" and `vlm_enabled=True`, the mock LLM is called and its tables appear in the result.
- `test_pipeline_no_escalation_vlm_disabled.py`: verify LLM is never called when `vlm_enabled=False` regardless of quality verdict.
- `test_chat_endpoint_integration.py`: mock `BedrockVLMClient`; verify full request/response cycle including system prompt construction.

### Frontend tests

- `ChatPanel.test.jsx`: render with empty history → welcome message shown; send message → loading state; response with action buttons → buttons rendered.
- `SchemaApprovalBanner.test.jsx`: shown when `pendingSchemaId` is set; hidden after accept; hidden after discard; not shown if `sessionStorage` flag is set.
