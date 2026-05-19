# Implementation Plan: Intelligent Extraction Improvement

## Overview

Implement three tightly coupled improvements: (1) a pure `QualityScorer` that evaluates `text_table_parser` output and auto-escalates to LLM extraction on failure, (2) a document-scoped chat panel with action buttons and re-extraction flow, and (3) user-approved schema caching via a `PendingSchemaStore` and `SchemaApprovalBanner`. All three share a common `pending_schema_id` data flow.

## Tasks

- [x] 1. Add new API response models and extend `FinalOutput`
  - [x] 1.1 Add `ActionButton`, `ChatResponse`, `ReextractResponse`, `ApproveSchemaResponse` Pydantic models to `api/models/response.py`
    - Add `ActionButton(label: str, action: str, table_id: str | None = None)`
    - Add `ChatResponse(reply: str, action_buttons: list[ActionButton] | None, pending_schema_id: str | None)`
    - Add `ReextractResponse(tables: list[Table], pending_schema_id: str, validation_warnings: list[str])`
    - Add `ApproveSchemaResponse(approved: bool, fingerprint_key: str)`
    - Add `llm_escalated: bool = False` field to `FinalOutput`
    - _Requirements: 2.6, 3.1, 3.2, 3.3, 9.1_

- [x] 2. Implement `QualityScorer` pure function
  - [x] 2.1 Create `pipeline/quality_scorer.py` with `CheckResult`, `QualityResult` dataclasses and `score_tables()` function
    - Implement all five checks: `cell_fragmentation` (threshold 0.40), `header_fragmentation` (substring of known keywords), `date_column_incoherence` (threshold 0.50), `row_uniformity` (std dev threshold 2.0), `numeric_column_incoherence` (threshold 0.30)
    - Known financial keywords: `SETTL`, `TRADE`, `DESC`, `ISIN`, `CUSIP`, `AMOUNT`, `DEBIT`, `CREDIT`, `BALANCE`, `QTY`, `PRICE`, `DATE`, `BUY`, `SELL`, `NET`
    - Accepted date formats: `YYYY-MM-DD`, `DD/MM/YYYY`, `MM/DD/YYYY`, `DD-MMM-YYYY`
    - Individual checks catch exceptions internally and return `passed=True, metric=0.0` on error (fail-safe)
    - Return `verdict="fail"` if any check fails; `verdict="pass"` if all pass
    - Bypass scoring (return early) when input has zero tables or all tables have zero rows
    - _Requirements: 1.1–1.9, 2.7_
  - [ ]* 2.2 Write unit tests for `QualityScorer` in `tests/test_quality_scorer.py`
    - Test each of the five checks at boundary values (exactly at threshold, one above, one below)
    - Test `failed_checks` list contents and `verdict` for mixed pass/fail scenarios
    - Test empty table list bypasses scoring
    - _Requirements: 1.1–1.9_

- [x] 3. Implement `PendingSchemaStore`
  - [x] 3.1 Create `pipeline/discovery/pending_schema_store.py` with `PendingEntry` dataclass and `PendingSchemaStore` class
    - `store_pending(schema, fingerprint, tenant_id, job_id) -> str` — stores entry, returns UUID4 `pending_id`
    - `get_pending(pending_id, tenant_id) -> PendingEntry | None` — returns `None` if expired (>24h) or not found; lazy expiry check on `created_at`
    - `discard(pending_id, tenant_id) -> bool` — deletes entry, returns `True` if existed
    - `expire_stale() -> int` — removes all entries older than 24h, returns count removed
    - Internal store: `dict[str, PendingEntry]` keyed by `pending_id`
    - _Requirements: 8.1–8.6_
  - [ ]* 3.2 Write unit tests for `PendingSchemaStore` in `tests/test_pending_schema_store.py`
    - Test store/retrieve round-trip preserves all fields
    - Test expiry at exactly 24h boundary (entry at 23h59m returns data; entry at 24h01m returns None)
    - Test `discard()` removes entry and returns correct boolean
    - Test `expire_stale()` removes only stale entries
    - _Requirements: 8.1–8.6_

