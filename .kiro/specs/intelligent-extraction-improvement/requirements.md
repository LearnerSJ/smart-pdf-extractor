# Requirements Document

## Introduction

This feature adds three tightly coupled improvements to the PDF ingestion platform:

1. **Auto Quality Check → LLM Escalation**: A quality scorer that evaluates `text_table_parser` output using internal consistency signals (no ground truth required) and automatically re-runs table extraction via LLM when quality fails. This eliminates the current binary choice between always-expensive LLM calls and always-inaccurate text-parser output.

2. **Document-Scoped Chat Panel**: A conversational interface on the `ResultsViewerScreen` that lets users describe problems with extracted data in natural language. The chat is strictly scoped to the current document, presents action buttons for re-extraction, and calls the LLM extractor when the user requests it.

3. **User-Approved Schema Caching**: Changes the `AutoSchemaDiscovery` system so that discovered schemas enter a "pending" state rather than being saved automatically. Schemas are only persisted to the approved cache when the user explicitly clicks "Accept & Save Schema". Only approved schemas are used for fast re-extraction on future submissions.

## Glossary

- **Quality_Scorer**: The new component that evaluates `text_table_parser` output using five internal consistency checks and produces a pass/fail verdict with per-check details
- **Text_Table_Parser**: The existing fallback extractor (`pipeline/extractors/text_table_parser.py`) that detects fixed-width columnar tables from raw text when rule-based extraction finds no tables
- **LLM_Escalation**: The automatic re-run of table extraction via `extract_document_with_llm` triggered when the Quality_Scorer returns a fail verdict
- **Quality_Check**: One of five internal consistency checks run by the Quality_Scorer: cell fragmentation, header fragmentation, date column incoherence, row uniformity, and numeric column incoherence
- **Chat_Panel**: The new React component rendered as a tab on `ResultsViewerScreen` that provides a document-scoped conversational interface for describing extraction problems
- **Chat_Guardrail**: The system-level instruction that rejects any user message not related to the current document's extracted data, responding with a fixed off-topic message
- **System_Prompt**: The dynamically generated prompt injected at the start of every chat session, containing document metadata, extracted field summary, table summaries, and strict scoping instructions
- **Action_Button**: A clickable button rendered by the Chat_Panel after the LLM identifies a problem, offering options: "Re-extract this table with AI", "Re-extract all tables with AI", "Accept current output", "Ask another question"
- **Pending_Schema**: A discovered schema that has been produced by LLM extraction but not yet approved by the user; stored in a separate pending slot and never used for fast re-extraction
- **Approved_Schema**: A discovered schema that the user has explicitly accepted via the "Accept & Save Schema" banner; persisted to the schema cache and used for fast re-extraction on future submissions
- **Schema_Approval_Banner**: The UI element shown after LLM extraction completes (from auto-escalation or chat re-extract) that prompts the user to accept or discard the pending schema
- **BedrockVLMClient**: The existing concrete implementation of `VLMClientPort` that calls Claude via AWS Bedrock
- **ResultsViewerScreen**: The existing React screen (`frontend/src/screens/ResultsViewerScreen.jsx`) that displays extraction results for a single job
- **SchemaCache**: The existing in-memory schema cache (`pipeline/discovery/schema_cache.py`) that stores discovered schemas keyed by `SchemaFingerprint`

---

## Requirements

### Requirement 1: Text-Parser Output Quality Scoring

**User Story:** As a reconciliation operator, I want the pipeline to automatically detect when text-parser table output is too fragmented or incoherent to be useful, so that poor-quality tables are escalated to LLM extraction without manual intervention.

#### Acceptance Criteria

1. THE Quality_Scorer SHALL evaluate text_table_parser output using exactly five Quality_Checks: cell fragmentation, header fragmentation, date column incoherence, row uniformity, and numeric column incoherence
2. WHEN more than 40% of all cells across all extracted tables contain 3 or fewer characters, THE Quality_Scorer SHALL mark the cell fragmentation check as failed
3. WHEN any header token is a substring of a known financial column keyword (SETTL, TRADE, DESC, ISIN, CUSIP, AMOUNT, DEBIT, CREDIT, BALANCE, QTY, PRICE, DATE, BUY, SELL, NET) and the token is shorter than the keyword, THE Quality_Scorer SHALL mark the header fragmentation check as failed
4. WHEN a column whose name contains DATE, SETTL, or TRADE has more than 50% of its non-null values failing ISO date parsing (YYYY-MM-DD, DD/MM/YYYY, MM/DD/YYYY, DD-MMM-YYYY), THE Quality_Scorer SHALL mark the date column incoherence check as failed
5. WHEN the standard deviation of non-null cell count per row across all tables exceeds 2.0, THE Quality_Scorer SHALL mark the row uniformity check as failed
6. WHEN a column whose name contains BUY, SELL, QTY, AMOUNT, or NET has more than 30% of its non-null values that cannot be parsed as a number (after stripping commas and currency symbols), THE Quality_Scorer SHALL mark the numeric column incoherence check as failed
7. IF any single Quality_Check fails, THEN THE Quality_Scorer SHALL return an overall verdict of "fail" with a list of which checks failed
8. WHEN all five Quality_Checks pass, THE Quality_Scorer SHALL return an overall verdict of "pass"
9. THE Quality_Scorer SHALL return a structured result containing: overall verdict, list of failed check names, and per-check details (check name, passed boolean, metric value, threshold)

