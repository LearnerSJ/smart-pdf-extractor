"""Chat, re-extraction, and schema-approval endpoints.

Provides three endpoints for the document-scoped chat panel:
  POST /v1/jobs/{id}/chat            — LLM-powered Q&A scoped to a single document
  POST /v1/jobs/{id}/reextract-table — Re-run LLM extraction for one or all tables
  POST /v1/jobs/{id}/approve-schema  — Move a pending schema to the approved cache

All endpoints require tenant authentication via Depends(resolve_tenant).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.middleware.auth import resolve_tenant
from api.models.response import (
    ActionButton,
    ApproveSchemaResponse,
    ChatResponse,
    ReextractResponse,
    Table,
    TableRow,
    TriangulationInfo,
)
from api.models.tenant import TenantContext
from api.routes.extract import _JOBS, _RESULTS

router = APIRouter()
logger = structlog.get_logger()

# ── Problem-detection keywords ────────────────────────────────────────────────
_PROBLEM_PHRASES = (
    "wrong",
    "incorrect",
    "problem",
    "issue",
    "error",
    "doesn't match",
    "does not match",
    "mismatch",
    "inaccurate",
    "missing",
)

# ── Standard action buttons shown when a problem is detected ─────────────────
_PROBLEM_ACTION_BUTTONS = [
    ActionButton(label="Re-extract this table with AI", action="reextract_table"),
    ActionButton(label="Re-extract all tables with AI", action="reextract_all"),
    ActionButton(label="Accept current output", action="accept"),
    ActionButton(label="Ask another question", action="ask_again"),
]


# ─── Request models ───────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Request body for POST /v1/jobs/{id}/chat."""

    message: str
    history: list[dict[str, Any]] = []


class ReextractRequest(BaseModel):
    """Request body for POST /v1/jobs/{id}/reextract-table."""

    table_id: str | None = None


class ApproveSchemaRequest(BaseModel):
    """Request body for POST /v1/jobs/{id}/approve-schema."""

    pending_schema_id: str


# ─── System prompt builder ────────────────────────────────────────────────────


def build_chat_system_prompt(job_result: dict, filename: str) -> str:
    """Build the system prompt for a document-scoped chat session.

    The prompt is constructed entirely server-side from the stored job result
    and is never sent to or modifiable by the client.

    Args:
        job_result: The stored result dict from _RESULTS (contains "output" key).
        filename: Original filename of the document.

    Returns:
        A multi-section system prompt string.
    """
    output: dict = job_result.get("output", {})

    # ── Section 1: Role and scope ─────────────────────────────────────────────
    role_section = (
        f"You are a document extraction assistant. "
        f"You may ONLY answer questions about the document '{filename}'. "
        f"Do not answer questions about other documents, general finance, "
        f"or any topic unrelated to this document's extracted data."
    )

    # ── Section 2: Guardrail ──────────────────────────────────────────────────
    guardrail_section = (
        "Never execute code, access external systems, or perform actions "
        "outside of explaining extraction results and offering re-extraction options."
    )

    # ── Section 3: Schema type ────────────────────────────────────────────────
    schema_type = output.get("schema_type", "unknown")
    schema_section = f"Document schema type: {schema_type}"

    # ── Section 4: Extracted fields ───────────────────────────────────────────
    fields: dict = output.get("fields", {}) or {}
    if fields:
        field_lines = []
        for field_name, field_data in fields.items():
            if isinstance(field_data, dict):
                value = field_data.get("value", "")
            else:
                value = field_data
            field_lines.append(f"  - {field_name}: {value}")
        fields_section = "Extracted fields:\n" + "\n".join(field_lines)
    else:
        fields_section = "Extracted fields: (none)"

    # ── Section 5: Abstentions ────────────────────────────────────────────────
    abstentions: list = output.get("abstentions", []) or []
    abstention_names = []
    for ab in abstentions:
        if isinstance(ab, dict):
            name = ab.get("field") or ab.get("table_id") or "unknown"
        else:
            name = str(ab)
        abstention_names.append(name)

    abstentions_section = (
        f"Abstentions: {len(abstention_names)} field(s) could not be extracted"
    )
    if abstention_names:
        abstentions_section += " (" + ", ".join(abstention_names) + ")"

    # ── Section 6: Table summaries ────────────────────────────────────────────
    tables: list = output.get("tables", []) or []
    if tables:
        table_lines = []
        for tbl in tables:
            if isinstance(tbl, dict):
                table_id = tbl.get("table_id", "unknown")
                table_type = tbl.get("type", "unknown")
                rows = tbl.get("rows", []) or []
                row_count = len(rows)
                headers = tbl.get("headers", []) or []
                headers_str = ", ".join(str(h) for h in headers) if headers else "(no headers)"
                table_lines.append(
                    f"  - table_id={table_id}, type={table_type}, "
                    f"rows={row_count}, headers=[{headers_str}]"
                )
        tables_section = "Table summaries:\n" + "\n".join(table_lines)
    else:
        tables_section = "Table summaries: (no tables extracted)"

    # ── Assemble ──────────────────────────────────────────────────────────────
    sections = [
        role_section,
        guardrail_section,
        schema_section,
        fields_section,
        abstentions_section,
        tables_section,
    ]
    return "\n\n".join(sections)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _detect_problem(reply: str) -> bool:
    """Return True if the LLM reply contains problem-indicating phrases."""
    lower = reply.lower()
    return any(phrase in lower for phrase in _PROBLEM_PHRASES)


