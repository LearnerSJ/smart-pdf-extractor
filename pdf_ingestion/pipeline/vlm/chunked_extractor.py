"""Chunked VLM extraction for large documents.

Splits documents that exceed the model's context window into page-level
windows and processes them using a tiered strategy:

- Single: Document fits in one call (no chunking needed)
- Tier 1: Only header/balance fields abstained — send targeted pages
- Tier 2: Full extraction needed, <80 pages — sliding window with overlap
- Tier 3: Full extraction needed, >=80 pages — two-pass summarize-then-extract

All tier functions are async because they call the VLM client via asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Callable

import structlog

from api.errors import ErrorCode
from pipeline.models import VLMFieldResult
from pipeline.ports import VLMClientPort
from pipeline.vlm.response_parser import strip_markdown_fences
from pipeline.vlm.token_budget import TokenBudget
from pipeline.vlm.usage_events import (
    VLMJobUsageSummary,
    VLMUsageEvent,
    emit_job_usage_summary,
    emit_window_usage,
)

logger = structlog.get_logger()


# ─── Constants ────────────────────────────────────────────────────────────────

HEADER_FIELDS: set[str] = {
    "institution",
    "client_name",
    "statement_date",
    "period_from",
    "period_to",
    "account_number",
    "iban",
    "opening_balance",
    "closing_balance",
    "currency",
}

# Maps field names to (start_strategy, end_strategy) where strategies indicate
# which pages are most likely to contain the field.
# Strategies: "first", "2", "3", "last", "last_2"
FIELD_PAGE_MAPPING: dict[str, tuple[str, str]] = {
    "institution": ("first", "first"),
    "client_name": ("first", "first"),
    "statement_date": ("first", "2"),
    "period_from": ("first", "2"),
    "period_to": ("first", "2"),
    "account_number": ("first", "2"),
    "iban": ("first", "2"),
    "opening_balance": ("first", "3"),
    "closing_balance": ("last_2", "last"),
    "currency": ("first", "3"),
}

CONTEXT_THRESHOLD_RATIO = 0.80  # 80% of max context tokens

PAGE_SUMMARY_PROMPT = """Analyze this single page from a financial document and identify which fields are present.

Page text:
---
{page_text}
---

Return a JSON object with:
- "has_header": true if page contains institution name, client name, or statement date
- "has_opening_balance": true if page contains opening/brought-forward balance
- "has_closing_balance": true if page contains closing/carried-forward balance
- "has_transactions": true if page contains transaction entries
- "has_account_info": true if page contains account number, IBAN, or currency
- "field_names": list of specific field names found on this page