- [x] 4. Modify `SchemaCache` to enforce approval gating
  - [x] 4.1 Add `approved` flag to `SchemaCache` in `pipeline/discovery/schema_cache.py`
    - Add `approved: bool = False` parameter to `store()` — write `"approved": approved` into the `_store` entry dict
    - Modify `lookup()` to check `entry.get("approved", False)` and return `None` when flag is absent or `False`
    - Log `schema_cache.approved_hit` (with fingerprint key and usage count) when `lookup()` returns an approved entry
    - _Requirements: 10.1–10.5_

- [x] 5. Add quality scoring and LLM escalation path to `pipeline/runner.py`
  - [x] 5.1 Insert quality scoring + escalation block after the existing text-table-parser fallback in `pipeline/runner.py`
    - Add `elif section_tables and tenant.vlm_enabled:` branch after the existing `if not section_tables and not tenant.vlm_enabled:` block
    - Import and call `score_tables(section_tables)` with timing; emit `quality_scorer.result` log event (job_id, verdict, failed_checks, per-check details, duration_ms)
    - On `verdict == "fail"`: discard text-parser tables, emit `quality_scorer.escalated` (job_id, failed_checks, tables_discarded count), call `extract_document_with_llm`, replace tables with LLM result, set `llm_escalated = True` on result metadata
    - On `verdict == "pass"`: emit `quality_scorer.escalation_skipped` with `reason="quality_pass"`
    - When `vlm_enabled=False` and quality would fail: emit `quality_scorer.escalation_skipped` with `reason="vlm_disabled"`
    - On LLM escalation error: catch exception, log `quality_scorer.escalation_failed`, re-instate discarded text-parser tables
    - When escalation produces no tables: log `quality_scorer.escalation_empty`
    - Store discovered schema in `PendingSchemaStore` after successful LLM escalation; attach `pending_schema_id` to result metadata
    - Set `llm_escalated: True` on `FinalOutput` when escalation completes
    - _Requirements: 2.1–2.7, 11.1–11.5_

- [x] 6. Implement chat API endpoints and system prompt builder
  - [x] 6.1 Create `api/routes/chat.py` with `build_chat_system_prompt()` and three endpoints
    - Implement `build_chat_system_prompt(job_result: dict, filename: str) -> str` with sections: role/scope instruction (including filename), guardrail instruction, schema type, extracted fields (name + value), abstention count + list, table summaries (table_id, type, row count, headers)
    - `POST /v1/jobs/{id}/chat`: validate non-empty `message` (HTTP 400 / `ERR_CHAT_001`), look up job in `_RESULTS` (HTTP 404 / `ERR_CHAT_002`), build system prompt, prepend to history, call `BedrockVLMClient`, parse response for action buttons, return `ChatResponse`
    - `POST /v1/jobs/{id}/reextract-table`: look up job (HTTP 404), call `extract_document_with_llm` for relevant section, run existing validator on new tables, store schema in `PendingSchemaStore`, return `ReextractResponse` with validation warnings per Requirements 12.1–12.4
    - `POST /v1/jobs/{id}/approve-schema`: look up `pending_schema_id` in `PendingSchemaStore` (HTTP 404 / `ERR_SCHEMA_001`), call `SchemaCache.store(..., approved=True)`, call `pending_store.discard()`, log `schema_cache.approved_hit`, return `ApproveSchemaResponse`
    - All three endpoints require tenant auth via `Depends(resolve_tenant)`; return HTTP 404 for wrong-tenant job lookups
    - _Requirements: 3.1–3.8, 4.1–4.5, 5.1–5.4, 6.1–6.6, 12.1–12.4_
  - [x] 6.2 Register chat router and `pending_schema_store` in `api/main.py`
    - Import and include `chat_router` in `create_app()`
    - Instantiate `PendingSchemaStore` in the lifespan hook and assign to `app.state.pending_schema_store`
    - _Requirements: 3.1–3.3_