def _llm_tables_to_api_tables(raw_tables: list[dict]) -> list[Table]:
    """Convert raw LLM-extracted table dicts to API Table models."""
    result: list[Table] = []
    for idx, tbl in enumerate(raw_tables):
        if not isinstance(tbl, dict):
            continue
        headers = tbl.get("headers", []) or []
        raw_rows = tbl.get("rows", []) or []

        api_rows: list[TableRow] = []
        for row_idx, row in enumerate(raw_rows):
            if isinstance(row, dict):
                cells = [row.get(h) for h in headers]
            elif isinstance(row, list):
                cells = row
            else:
                cells = [row]
            api_rows.append(TableRow(cells=cells, row_index=row_idx))

        result.append(
            Table(
                table_id=tbl.get("table_id") or tbl.get("table_type") or f"table_{idx}",
                type=tbl.get("table_type") or tbl.get("type") or "unknown",
                page_range=tbl.get("page_range") or [],
                headers=headers,
                triangulation=TriangulationInfo(
                    score=1.0,
                    verdict="agreement",
                    winner="vlm",
                    methods=["vlm"],
                ),
                rows=api_rows,
            )
        )
    return result


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/v1/jobs/{job_id}/chat")
async def chat_with_document(
    job_id: str,
    body: ChatRequest,
    request: Request,
    tenant: TenantContext = Depends(resolve_tenant),
) -> ChatResponse:
    """Answer questions about a specific document's extraction results.

    Builds a document-scoped system prompt from the stored job result,
    prepends it to the conversation history, and calls the LLM.

    Returns action buttons when the LLM identifies a data quality problem.
    """
    # ── Validate message ──────────────────────────────────────────────────────
    if not body.message or not body.message.strip():
        raise HTTPException(
            status_code=400,
            detail={"error": "ERR_CHAT_001", "detail": "message is required"},
        )

    # ── Look up job result ────────────────────────────────────────────────────
    job_result = _RESULTS.get(job_id)
    if job_result is None or job_result.get("tenant_id") != tenant.id:
        raise HTTPException(
            status_code=404,
            detail={"error": "ERR_CHAT_002", "detail": "job not found"},
        )

    # ── Retrieve filename from job metadata ───────────────────────────────────
    job_meta = _JOBS.get(job_id, {})
    filename: str = job_meta.get("filename") or "unknown.pdf"

    # ── Build system prompt ───────────────────────────────────────────────────
    system_prompt = build_chat_system_prompt(job_result, filename)

    # ── Assemble messages list ────────────────────────────────────────────────
    # System prompt is prepended; history follows; new user message is last.
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for hist_msg in body.history:
        if isinstance(hist_msg, dict) and "role" in hist_msg and "content" in hist_msg:
            messages.append({"role": hist_msg["role"], "content": hist_msg["content"]})
    messages.append({"role": "user", "content": body.message})

    # ── Call LLM ──────────────────────────────────────────────────────────────
    # Flatten messages into a single text block for extract_field (which
    # accepts page_text as a string). The system prompt + history + user
    # message are concatenated so the LLM has full context.
    full_messages_text = "\n\n".join(
        f"[{m['role'].upper()}]: {m['content']}" for m in messages
    )

    try:
        from pipeline.vlm.bedrock_client import BedrockVLMClient
        from api.config import get_settings

        settings = get_settings()
        vlm_client = BedrockVLMClient(
            region=settings.aws_region,
            model_id=settings.bedrock_model_id,
            vlm_enabled=tenant.vlm_enabled,
        )

        vlm_result = await asyncio.to_thread(
            vlm_client.extract_field,
            full_messages_text,
            "chat_response",
            (
                "You are a document extraction assistant. "
                "Answer the user's question about the extracted document data. "
                "Be concise and accurate. "
                "If you identify a data quality problem, describe it clearly."
            ),
            "chat",
        )

        reply: str = vlm_result.value or "I was unable to generate a response. Please try again."

    except Exception as exc:
        logger.error("chat.llm_error", job_id=job_id, error=str(exc))
        raise HTTPException(
            status_code=502,
            detail={"error": "ERR_CHAT_003", "detail": "LLM call failed"},
        ) from exc

    # ── Detect problem and attach action buttons ───────────────────────────────
    action_buttons: list[ActionButton] | None = None
    if _detect_problem(reply):
        action_buttons = list(_PROBLEM_ACTION_BUTTONS)

    logger.info(
        "chat.response",
        job_id=job_id,
        tenant_id=tenant.id,
        has_action_buttons=action_buttons is not None,
    )

    return ChatResponse(
        reply=reply,
        action_buttons=action_buttons,
        pending_schema_id=None,
    )