### Requirement 2: Automatic LLM Escalation on Quality Failure

**User Story:** As a reconciliation operator, I want the pipeline to automatically re-run table extraction with the LLM when text-parser quality fails, so that scanned fixed-width documents get accurate table data without requiring manual re-submission.

#### Acceptance Criteria

1. WHEN the text_table_parser produces tables and the Quality_Scorer returns a "fail" verdict, THE Pipeline SHALL discard the text-parser tables and re-run table extraction using `extract_document_with_llm`
2. WHEN LLM_Escalation is triggered, THE Pipeline SHALL log a structured event `quality_scorer.escalated` containing job_id, failed_checks list, and table count discarded
3. WHEN LLM_Escalation produces tables, THE Pipeline SHALL replace the discarded text-parser tables with the LLM-extracted tables in the job result
4. WHEN LLM_Escalation produces no tables, THE Pipeline SHALL retain an empty table list and log `quality_scorer.escalation_empty`
5. THE Pipeline SHALL only trigger LLM_Escalation when the tenant has `vlm_enabled` set to True; IF the tenant has `vlm_enabled` set to False, THEN THE Pipeline SHALL retain the text-parser output regardless of quality verdict
6. WHEN LLM_Escalation completes successfully, THE Pipeline SHALL set a flag `llm_escalated: true` on the job result metadata so the frontend can show the Schema_Approval_Banner
7. THE Quality_Scorer SHALL be invoked only when text_table_parser produces at least one table with at least one row; empty text-parser output SHALL bypass quality scoring

### Requirement 3: New API Endpoints for Chat and Re-extraction

**User Story:** As a developer, I want dedicated API endpoints for document chat and per-table re-extraction, so that the frontend can invoke LLM operations without re-submitting the entire document.

#### Acceptance Criteria

1. THE API SHALL expose `POST /v1/jobs/{id}/chat` accepting a JSON body with `message` (string, required) and `history` (array of prior message objects, optional) and returning a chat response with `reply` (string), `action_buttons` (array of button objects, optional), and `pending_schema_id` (string, optional)
2. THE API SHALL expose `POST /v1/jobs/{id}/reextract-table` accepting a JSON body with `table_id` (string, optional — if omitted, re-extracts all tables) and returning updated table data and a `pending_schema_id`
3. THE API SHALL expose `POST /v1/jobs/{id}/approve-schema` accepting a JSON body with `pending_schema_id` (string, required) and returning a confirmation that the schema has been moved from pending to approved
4. THE `POST /v1/jobs/{id}/chat` endpoint SHALL require the same tenant authentication as all other protected routes
5. THE `POST /v1/jobs/{id}/reextract-table` endpoint SHALL require the same tenant authentication as all other protected routes
6. THE `POST /v1/jobs/{id}/approve-schema` endpoint SHALL require the same tenant authentication as all other protected routes
7. IF the job_id does not exist for the authenticated tenant, THEN all three endpoints SHALL return HTTP 404
8. THE `POST /v1/jobs/{id}/chat` endpoint SHALL return HTTP 400 with a descriptive error if `message` is empty or missing

### Requirement 4: Document-Scoped Chat System Prompt

**User Story:** As a reconciliation operator, I want the chat LLM to have full context about the current document's extraction results, so that it can give accurate, relevant answers about the specific data extracted from that document.

#### Acceptance Criteria