Respond with ONLY valid JSON."""



# ─── Data Classes ─────────────────────────────────────────────────────────────


@dataclass
class PageWindow:
    """A contiguous range of pages sent in a single LLM call.

    Pages are 1-indexed and end_page is inclusive.
    """

    start_page: int  # 1-indexed
    end_page: int  # inclusive
    target_fields: list[str] = field(default_factory=list)
    page_texts: list[str] = field(default_factory=list)

    @property
    def num_pages(self) -> int:
        """Number of pages in this window."""
        return self.end_page - self.start_page + 1


@dataclass
class WindowConfig:
    """Configuration for sliding window extraction."""

    window_size: int = 12
    overlap: int = 3
    max_concurrent: int = 3


@dataclass
class TransactionKey:
    """Composite key for transaction deduplication in overlap regions.

    Uses (date, description, abs(amount)) to identify duplicate transactions
    that appear in overlapping windows.
    """

    date: str
    description: str
    amount: float

    def __hash__(self) -> int:
        return hash((self.date, self.description, self.amount))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TransactionKey):
            return NotImplemented
        return (
            self.date == other.date
            and self.description == other.description
            and self.amount == other.amount
        )


# ─── Tier Selection (Task 9.5) ───────────────────────────────────────────────


def select_extraction_tier(
    page_texts: list[str],
    abstained_fields: list[str],
    vlm_client: VLMClientPort,
) -> str:
    """Select the appropriate extraction tier based on document size and needs.

    Decision matrix:
    1. "single" — full document fits within 80% of context window
    2. "tier1"  — only header/balance fields abstained (targeted pages)
    3. "tier2"  — full extraction needed, document < 80 pages (sliding window)
    4. "tier3"  — full extraction needed, document >= 80 pages (two-pass)

    Args:
        page_texts: List of page text content (one string per page).
        abstained_fields: List of field names that need VLM extraction.
        vlm_client: VLM client port for token estimation.

    Returns:
        One of "single", "tier1", "tier2", "tier3".
    """
    full_text = "\n".join(page_texts)
    estimated_tokens = vlm_client.estimate_tokens(full_text)
    max_tokens = vlm_client.max_context_tokens()
    threshold = int(max_tokens * CONTEXT_THRESHOLD_RATIO)

    # If the full document fits in a single call, no chunking needed
    if estimated_tokens <= threshold:
        return "single"

    # If only header fields are abstained, use targeted page selection
    abstained_set = set(abstained_fields)
    if abstained_set and abstained_set.issubset(HEADER_FIELDS):
        return "tier1"

    # Use sliding window for all large documents regardless of page count.
    # Tier 3's two-pass summarize-then-extract is too slow for 100+ page docs
    # (Pass 1 alone requires one VLM call per page). Sliding window with
    # overlap and deduplication handles large documents efficiently.
    return "tier2"



# ─── Tier 1: Targeted Page Selection (Task 9.6) ──────────────────────────────


def _resolve_page_index(strategy: str, total_pages: int) -> int:
    """Resolve a page strategy string to a 0-based page index.

    Strategies:
        "first" -> 0
        "2"     -> 1
        "3"     -> 2
        "last"  -> total_pages - 1
        "last_2" -> total_pages - 2
    """
    if strategy == "first":
        return 0
    if strategy == "last":
        return total_pages - 1
    if strategy == "last_2":
        return max(0, total_pages - 2)
    # Numeric strategies like "2", "3"
    return min(int(strategy) - 1, total_pages - 1)


def select_target_pages(
    abstained_fields: list[str],
    total_pages: int,
) -> list[PageWindow]:
    """Group abstained fields by target page ranges and create windows.

    Groups fields that share overlapping page ranges into single windows,
    each targeting 2-5 pages. Returns a list of PageWindow objects ready
    for LLM calls.

    Args:
        abstained_fields: Field names that need extraction.
        total_pages: Total number of pages in the document.

    Returns:
        List of PageWindow objects with target page ranges.
    """
    if not abstained_fields or total_pages == 0:
        return []

    # Collect page indices needed for each field
    field_pages: dict[str, set[int]] = {}
    for field_name in abstained_fields:
        mapping = FIELD_PAGE_MAPPING.get(field_name)
        if mapping is None:
            # Unknown field — default to first 3 pages
            field_pages[field_name] = {0, 1, min(2, total_pages - 1)}
            continue

        start_strategy, end_strategy = mapping
        start_idx = _resolve_page_index(start_strategy, total_pages)
        end_idx = _resolve_page_index(end_strategy, total_pages)

        pages = set(range(start_idx, end_idx + 1))
        field_pages[field_name] = pages

    # Group fields by overlapping page sets
    # Simple approach: merge fields whose page sets overlap
    groups: list[tuple[set[int], list[str]]] = []
    for field_name, pages in field_pages.items():
        merged = False
        for group_pages, group_fields in groups:
            if group_pages & pages:  # overlap exists
                group_pages.update(pages)
                group_fields.append(field_name)
                merged = True
                break
        if not merged:
            groups.append((set(pages), [field_name]))

    # Convert groups to PageWindow objects
    windows: list[PageWindow] = []
    for page_set, fields in groups:
        sorted_pages = sorted(page_set)
        # Ensure we send 2-5 contiguous pages
        start = sorted_pages[0]
        end = sorted_pages[-1]
        # Expand to at least 2 pages if only 1
        if end - start < 1 and end + 1 < total_pages:
            end = start + 1
        # Cap at 5 pages
        if end - start >= 5:
            end = start + 4

        windows.append(
            PageWindow(
                start_page=start + 1,  # Convert to 1-indexed
                end_page=end + 1,  # Convert to 1-indexed, inclusive
                target_fields=fields,
            )
        )

    return windows


async def _extract_tier1(
    page_texts: list[str],
    abstained_fields: list[str],
    vlm_client: VLMClientPort,
    token_budget: TokenBudget,
    schema_type: str,
    job_id: str,
    tenant_id: str,
) -> dict:
    """Execute Tier 1 extraction — targeted page selection.

    Sends only the 2-5 pages most likely to contain the abstained header fields.
    """
    total_pages = len(page_texts)
    windows = select_target_pages(abstained_fields, total_pages)

    results: dict = {}
    for i, window in enumerate(windows):
        if not token_budget.can_proceed():
            logger.warning(
                "vlm.budget_exceeded",
                tier="tier1",
                job_id=job_id,
                action=token_budget.budget_exceeded_action,
            )
            break

        # Gather page texts for this window
        window_text = "\n\n".join(
            page_texts[p - 1]
            for p in range(window.start_page, window.end_page + 1)
            if p - 1 < len(page_texts)
        )

        prompt = (
            f"Extract the following fields from this document excerpt: "
            f"{', '.join(window.target_fields)}\n\n"
            f"Document text:\n---\n{window_text}\n---\n\n"
            f"Return a JSON object with field names as keys and extracted values. "
            f"Use null for fields not found."
        )

        input_tokens = vlm_client.estimate_tokens(prompt)

        vlm_result: VLMFieldResult = await asyncio.to_thread(
            vlm_client.extract_field,
            prompt,
            "chunked_extraction",
            f"Extract fields: {', '.join(window.target_fields)}",
            schema_type,
        )

        output_tokens = vlm_client.estimate_tokens(vlm_result.raw_response)
        token_budget.record_usage(input_tokens, output_tokens)

        emit_window_usage(
            VLMUsageEvent(
                tenant_id=tenant_id,
                job_id=job_id,
                schema_type=schema_type,
                model_id=vlm_result.model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                tier="tier1",
                window_index=i,
                window_start_page=window.start_page,
                window_end_page=window.end_page,
                target_fields=window.target_fields,
            )
        )

        if vlm_result.value:
            try:
                parsed = json.loads(strip_markdown_fences(vlm_result.value))
                results.update(parsed)
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "vlm.window_failed",
                    tier="tier1",
                    window_index=i,
                    error="parse_error",
                )

    return results



# ─── Tier 2: Sliding Window with Overlap (Task 9.7) ──────────────────────────


def create_sliding_windows(
    page_texts: list[str],
    config: WindowConfig,
) -> list[PageWindow]:
    """Create overlapping page windows for sliding window extraction.

    Windows are page-aligned (never split mid-page) with configurable overlap
    between adjacent windows.

    Args:
        page_texts: List of page text content (one string per page).
        config: Window configuration (size, overlap, max_concurrent).

    Returns:
        List of PageWindow objects covering all pages.
    """
    total_pages = len(page_texts)
    if total_pages == 0:
        return []

    windows: list[PageWindow] = []
    step = config.window_size - config.overlap  # Advance by window_size - overlap

    if step <= 0:
        step = 1  # Safety: ensure forward progress

    start = 0
    while start < total_pages:
        end = min(start + config.window_size - 1, total_pages - 1)
        window = PageWindow(
            start_page=start + 1,  # 1-indexed
            end_page=end + 1,  # 1-indexed, inclusive
            page_texts=page_texts[start : end + 1],
        )
        windows.append(window)

        # If we've reached the end, stop
        if end >= total_pages - 1:
            break

        start += step

    return windows


async def _process_window(
    window: PageWindow,
    window_index: int,
    vlm_client: VLMClientPort,
    token_budget: TokenBudget,
    schema_type: str,
    job_id: str,
    tenant_id: str,
    semaphore: asyncio.Semaphore,
    on_window_complete: Callable[[], None] | None = None,
) -> dict | None:
    """Process a single window through the VLM client.

    Returns parsed extraction result or None if the window fails.
    """
    async with semaphore:
        if not token_budget.can_proceed():
            logger.warning(
                "vlm.budget_exceeded",
                tier="tier2",
                window_index=window_index,
                job_id=job_id,
                action=token_budget.budget_exceeded_action,
            )
            return None

        window_text = "\n\n".join(window.page_texts)
        prompt = (
            f"Extract all financial data from this document section "
            f"(pages {window.start_page}-{window.end_page}).\n\n"
            f"Document text:\n---\n{window_text}\n---\n\n"
            f"Return a JSON object with:\n"
            f'- "header_fields": object with institution, client_name, '
            f"statement_date, period_from, period_to, account_number, iban, "
            f"opening_balance, closing_balance, currency\n"
            f'- "transactions": array of objects with date, description, '
            f"debit, credit, balance\n\n"
            f"Use null for fields not found. Respond with ONLY valid JSON."
        )

        input_tokens = vlm_client.estimate_tokens(prompt)

        try:
            vlm_result: VLMFieldResult = await asyncio.to_thread(
                vlm_client.extract_field,
                prompt,
                "chunked_extraction",
                f"Extract pages {window.start_page}-{window.end_page}",
                schema_type,
            )
        except Exception as exc:
            logger.warning(
                "vlm.window_failed",
                tier="tier2",
                window_index=window_index,
                error=str(exc),
            )
            return None

        output_tokens = vlm_client.estimate_tokens(vlm_result.raw_response)
        token_budget.record_usage(input_tokens, output_tokens)

        emit_window_usage(
            VLMUsageEvent(
                tenant_id=tenant_id,
                job_id=job_id,
                schema_type=schema_type,
                model_id=vlm_result.model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                tier="tier2",
                window_index=window_index,
                window_start_page=window.start_page,
                window_end_page=window.end_page,
            )
        )

        if on_window_complete:
            on_window_complete()

        if vlm_result.value is None:
            return None

        try:
            return json.loads(strip_markdown_fences(vlm_result.value))
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "vlm.window_failed",
                tier="tier2",
                window_index=window_index,
                error="parse_error",
            )
            return None


async def _extract_tier2(
    page_texts: list[str],
    vlm_client: VLMClientPort,
    token_budget: TokenBudget,
    config: WindowConfig,
    schema_type: str,
    job_id: str,
    tenant_id: str,
    on_window_complete: Callable[[], None] | None = None,
) -> dict:
    """Execute Tier 2 extraction — sliding window with overlap.

    Creates overlapping windows and processes them in parallel with
    rate limiting via asyncio.Semaphore.
    """
    windows = create_sliding_windows(page_texts, config)
    semaphore = asyncio.Semaphore(config.max_concurrent)

    tasks = [
        _process_window(
            window=w,
            window_index=i,
            vlm_client=vlm_client,
            token_budget=token_budget,
            schema_type=schema_type,
            job_id=job_id,
            tenant_id=tenant_id,
            semaphore=semaphore,
            on_window_complete=on_window_complete,
        )
        for i, w in enumerate(windows)
    ]

    results = await asyncio.gather(*tasks)
    window_results = [r for r in results if r is not None]

    return merge_window_results(window_results)



# ─── Result Merging and Deduplication (Task 9.8) ─────────────────────────────


def _make_transaction_key(txn: dict) -> TransactionKey:
    """Create a composite key for transaction deduplication.

    Uses (date, description, abs(amount)) where amount is the absolute
    value of debit or credit.
    """
    date = txn.get("date", "")
    description = txn.get("description", "")
    debit = txn.get("debit")
    credit = txn.get("credit")

    # Use whichever amount is present (debit or credit)
    amount = 0.0
    if debit is not None:
        try:
            amount = abs(float(debit))
        except (ValueError, TypeError):
            pass
    elif credit is not None:
        try:
            amount = abs(float(credit))
        except (ValueError, TypeError):
            pass

    return TransactionKey(date=date, description=description, amount=amount)


def merge_window_results(window_results: list[dict]) -> dict:
    """Merge extraction results from multiple windows.

    Merge strategy:
    - Header fields: taken from the first window (statement metadata on pages 1-2)
    - Closing balance: taken from the last window
    - Transactions: concatenated and deduplicated by composite key

    Args:
        window_results: List of parsed extraction results from each window.

    Returns:
        Merged extraction result dict.
    """
    if not window_results:
        return {}

    if len(window_results) == 1:
        return window_results[0]

    merged: dict = {}

    # Header fields from first window
    first_result = window_results[0]
    first_headers = first_result.get("header_fields", {})
    if first_headers:
        merged["header_fields"] = dict(first_headers)
    else:
        # If no header_fields key, copy all non-transaction fields from first
        merged["header_fields"] = {
            k: v
            for k, v in first_result.items()
            if k != "transactions" and k != "header_fields"
        }

    # Closing balance from last window
    last_result = window_results[-1]
    last_headers = last_result.get("header_fields", {})
    if last_headers and last_headers.get("closing_balance") is not None:
        if "header_fields" not in merged:
            merged["header_fields"] = {}
        merged["header_fields"]["closing_balance"] = last_headers["closing_balance"]
    elif last_result.get("closing_balance") is not None:
        if "header_fields" not in merged:
            merged["header_fields"] = {}
        merged["header_fields"]["closing_balance"] = last_result["closing_balance"]

    # Deduplicate transactions across windows
    seen_keys: set[TransactionKey] = set()
    merged_transactions: list[dict] = []

    for result in window_results:
        transactions = result.get("transactions", [])
        for txn in transactions:
            key = _make_transaction_key(txn)
            # Never dedup zero-amount transactions — they're distinct line items
            if key.amount == 0.0:
                merged_transactions.append(txn)
            elif key not in seen_keys:
                seen_keys.add(key)
                merged_transactions.append(txn)
            else:
                logger.debug(
                    "vlm.dedup_applied",
                    date=key.date,
                    description=key.description,
                    amount=key.amount,
                )

    merged["transactions"] = merged_transactions

    return merged



# ─── Tier 3: Two-Pass Summarize-then-Extract (Task 9.9) ──────────────────────


def _identify_relevant_pages(page_summaries: list[dict]) -> list[int]:
    """Identify pages containing target fields from page summaries.

    Selects pages that contain header info, balances, account info,
    or transactions for Pass 2 extraction.

    Args:
        page_summaries: List of parsed summary dicts (one per page).

    Returns:
        Sorted list of 0-based page indices to include in Pass 2.
    """
    relevant: set[int] = set()

    for i, summary in enumerate(page_summaries):
        if not summary:
            continue
        # Include pages with any meaningful content
        if summary.get("has_header"):
            relevant.add(i)
        if summary.get("has_opening_balance"):
            relevant.add(i)
        if summary.get("has_closing_balance"):
            relevant.add(i)
        if summary.get("has_account_info"):
            relevant.add(i)
        if summary.get("has_transactions"):
            relevant.add(i)
        if summary.get("field_names"):
            relevant.add(i)

    return sorted(relevant)


async def _summarize_page(
    page_index: int,
    page_text: str,
    vlm_client: VLMClientPort,
    token_budget: TokenBudget,
    schema_type: str,
    job_id: str,
    tenant_id: str,
    semaphore: asyncio.Semaphore,
) -> tuple[int, dict]:
    """Summarize a single page for Pass 1 of Tier 3.

    Returns (page_index, summary_dict) tuple.
    """
    async with semaphore:
        if not token_budget.can_proceed():
            return page_index, {}

        prompt = PAGE_SUMMARY_PROMPT.format(page_text=page_text)
        input_tokens = vlm_client.estimate_tokens(prompt)

        try:
            vlm_result: VLMFieldResult = await asyncio.to_thread(
                vlm_client.extract_field,
                prompt,
                "page_summary",
                f"Summarize page {page_index + 1}",
                schema_type,
            )
        except Exception as exc:
            logger.warning(
                "vlm.window_failed",
                tier="tier3",
                pass_num=1,
                page_index=page_index,
                error=str(exc),
            )
            return page_index, {}

        output_tokens = vlm_client.estimate_tokens(vlm_result.raw_response)
        token_budget.record_usage(input_tokens, output_tokens)

        emit_window_usage(
            VLMUsageEvent(
                tenant_id=tenant_id,
                job_id=job_id,
                schema_type=schema_type,
                model_id=vlm_result.model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                tier="tier3",
                window_index=page_index,
                window_start_page=page_index + 1,
                window_end_page=page_index + 1,
                target_fields=["page_summary"],
            )
        )

        if vlm_result.value is None:
            return page_index, {}

        try:
            parsed = json.loads(strip_markdown_fences(vlm_result.value))
            return page_index, parsed
        except (json.JSONDecodeError, TypeError):
            return page_index, {}


async def _extract_tier3(
    page_texts: list[str],
    vlm_client: VLMClientPort,
    token_budget: TokenBudget,
    config: WindowConfig,
    schema_type: str,
    job_id: str,
    tenant_id: str,
) -> dict:
    """Execute Tier 3 extraction — two-pass summarize-then-extract.

    Pass 1: Send each page individually for a lightweight structured summary.
    Pass 2: Apply sliding-window extraction over the relevant pages identified
            in Pass 1, then merge results using the same deduplication logic
            as Tier 2.
    """
    semaphore = asyncio.Semaphore(config.max_concurrent)

    # ── Pass 1: Summarize each page ──────────────────────────────────────────
    logger.info("vlm.tier3_pass1_start", job_id=job_id, total_pages=len(page_texts))

    summary_tasks = [
        _summarize_page(
            page_index=i,
            page_text=text,
            vlm_client=vlm_client,
            token_budget=token_budget,
            schema_type=schema_type,
            job_id=job_id,
            tenant_id=tenant_id,
            semaphore=semaphore,
        )
        for i, text in enumerate(page_texts)
    ]

    summary_results = await asyncio.gather(*summary_tasks)
    page_summaries: list[dict] = [{}] * len(page_texts)
    for page_idx, summary in summary_results:
        page_summaries[page_idx] = summary

    # ── Identify relevant pages for Pass 2 ───────────────────────────────────
    relevant_pages = _identify_relevant_pages(page_summaries)

    if not relevant_pages:
        logger.warning("vlm.tier3_no_relevant_pages", job_id=job_id)
        return {}

    logger.info(
        "vlm.tier3_pass2_start",
        job_id=job_id,
        relevant_pages=len(relevant_pages),
        total_pages=len(page_texts),
    )

    # ── Pass 2: Sliding-window extraction over relevant pages ────────────────
    # Build a subset of page texts containing only the relevant pages
    relevant_page_texts = [page_texts[idx] for idx in relevant_pages]

    # Check if the relevant pages fit in a single call
    relevant_full_text = "\n".join(relevant_page_texts)
    estimated_tokens = vlm_client.estimate_tokens(relevant_full_text)
    max_tokens = vlm_client.max_context_tokens()
    threshold = int(max_tokens * CONTEXT_THRESHOLD_RATIO)

    if estimated_tokens <= threshold:
        # Relevant pages fit in one call — send them directly
        result = await _tier3_pass2_single(
            relevant_pages=relevant_pages,
            page_texts=page_texts,
            page_summaries=page_summaries,
            vlm_client=vlm_client,
            token_budget=token_budget,
            schema_type=schema_type,
            job_id=job_id,
            tenant_id=tenant_id,
        )
    else:
        # Too many relevant pages — use sliding windows over them
        result = await _tier3_pass2_windowed(
            relevant_pages=relevant_pages,
            page_texts=page_texts,
            vlm_client=vlm_client,
            token_budget=token_budget,
            config=config,
            schema_type=schema_type,
            job_id=job_id,
            tenant_id=tenant_id,
            semaphore=semaphore,
        )

    return result


async def _tier3_pass2_single(
    relevant_pages: list[int],
    page_texts: list[str],
    page_summaries: list[dict],
    vlm_client: VLMClientPort,
    token_budget: TokenBudget,
    schema_type: str,
    job_id: str,
    tenant_id: str,
) -> dict:
    """Tier 3 Pass 2 when relevant pages fit in a single VLM call."""
    summary_text = "Page summaries:\n"
    for i, summary in enumerate(page_summaries):
        if summary:
            summary_text += f"  Page {i + 1}: {json.dumps(summary)}\n"

    relevant_text = "\n\n".join(
        f"--- Page {idx + 1} ---\n{page_texts[idx]}" for idx in relevant_pages
    )

    prompt = (
        f"Based on the page summaries below, extract all financial data from "
        f"the relevant pages.\n\n{summary_text}\n\n"
        f"Relevant page content:\n{relevant_text}\n\n"
        f"Return a JSON object with:\n"
        f'- "header_fields": object with institution, client_name, '
        f"statement_date, period_from, period_to, account_number, iban, "
        f"opening_balance, closing_balance, currency\n"
        f'- "transactions": array of objects with date, description, '
        f"debit, credit, balance\n\n"
        f"Use null for fields not found. Respond with ONLY valid JSON."
    )

    if not token_budget.can_proceed():
        logger.warning(
            "vlm.budget_exceeded",
            tier="tier3",
            pass_num=2,
            job_id=job_id,
            action=token_budget.budget_exceeded_action,
        )
        return {}

    input_tokens = vlm_client.estimate_tokens(prompt)

    try:
        vlm_result: VLMFieldResult = await asyncio.to_thread(
            vlm_client.extract_field,
            prompt,
            "chunked_extraction",
            "Tier 3 Pass 2 full extraction",
            schema_type,
        )
    except Exception as exc:
        logger.warning(
            "vlm.window_failed",
            tier="tier3",
            pass_num=2,
            error=str(exc),
        )
        return {}

    output_tokens = vlm_client.estimate_tokens(vlm_result.raw_response)
    token_budget.record_usage(input_tokens, output_tokens)

    emit_window_usage(
        VLMUsageEvent(
            tenant_id=tenant_id,
            job_id=job_id,
            schema_type=schema_type,
            model_id=vlm_result.model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tier="tier3",
            window_index=len(page_texts),
            window_start_page=relevant_pages[0] + 1,
            window_end_page=relevant_pages[-1] + 1,
        )
    )

    if vlm_result.value is None:
        return {}

    try:
        return json.loads(strip_markdown_fences(vlm_result.value))
    except (json.JSONDecodeError, TypeError):
        logger.warning("vlm.window_failed", tier="tier3", pass_num=2, error="parse_error")
        return {}


async def _tier3_pass2_windowed(
    relevant_pages: list[int],
    page_texts: list[str],
    vlm_client: VLMClientPort,
    token_budget: TokenBudget,
    config: WindowConfig,
    schema_type: str,
    job_id: str,
    tenant_id: str,
    semaphore: asyncio.Semaphore,
) -> dict:
    """Tier 3 Pass 2 with sliding-window extraction over relevant pages.

    Reuses the same windowing and merging logic as Tier 2 but operates
    only on the subset of pages identified as relevant in Pass 1.
    """
    # Build page texts for only the relevant pages
    relevant_page_texts = [page_texts[idx] for idx in relevant_pages]

    # Create sliding windows over the relevant page subset
    windows = create_sliding_windows(relevant_page_texts, config)

    # Remap window page numbers to original document page numbers
    for window in windows:
        original_start = relevant_pages[window.start_page - 1]  # 0-indexed
        original_end = relevant_pages[window.end_page - 1]  # 0-indexed
        window.start_page = original_start + 1  # back to 1-indexed
        window.end_page = original_end + 1

    logger.info(
        "vlm.tier3_pass2_windowed",
        job_id=job_id,
        num_windows=len(windows),
        relevant_pages=len(relevant_pages),
    )

    # Process windows concurrently (same as Tier 2)
    tasks = [
        _process_window(
            window=w,
            window_index=i,
            vlm_client=vlm_client,
            token_budget=token_budget,
            schema_type=schema_type,
            job_id=job_id,
            tenant_id=tenant_id,
            semaphore=semaphore,
        )
        for i, w in enumerate(windows)
    ]

    results = await asyncio.gather(*tasks)
    window_results = [r for r in results if r is not None]

    return merge_window_results(window_results)



# ─── Main Entry Point ────────────────────────────────────────────────────────


async def extract_chunked(
    page_texts: list[str],
    abstained_fields: list[str],
    vlm_client: VLMClientPort,
    token_budget: TokenBudget,
    schema_type: str,
    job_id: str,
    tenant_id: str,
    window_config: WindowConfig | None = None,
    on_window_complete: Callable[[], None] | None = None,
) -> dict:
    """Orchestrate chunked VLM extraction using the appropriate tier.

    Selects the extraction tier based on document size and abstention pattern,
    then dispatches to the appropriate tier function. Emits a job usage summary
    on completion.

    Args:
        page_texts: List of page text content (one string per page).
        abstained_fields: List of field names that need VLM extraction.
        vlm_client: VLM client port implementation.
        token_budget: Per-job token budget tracker.
        schema_type: Document schema type (e.g., "bank_statement").
        job_id: Unique job identifier for logging.
        tenant_id: Tenant identifier for cost attribution.
        window_config: Optional window configuration override.
        on_window_complete: Optional callback invoked after each window completes.

    Returns:
        Merged extraction result dict.
    """
    config = window_config or WindowConfig()

    # Select tier
    tier = select_extraction_tier(page_texts, abstained_fields, vlm_client)
    logger.info(
        "vlm.tier_selected",
        tier=tier,
        job_id=job_id,
        total_pages=len(page_texts),
        abstained_fields=abstained_fields,
    )

    # Dispatch to appropriate tier
    result: dict = {}
    if tier == "single":
        # Full document in one call — delegate to existing llm_extractor
        # This path is handled by the caller; return empty to signal no chunking
        result = {}
    elif tier == "tier1":
        result = await _extract_tier1(
            page_texts=page_texts,
            abstained_fields=abstained_fields,
            vlm_client=vlm_client,
            token_budget=token_budget,
            schema_type=schema_type,
            job_id=job_id,
            tenant_id=tenant_id,
        )
    elif tier == "tier2":
        result = await _extract_tier2(
            page_texts=page_texts,
            vlm_client=vlm_client,
            token_budget=token_budget,
            config=config,
            schema_type=schema_type,
            job_id=job_id,
            tenant_id=tenant_id,
            on_window_complete=on_window_complete,
        )
    elif tier == "tier3":
        result = await _extract_tier3(
            page_texts=page_texts,
            vlm_client=vlm_client,
            token_budget=token_budget,
            config=config,
            schema_type=schema_type,
            job_id=job_id,
            tenant_id=tenant_id,
        )

    # Emit job usage summary
    emit_job_usage_summary(
        VLMJobUsageSummary(
            tenant_id=tenant_id,
            job_id=job_id,
            schema_type=schema_type,
            model_id=vlm_client.__class__.__name__,
            tier=tier,
            total_input_tokens=token_budget.consumed_input_tokens,
            total_output_tokens=token_budget.consumed_output_tokens,
            total_calls=token_budget.windows_processed,
            budget_max_tokens=token_budget.max_tokens,
            budget_exceeded=token_budget.is_exceeded,
            budget_action=token_budget.budget_exceeded_action,
            pages_processed=len(page_texts),
            windows_processed=token_budget.windows_processed,
        )
    )

    return result