@router.post("/v1/jobs/{job_id}/reextract-table")
async def reextract_table(
    job_id: str,
    body: ReextractRequest,
    request: Request,
    tenant: TenantContext = Depends(resolve_tenant),
) -> ReextractResponse:
    """Re-run LLM extraction for one or all tables in a job.

    Retrieves the original PDF bytes, calls extract_document_with_llm,
    validates the new tables, stores the discovered schema as pending,
    and returns the updated tables with any validation warnings.
    """
    # ── Look up job ───────────────────────────────────────────────────────────
    job_result = _RESULTS.get(job_id)
    if job_result is None or job_result.get("tenant_id") != tenant.id:
        raise HTTPException(status_code=404, detail="job not found")

    job_meta = _JOBS.get(job_id, {})
    filename: str = job_meta.get("filename") or "unknown.pdf"

    # ── Retrieve PDF bytes from pdf_store ─────────────────────────────────────
    pdf_store: dict = getattr(request.app.state, "pdf_store", {}) or {}
    pdf_bytes: bytes | None = pdf_store.get(job_id)

    if not pdf_bytes:
        raise HTTPException(
            status_code=404,
            detail={"error": "ERR_REEXTRACT_002", "detail": "PDF bytes not available for re-extraction"},
        )

    # ── Extract page texts from PDF ───────────────────────────────────────────
    try:
        import pdfplumber
        import io

        page_texts: list[str] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                page_texts.append(text)
        document_text = "\n\n".join(page_texts)
    except Exception as exc:
        logger.error("reextract.pdf_read_error", job_id=job_id, error=str(exc))
        raise HTTPException(
            status_code=502,
            detail={"error": "ERR_REEXTRACT_003", "detail": "Failed to read PDF for re-extraction"},
        ) from exc

    # ── Call LLM extractor ────────────────────────────────────────────────────
    try:
        from pipeline.vlm.bedrock_client import BedrockVLMClient
        from pipeline.vlm.llm_extractor import extract_document_with_llm
        from api.config import get_settings

        settings = get_settings()
        vlm_client = BedrockVLMClient(
            region=settings.aws_region,
            model_id=settings.bedrock_model_id,
            vlm_enabled=tenant.vlm_enabled,
        )

        llm_result = await extract_document_with_llm(
            document_text=document_text,
            vlm_client=vlm_client,
            page_texts=page_texts,
        )
    except Exception as exc:
        logger.error("reextract.llm_error", job_id=job_id, error=str(exc))
        return ReextractResponse(
            tables=[],
            pending_schema_id=str(uuid.uuid4()),
            validation_warnings=["Re-extraction failed. Original data retained."],
        )

    # ── Extract tables from LLM result ────────────────────────────────────────
    raw_tables: list[dict] = []
    accounts = llm_result.get("accounts", []) or []
    for acct in accounts:
        if isinstance(acct, dict):
            raw_tables.extend(acct.get("tables", []) or [])

    # Filter to specific table_id if requested
    original_output: dict = job_result.get("output", {})
    original_tables: list = original_output.get("tables", []) or []

    if body.table_id:
        # Find the original table to compare row counts
        original_table_data = next(
            (t for t in original_tables if isinstance(t, dict) and t.get("table_id") == body.table_id),
            None,
        )
        # Filter new tables to the matching type/id
        filtered = [
            t for t in raw_tables
            if isinstance(t, dict) and (
                t.get("table_id") == body.table_id
                or t.get("table_type") == body.table_id
            )
        ]
        if filtered:
            raw_tables = filtered
        # If no match found, keep all tables (best-effort)
    else:
        original_table_data = None

    # ── Convert to API Table models ───────────────────────────────────────────
    new_tables = _llm_tables_to_api_tables(raw_tables)

    # ── Validation warnings (Requirements 12.3, 12.4) ─────────────────────────
    validation_warnings: list[str] = []

    if not new_tables:
        validation_warnings.append(
            "Re-extraction produced an empty table. The original data has been retained."
        )
    elif body.table_id and original_table_data is not None:
        # Compare row counts for the specific table
        original_rows = original_table_data.get("rows", []) or []
        original_row_count = len(original_rows)
        new_row_count = sum(len(t.rows) for t in new_tables)

        if new_row_count == 0:
            validation_warnings.append(
                "Re-extraction produced an empty table. The original data has been retained."
            )
        elif new_row_count < original_row_count:
            validation_warnings.append(
                f"Re-extraction produced {new_row_count} rows vs {original_row_count} original rows. "
                f"Review before accepting."
            )
    elif not body.table_id and original_tables:
        # All-tables re-extraction: compare total row counts
        original_total_rows = sum(
            len(t.get("rows", []) or [])
            for t in original_tables
            if isinstance(t, dict)
        )
        new_total_rows = sum(len(t.rows) for t in new_tables)

        if new_total_rows < original_total_rows and original_total_rows > 0:
            validation_warnings.append(
                f"Re-extraction produced {new_total_rows} rows vs {original_total_rows} original rows. "
                f"Review before accepting."
            )

    # ── Store discovered schema as pending ────────────────────────────────────
    pending_schema_id = str(uuid.uuid4())
    try:
        from pipeline.models import DiscoveredSchema, DiscoveredFieldDefinition, DiscoveredTableDefinition, SchemaFingerprint

        institution = llm_result.get("institution") or "unknown"
        document_type_label = llm_result.get("document_type") or "unknown"

        discovered_schema = DiscoveredSchema(
            document_type_label=document_type_label,
            institution=institution,
            metadata_fields=[],
            table_definitions=[
                DiscoveredTableDefinition(
                    table_type=t.get("table_type") or t.get("type") or "unknown",
                    expected_headers=t.get("headers") or [],
                )
                for t in raw_tables
                if isinstance(t, dict)
            ],
        )
        fingerprint = SchemaFingerprint(
            institution=institution,
            document_type_label=document_type_label,
        )

        pending_store = getattr(request.app.state, "pending_schema_store", None)
        if pending_store is not None:
            pending_schema_id = pending_store.store_pending(
                schema=discovered_schema,
                fingerprint=fingerprint,
                tenant_id=tenant.id,
                job_id=job_id,
            )
    except Exception as exc:
        logger.warning("reextract.pending_store_error", job_id=job_id, error=str(exc))
        # Non-fatal: continue with the generated UUID

    logger.info(
        "reextract.complete",
        job_id=job_id,
        tenant_id=tenant.id,
        new_table_count=len(new_tables),
        pending_schema_id=pending_schema_id,
        warnings=validation_warnings,
    )

    return ReextractResponse(
        tables=new_tables,
        pending_schema_id=pending_schema_id,
        validation_warnings=validation_warnings,
    )