1. WHEN a chat request is received, THE System_Prompt SHALL be generated dynamically from the current job's result data and SHALL include: filename, schema type, list of extracted field names and their values, count of abstentions, and a summary of each extracted table (table_id, type, row count, column headers)
2. THE System_Prompt SHALL include a strict instruction: "You are a document extraction assistant. You may ONLY answer questions about the document '[filename]'. Do not answer questions about other documents, general finance, or any topic unrelated to this document's extracted data."
3. THE System_Prompt SHALL include an instruction: "Never execute code, access external systems, or perform actions outside of explaining extraction results and offering re-extraction options."
4. THE System_Prompt SHALL be constructed server-side in the `POST /v1/jobs/{id}/chat` handler and SHALL never be sent to or modifiable by the client
5. THE System_Prompt SHALL include the full conversation history passed in the `history` parameter so the LLM has context for follow-up questions

### Requirement 5: Chat Guardrails and Off-Topic Rejection

**User Story:** As a system operator, I want the chat interface to reject questions unrelated to the current document, so that the LLM cannot be used as a general-purpose assistant or prompted to perform unintended actions.

#### Acceptance Criteria

1. WHEN the LLM determines a user message is not about the current document's extracted data, THE Chat_Panel SHALL display the fixed response: "I can only help with questions about [filename]. Please ask about the extracted fields or tables."
2. THE guardrail check SHALL be performed by the LLM itself using the System_Prompt scoping instruction, not by a separate keyword filter
3. WHEN the user asks about a specific table or field that exists in the extraction result, THE LLM SHALL answer using the data from the System_Prompt context
4. THE chat endpoint SHALL never return raw LLM output that includes code blocks intended for execution, file paths, or references to external systems

### Requirement 6: Chat Action Buttons and Re-extraction Flow

**User Story:** As a reconciliation operator, I want the chat to present clickable action options after identifying a problem, so that I can trigger re-extraction directly from the conversation without navigating away.

#### Acceptance Criteria

1. WHEN the LLM identifies a data quality problem in its response, THE `POST /v1/jobs/{id}/chat` endpoint SHALL include an `action_buttons` array in the response containing at minimum: "Re-extract this table with AI", "Re-extract all tables with AI", "Accept current output", "Ask another question"
2. WHEN the user selects "Re-extract this table with AI", THE Chat_Panel SHALL call `POST /v1/jobs/{id}/reextract-table` with the relevant `table_id` and display the updated table inline in the chat
3. WHEN the user selects "Re-extract all tables with AI", THE Chat_Panel SHALL call `POST /v1/jobs/{id}/reextract-table` without a `table_id` and display a summary of updated tables inline in the chat
4. WHEN the user selects "Accept current output", THE Chat_Panel SHALL close the action buttons and allow the user to continue asking questions
5. WHEN the user selects "Ask another question", THE Chat_Panel SHALL focus the message input field
6. AFTER a re-extraction action completes, THE Chat_Panel SHALL display the Schema_Approval_Banner if the response includes a `pending_schema_id`

### Requirement 7: Chat Panel UI Component

**User Story:** As a reconciliation operator, I want a chat interface integrated into the results viewer, so that I can describe problems and trigger re-extraction without leaving the results screen.

#### Acceptance Criteria

1. THE ResultsViewerScreen SHALL include a "Chat" tab alongside the existing Fields, Tables, Abstentions, and Validation tabs
2. THE Chat_Panel SHALL display a scrollable message history with user messages right-aligned and assistant messages left-aligned
3. THE Chat_Panel SHALL include a text input field and a "Send" button; pressing Enter SHALL also submit the message
4. WHILE a chat response is loading, THE Chat_Panel SHALL display a loading indicator and disable the input field
5. THE Chat_Panel SHALL render Action_Buttons as distinct clickable button elements below the assistant message that triggered them
6. THE Chat_Panel SHALL preserve conversation history within the current browser session for the current job; navigating away and returning SHALL restore the conversation
7. WHEN the Chat_Panel is first opened for a job, THE Chat_Panel SHALL display a welcome message: "I can help you review the extraction results for [filename]. Describe any issues you see with the extracted fields or tables."

### Requirement 8: Pending Schema State

**User Story:** As a reconciliation operator, I want newly discovered schemas to require my explicit approval before being saved, so that low-quality or incorrect schemas are not automatically used for future documents.

#### Acceptance Criteria

1. WHEN LLM extraction completes (from auto-escalation or chat re-extract), THE Pipeline SHALL store the discovered schema in a "pending" state identified by a unique `pending_schema_id` (UUID)
2. THE Pending_Schema SHALL be stored separately from the approved SchemaCache and SHALL NOT be returned by `SchemaCache.lookup()`
3. THE Pending_Schema SHALL be associated with the job_id and tenant_id that produced it
4. WHEN a Pending_Schema is discarded (user rejects or ignores the banner), THE Pipeline SHALL delete the pending entry and log `schema_cache.pending_discarded`
5. THE Pending_Schema store SHALL automatically expire pending entries after 24 hours if neither approved nor explicitly rejected
6. THE Pipeline SHALL never use a Pending_Schema for fast re-extraction on future document submissions; only Approved_Schemas SHALL be used

