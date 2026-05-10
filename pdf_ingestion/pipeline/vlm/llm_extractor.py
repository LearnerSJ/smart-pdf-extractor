"""LLM-based full document extraction.

Uses a two-phase approach to avoid output token limits:
1. Metadata call: extracts document type, institution, client, dates, account
   numbers, and balances (small output, always fits)
2. Transaction calls: extracts tabular data per-page or per-window (each call
   handles a small batch, output always fits)

This handles ANY bank/custody format without pre-written regex patterns.
"""

from __future__ import annotations

import asyncio
import json

import structlog

from api.errors import ErrorCode
from pipeline.models import VLMFieldResult
from pipeline.ports import VLMClientPort

logger = structlog.get_logger()


# ─── Phase 1: Metadata Extraction Prompt ──────────────────────────────────────

METADATA_PROMPT = '''You are a financial document parser. Analyze the following document text and extract ONLY the metadata and account structure (NO transactions or table rows).

Document text:
---
{document_text}
---

Extract the following into JSON:
1. "document_type": one of "bank_statement", "custody_statement", "swift_confirm", "multi_account_statement", or "unknown"
2. "statement_date": the statement or valuation date (ISO format YYYY-MM-DD)
3. "period_from": start of statement period (ISO format)
4. "period_to": end of statement period (ISO format)
5. "institution": the bank, custodian, or financial institution issuing the statement (look for logos, letterheads, or "issued by" text)
6. "client_name": the account holder / client / fund name (the entity the statement is FOR, not the institution)
7. "accounts": array of accounts found, each with ONLY:
   - "account_number": the primary account identifier (look for codes like IBAN, account numbers, fund codes, or identifiers after "Account:" or in headers)
   - "iban": IBAN if present
   - "currency": 3-letter currency code
   - "account_type": "capital", "income", or "current"
   - "opening_balance": the FIRST balance shown at the very start of the statement period (the initial/brought-forward balance before any transactions)
   - "closing_balance": the LAST/FINAL balance shown at the end of the statement (often on the last page, in a "Total:" line or final balance column)
   - "has_transactions": true if this account has transaction rows in the document
   - "has_other_tables": true if this account has other tabular data (fees, settlements, etc.)

Rules:
- Do NOT include any transactions or table rows — only metadata
- Use null for fields not found
- For amounts, return as numbers (no currency symbols or commas)
- For dates, use ISO format YYYY-MM-DD
- For opening_balance: use the very first balance value that appears BEFORE any transactions. This is often labeled "Balance brought forward", "Previous balance", "Opening balance", or is simply the first number in the Balance column.
- For closing_balance: use the very last balance or the "Total:" line balance at the end of the document.
- For account_number: use the primary identifier for the account. If the document shows a code like "INUNIKAE" or a number in the header, use that. Do NOT use sub-account names as the account number.
- IMPORTANT: If a single statement has sub-sections or sub-accounts (e.g. "Settlement Account", "Margin Account", "ETD Account") that are all part of the same client's statement, treat the ENTIRE statement as ONE account. The sub-sections are categories within that account, not separate accounts.
- Only create multiple accounts if the document explicitly contains statements for DIFFERENT account holders or DIFFERENT account numbers that are clearly independent.

Respond with ONLY valid JSON, no other text.'''


# ─── Phase 2: Transaction Extraction Prompt ───────────────────────────────────

TRANSACTIONS_PROMPT = '''You are a financial document parser. Extract ALL tabular data from this document section exactly as it appears.

Document text (pages {start_page}-{end_page}):
---
{page_text}
---

Extract into JSON:
"tables": an array of ALL tables found on these pages. Each table is an object with:
  - "table_type": descriptive name based on the table's content (e.g. "transactions", "holdings", "settlements", "fees", "positions", "cash_movements")
  - "headers": array of ALL column header names exactly as they appear in the document (preserve every column)
  - "rows": array of row objects where keys match the headers exactly. Include EVERY row, even if values are zero or empty.

Rules:
- Preserve ALL columns from the original table — do not drop, rename, or merge columns
- Include EVERY row — do not skip rows even if amounts are zero
- Use the exact column headers as they appear in the document
- If a cell is empty, use null
- For amounts, return as numbers (no currency symbols or commas)
- For dates, use ISO format YYYY-MM-DD where possible
- If multiple tables with different structures exist on these pages, return each as a separate entry in the array
- If no tables found, return {{"tables": []}}

Respond with ONLY valid JSON, no other text.'''