- [x] 7. Checkpoint — ensure backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement `ChatPanel` React component
  - [x] 8.1 Create `frontend/src/components/ChatPanel.jsx`
    - Props: `{ jobId, filename, onPendingSchema }`
    - State: `messages` (array of `{ role, content, actionButtons? }`), `input`, `loading`
    - Persist/restore conversation history to `sessionStorage` under key `chat_history_{jobId}`
    - On mount: load from `sessionStorage`; if empty, push welcome message: "I can help you review the extraction results for [filename]. Describe any issues you see with the extracted fields or tables."
    - On send (button click or Enter key): append user message, call `apiPost(/v1/jobs/${jobId}/chat, { message, history })`, append assistant reply with optional `actionButtons`
    - Render user messages right-aligned, assistant messages left-aligned in a scrollable container
    - Render `actionButtons` as `<button>` elements below the triggering assistant message
    - "Re-extract this table with AI": call `apiPost(/v1/jobs/${jobId}/reextract-table, { table_id })`; if response has `pending_schema_id`, call `onPendingSchema(pending_schema_id)`
    - "Re-extract all tables with AI": same endpoint without `table_id`
    - "Accept current output": close action buttons, keep input focused
    - "Ask another question": focus message input field
    - Disable input and show loading indicator while awaiting response
    - _Requirements: 7.1–7.7, 6.1–6.6_
  - [ ]* 8.2 Write component tests in `frontend/src/components/ChatPanel.test.jsx`
    - Render with empty history → welcome message shown
    - Send message → loading state active, input disabled
    - Response with action buttons → buttons rendered below assistant message
    - "Ask another question" button → input field focused
    - _Requirements: 7.2–7.7_

- [x] 9. Implement `SchemaApprovalBanner` React component
  - [x] 9.1 Create `frontend/src/components/SchemaApprovalBanner.jsx`
    - Props: `{ jobId, pendingSchemaId, schemaLabel, institution, fieldCount, tableCount, onApproved, onDiscarded }`
    - Show only when `pendingSchemaId` is non-null and `sessionStorage` key `schema_banner_acted_{jobId}` is not set
    - Display: schema type label, institution name (if present), field count, table count, "Accept & Save Schema" button, "Discard" button
    - "Accept & Save Schema": call `apiPost(/v1/jobs/${jobId}/approve-schema, { pending_schema_id: pendingSchemaId })`, set `sessionStorage` flag, call `onApproved()`, show confirmation toast
    - "Discard": set `sessionStorage` flag, call `onDiscarded()`, hide banner (let 24h expiry clean up pending entry)
    - Dismiss (click outside or Escape key): treat as Discard
    - _Requirements: 9.1–9.6_
  - [ ]* 9.2 Write component tests in `frontend/src/components/SchemaApprovalBanner.test.jsx`
    - Shown when `pendingSchemaId` is set and no `sessionStorage` flag
    - Hidden after "Accept & Save Schema" click (sets flag, calls `onApproved`)
    - Hidden after "Discard" click (sets flag, calls `onDiscarded`)
    - Not shown when `sessionStorage` flag is already set
    - _Requirements: 9.1–9.6_

- [x] 10. Wire `ChatPanel` and `SchemaApprovalBanner` into `ResultsViewerScreen`
  - [x] 10.1 Modify `frontend/src/screens/ResultsViewerScreen.jsx` to add Chat tab and schema banner
    - Add `pendingSchemaId` state (initialised from `result?.pending_schema_id` or `null`)
    - Add `"chat"` tab to the `tabs` array: `{ id: "chat", label: "Chat" }`
    - Render `<ChatPanel jobId={jobId} filename={jobData?.filename} onPendingSchema={(id) => setPendingSchemaId(id)} />` when `activeTab === "chat"`
    - Render `<SchemaApprovalBanner>` above the tab bar when `pendingSchemaId` is non-null and `result?.llm_escalated` is true or `pendingSchemaId` was set via chat re-extraction
    - Pass `schemaLabel`, `institution`, `fieldCount`, `tableCount` from `output` to the banner
    - On `onApproved`: clear `pendingSchemaId` state
    - On `onDiscarded`: clear `pendingSchemaId` state
    - _Requirements: 7.1, 9.1, 9.3–9.6_