### Requirement 9: Schema Approval Banner

**User Story:** As a reconciliation operator, I want a clear prompt to accept or discard a newly discovered schema after LLM extraction, so that I can control which schemas are persisted for future use.

#### Acceptance Criteria

1. WHEN a job result contains `llm_escalated: true` or a chat re-extraction returns a `pending_schema_id`, THE ResultsViewerScreen SHALL display the Schema_Approval_Banner
2. THE Schema_Approval_Banner SHALL display: the schema type label, the institution name (if detected), the number of fields and tables in the schema, and two buttons: "Accept & Save Schema" and "Discard"
3. WHEN the user clicks "Accept & Save Schema", THE frontend SHALL call `POST /v1/jobs/{id}/approve-schema` with the `pending_schema_id` and, on success, hide the banner and show a confirmation toast
4. WHEN the user clicks "Discard", THE frontend SHALL call `POST /v1/jobs/{id}/approve-schema` with a `rejected: true` flag (or omit the call and let the 24-hour expiry handle cleanup), and hide the banner
5. THE Schema_Approval_Banner SHALL be dismissible; dismissing without clicking either button SHALL be treated as "Discard"
6. THE Schema_Approval_Banner SHALL only be shown once per job per browser session; if the user has already acted on it, it SHALL NOT reappear on page refresh

### Requirement 10: Approved Schema Fast Re-extraction

**User Story:** As a reconciliation operator, I want previously approved schemas to be used automatically on future submissions of the same document type, so that re-extraction is faster and cheaper for known document formats.

#### Acceptance Criteria

1. WHEN a document is submitted and the SchemaCache contains an Approved_Schema matching the document's fingerprint (institution + document_type_label), THE Pipeline SHALL use the Approved_Schema for extraction without triggering full LLM discovery
2. WHEN an Approved_Schema is used for extraction, THE Pipeline SHALL log `schema_cache.approved_hit` with the fingerprint key and usage count
3. THE `POST /v1/jobs/{id}/approve-schema` endpoint SHALL move the Pending_Schema to the approved SchemaCache by calling `SchemaCache.store()` with the schema and fingerprint
4. WHEN `SchemaCache.store()` is called via the approve endpoint, THE SchemaCache SHALL set an `approved: true` flag on the entry to distinguish it from any auto-saved entries
5. THE SchemaCache.lookup() method SHALL only return schemas with `approved: true`; schemas without this flag SHALL be treated as cache misses

### Requirement 11: Quality Scorer Observability

**User Story:** As a system operator, I want quality scoring decisions logged with full detail, so that I can monitor escalation rates and tune thresholds over time.

#### Acceptance Criteria

1. WHEN the Quality_Scorer runs, THE Pipeline SHALL emit a structured log event `quality_scorer.result` containing: job_id, overall verdict, list of failed checks, and per-check metric values
2. WHEN LLM_Escalation is triggered, THE Pipeline SHALL emit `quality_scorer.escalated` with job_id, failed_checks, and the count of text-parser tables discarded
3. WHEN LLM_Escalation is skipped because `vlm_enabled` is False, THE Pipeline SHALL emit `quality_scorer.escalation_skipped` with reason "vlm_disabled"
4. THE quality scoring log events SHALL use the same structlog JSON format as all other pipeline log events
5. THE `quality_scorer.result` event SHALL include a `duration_ms` field recording how long the scoring took

### Requirement 12: Re-extraction Result Validation

**User Story:** As a reconciliation operator, I want re-extracted tables validated before being shown to me, so that LLM re-extraction does not silently produce worse output than the original.

#### Acceptance Criteria

1. WHEN `POST /v1/jobs/{id}/reextract-table` completes, THE Pipeline SHALL run the existing Validator on the new table data before returning it to the frontend
2. IF the re-extracted table fails validation, THEN THE API SHALL include a `validation_warnings` array in the response listing the failures, but SHALL still return the table data
3. WHEN re-extraction produces a table with zero rows, THE API SHALL include a warning in the response: "Re-extraction produced an empty table. The original data has been retained."
4. WHEN re-extraction produces a table with fewer rows than the original, THE API SHALL include a warning: "Re-extraction produced [N] rows vs [M] original rows. Review before accepting."