async def extract_document_with_llm(
    document_text: str,
    vlm_client: VLMClientPort,
    schema_type_hint: str | None = None,
    page_texts: list[str] | None = None,
) -> dict:
    """Extract all fields from document text using two-phase LLM calls.

    Phase 1: Single call for metadata (document type, accounts, balances)
    Phase 2: Per-page calls for transactions and tables (parallel)

    This ensures output never exceeds token limits regardless of document size.

    Args:
        document_text: Full text content of the document.
        vlm_client: VLM client port implementation.
        schema_type_hint: Optional hint for the expected document type.
        page_texts: Optional list of per-page text for windowed transaction extraction.

    Returns:
        A dict with document_type, accounts (including transactions), etc.
        If the LLM call fails, returns an error dict with "error" key.
    """
    logger.info(
        "llm_extractor.invoked",
        text_length=len(document_text),
        schema_type_hint=schema_type_hint,
    )

    # ── Phase 1: Extract metadata ────────────────────────────────────────────
    metadata = await _extract_metadata(document_text, vlm_client, schema_type_hint)
    if "error" in metadata:
        return metadata

    # ── Phase 2: Extract transactions per-window ─────────────────────────────
    # Determine pages to process
    if page_texts and len(page_texts) > 0:
        pages = page_texts
    else:
        # Split document_text into rough pages (by double newline or page markers)
        pages = [document_text]

    # Process pages in adaptive windows
    # Small docs (< 20 pages): 3 pages per window (detailed extraction)
    # Large docs (>= 20 pages): 5 pages per window (balance between calls and timeout)
    if len(pages) >= 20:
        window_size = 5
    else:
        window_size = 3
    windows: list[tuple[int, int, str]] = []
    for i in range(0, len(pages), window_size):
        window_pages = pages[i:i + window_size]
        window_text = "\n\n".join(window_pages)
        windows.append((i + 1, min(i + window_size, len(pages)), window_text))

    # Run transaction extraction in parallel
    txn_tasks = [
        _extract_transactions(start, end, text, vlm_client, schema_type_hint)
        for start, end, text in windows
    ]
    txn_results = await asyncio.gather(*txn_tasks)

    # ── Assemble: merge tables into accounts ────────────────────────────────
    all_tables: list[dict] = []

    for result in txn_results:
        if result and not result.get("error"):
            all_tables.extend(result.get("tables", []))

    # Merge tables with identical headers (same schema from different windows)
    merged_tables: list[dict] = []
    for tbl in all_tables:
        if not isinstance(tbl, dict):
            continue
        headers = tbl.get("headers", [])
        rows = tbl.get("rows", [])
        table_type = tbl.get("table_type", "")

        # Find existing table with same headers
        merged = False
        for existing in merged_tables:
            if existing.get("headers") == headers:
                existing_rows = existing.get("rows", [])
                existing["rows"] = existing_rows + rows
                merged = True
                break

        if not merged:
            merged_tables.append(dict(tbl))

    # Attach tables to accounts
    accounts = metadata.get("accounts", [])
    if accounts:
        target_account = None
        for acct in accounts:
            if acct.get("has_transactions") or acct.get("has_other_tables"):
                target_account = acct
                break
        if target_account is None:
            target_account = accounts[0]

        existing_tables = target_account.get("tables", []) or []
        target_account["tables"] = existing_tables + merged_tables

        # Clean up helper flags
        for acct in accounts:
            acct.pop("has_transactions", None)
            acct.pop("has_other_tables", None)

    metadata["accounts"] = accounts

    logger.info(
        "llm_extractor.success",
        document_type=metadata.get("document_type"),
        num_accounts=len(accounts),
        total_transactions=0,
        total_tables=len(merged_tables),
    )

    return metadata