- [x] 11. Checkpoint — ensure frontend renders correctly
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Write property-based tests
  - [ ]* 12.1 Write PBT for `QualityScorer` in `tests/pbt/test_quality_scorer_pbt.py`
    - **Property 1: scorer always returns exactly five checks** — `@given(tables=st.lists(table_strategy(), min_size=1))` — assert `len(result.checks) == 5` and all five check names present
    - **Property 2: cell fragmentation threshold is exact** — generate tables with controlled short-cell ratio; assert check passes iff ratio ≤ 0.40
    - **Property 7: verdict = fail iff any check fails** — for any tables, assert `result.verdict == "fail"` iff `any(not c.passed for c in result.checks)` and `result.failed_checks` matches
    - **Validates: Requirements 1.1, 1.2, 1.7, 1.8, 1.9**
  - [ ]* 12.2 Write PBT for `PendingSchemaStore` in `tests/pbt/test_pending_schema_store_pbt.py`
    - **Property 12: pending store round-trip preserves schema and metadata** — `@given(schema=schema_strategy(), fingerprint=fingerprint_strategy(), tenant_id=st.text(min_size=1), job_id=st.text(min_size=1))` — assert retrieved entry matches stored values
    - **Property 14: pending entries expire after 24 hours** — `@given(age_hours=st.floats(min_value=24.001, max_value=720.0))` — backdate `created_at`, assert `get_pending()` returns `None`
    - **Validates: Requirements 8.1, 8.3, 8.5**
  - [ ]* 12.3 Write PBT for `SchemaCache` in `tests/pbt/test_schema_cache_pbt.py`
    - **Property 13: pending schemas never returned by SchemaCache.lookup()** — store schema without `approved=True`, assert `lookup()` returns `None`
    - **Property 15: lookup only returns approved entries** — `@given(approved=st.booleans())` — store with given flag, assert `lookup()` returns schema iff `approved=True`
    - **Validates: Requirements 8.2, 8.6, 10.5**
  - [ ]* 12.4 Write PBT for chat system prompt in `tests/pbt/test_chat_prompt_pbt.py`
    - **Property 10: prompt contains all required sections for any job result** — `@given(job_result=job_result_strategy(), filename=st.text(min_size=1))` — assert prompt contains filename, schema type, all field names/values, abstention count, each table's table_id/type/row count/headers, scoping instruction, guardrail instruction
    - **Property 11: system prompt includes full conversation history** — `@given(history=st.lists(message_strategy()))` — assert all history messages appear in correct order before the new user message
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.5**

- [x] 13. Final checkpoint — ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The `approved` flag change to `SchemaCache` is backward-compatible: existing entries without the flag are treated as unapproved (cache miss)
- PBT tests use Hypothesis with `@settings(max_examples=100)` and are tagged with `# Feature: intelligent-extraction-improvement, Property N: <text>`
- The `build_chat_system_prompt` function is defined in `api/routes/chat.py` and is never sent to or modifiable by the client
- LLM escalation reuses the existing `extract_document_with_llm` function — no new LLM call path is introduced

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "3.1", "2.1"] },
    { "id": 1, "tasks": ["2.2", "3.2", "4.1"] },
    { "id": 2, "tasks": ["5.1"] },
    { "id": 3, "tasks": ["6.1", "6.2"] },
    { "id": 4, "tasks": ["8.1", "9.1"] },
    { "id": 5, "tasks": ["8.2", "9.2", "10.1"] },
    { "id": 6, "tasks": ["12.1", "12.2", "12.3", "12.4"] }
  ]
}
```