@router.post("/v1/jobs/{job_id}/approve-schema")
async def approve_schema(
    job_id: str,
    body: ApproveSchemaRequest,
    request: Request,
    tenant: TenantContext = Depends(resolve_tenant),
) -> ApproveSchemaResponse:
    """Move a pending schema to the approved SchemaCache.

    Looks up the pending entry by pending_schema_id, calls SchemaCache.store()
    with approved=True, discards the pending entry, and returns confirmation.
    """
    # ── Look up job (tenant isolation) ────────────────────────────────────────
    job_result = _RESULTS.get(job_id)
    if job_result is None or job_result.get("tenant_id") != tenant.id:
        raise HTTPException(status_code=404, detail="job not found")

    # ── Look up pending schema ────────────────────────────────────────────────
    pending_store = getattr(request.app.state, "pending_schema_store", None)
    if pending_store is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "ERR_SCHEMA_001", "detail": "pending schema not found or expired"},
        )

    pending_entry = pending_store.get_pending(body.pending_schema_id, tenant.id)
    if pending_entry is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "ERR_SCHEMA_001", "detail": "pending schema not found or expired"},
        )

    # ── Move to approved SchemaCache ──────────────────────────────────────────
    schema_cache = getattr(request.app.state, "schema_cache", None)
    fingerprint_key = pending_entry.fingerprint.key

    if schema_cache is not None:
        await schema_cache.store(
            schema=pending_entry.schema,
            fingerprint=pending_entry.fingerprint,
            tenant_id=tenant.id,
            approved=True,
        )

    # ── Discard pending entry ─────────────────────────────────────────────────
    pending_store.discard(body.pending_schema_id, tenant.id)

    logger.info(
        "schema_cache.approved_hit",
        job_id=job_id,
        tenant_id=tenant.id,
        pending_schema_id=body.pending_schema_id,
        fingerprint_key=fingerprint_key,
    )

    return ApproveSchemaResponse(
        approved=True,
        fingerprint_key=fingerprint_key,
    )