async def _extract_metadata(
    document_text: str,
    vlm_client: VLMClientPort,
    schema_type_hint: str | None,
) -> dict:
    """Phase 1: Extract document metadata and account structure.

    For large documents, only sends the first and last pages to avoid
    exceeding input token limits. Metadata (institution, client, dates,
    account numbers, balances) is always on the first/last pages.
    """
    # Truncate for large documents: first 5000 chars + last 3000 chars
    if len(document_text) > 15000:
        truncated = document_text[:8000] + "\n\n[... middle pages omitted ...]\n\n" + document_text[-5000:]
    else:
        truncated = document_text

    prompt_text = METADATA_PROMPT.format(document_text=truncated)

    vlm_result: VLMFieldResult = await asyncio.to_thread(
        vlm_client.extract_field,
        prompt_text,
        "metadata_extraction",
        "Extract document metadata and account structure",
        schema_type_hint or "auto",
    )

    if vlm_result.value is None:
        logger.warning("llm_extractor.metadata_null")
        return {
            "error": ErrorCode.VLM_RETURNED_NULL,
            "detail": "LLM returned null for metadata extraction",
        }

    raw_value = _strip_markdown_fences(vlm_result.value)

    try:
        parsed = json.loads(raw_value)
    except (json.JSONDecodeError, TypeError) as e:
        repaired = _repair_truncated_json(raw_value)
        if repaired is not None:
            logger.info("llm_extractor.metadata_repaired", error=str(e))
            parsed = repaired
        else:
            logger.warning("llm_extractor.metadata_parse_error", error=str(e))
            return {
                "error": ErrorCode.VLM_PARSE_ERROR,
                "detail": f"Failed to parse metadata JSON: {e}",
            }

    # Unwrap {"value": {...}} envelope if present (VLM client prompt adds this)
    if "value" in parsed and isinstance(parsed["value"], dict):
        parsed = parsed["value"]

    return parsed


async def _extract_transactions(
    start_page: int,
    end_page: int,
    page_text: str,
    vlm_client: VLMClientPort,
    schema_type_hint: str | None,
) -> dict:
    """Phase 2: Extract transactions and tables from a page window."""
    if not page_text.strip():
        return {"transactions": [], "tables": []}

    prompt_text = TRANSACTIONS_PROMPT.format(
        start_page=start_page,
        end_page=end_page,
        page_text=page_text,
    )

    try:
        vlm_result: VLMFieldResult = await asyncio.to_thread(
            vlm_client.extract_field,
            prompt_text,
            "transaction_extraction",
            f"Extract transactions from pages {start_page}-{end_page}",
            schema_type_hint or "auto",
        )
    except Exception as exc:
        logger.warning(
            "llm_extractor.txn_window_failed",
            start_page=start_page,
            end_page=end_page,
            error=str(exc),
        )
        return {"transactions": [], "tables": []}

    if vlm_result.value is None:
        return {"transactions": [], "tables": []}

    raw_value = _strip_markdown_fences(vlm_result.value)

    try:
        parsed = json.loads(raw_value)
    except (json.JSONDecodeError, TypeError) as e:
        repaired = _repair_truncated_json(raw_value)
        if repaired is not None:
            parsed = repaired
        else:
            logger.warning(
                "llm_extractor.txn_parse_error",
                start_page=start_page,
                error=str(e),
            )
            return {"transactions": [], "tables": []}

    # Unwrap {"value": {...}} envelope if present
    if "value" in parsed and isinstance(parsed["value"], dict):
        parsed = parsed["value"]

    return {
        "transactions": [],
        "tables": parsed.get("tables", []),
    }


def _strip_markdown_fences(value: str) -> str:
    """Remove ```json ... ``` wrapper from LLM response."""
    raw = value.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)
    # Strip any trailing text after the JSON object closes
    # (LLM sometimes adds explanatory text after the JSON)
    raw = raw.strip()
    if raw.startswith("{"):
        # Find the matching closing brace
        depth = 0
        for i, ch in enumerate(raw):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    raw = raw[:i + 1]
                    break
    return raw


def _repair_truncated_json(raw: str) -> dict | None:
    """Attempt to repair truncated JSON by closing open brackets/braces.

    When the LLM hits its output token limit, the JSON gets cut off mid-stream.
    This function tries to salvage the valid portion by:
    1. Removing the last incomplete value/key
    2. Closing all open brackets and braces

    Returns parsed dict if repair succeeds, None otherwise.
    """
    if not raw:
        return None

    # Try progressively shorter substrings
    for trim in range(0, min(500, len(raw)), 10):
        attempt = raw[:len(raw) - trim] if trim > 0 else raw

        # Count open/close brackets
        open_braces = attempt.count("{") - attempt.count("}")
        open_brackets = attempt.count("[") - attempt.count("]")

        if open_braces < 0 or open_brackets < 0:
            continue

        # Remove trailing comma or incomplete key/value
        attempt = attempt.rstrip()
        while attempt and attempt[-1] in (",", ":", '"', " ", "\n"):
            attempt = attempt[:-1].rstrip()

        # If we end mid-string, try to close it
        if attempt.count('"') % 2 != 0:
            attempt += '"'

        # Remove trailing comma after fixing quotes
        attempt = attempt.rstrip().rstrip(",")

        # Close open brackets and braces
        attempt += "]" * open_brackets
        attempt += "}" * open_braces

        try:
            parsed = json.loads(attempt)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            continue

    return None
