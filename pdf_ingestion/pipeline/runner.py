"""Pipeline runner — end-to-end document processing orchestration.

Connects all pipeline stages:
    ingestion → classifier → extractor → triangulation → assembler →
    schema extractor → VLM fallback → validator → packager → delivery

This is the main orchestration function that processes a single document
through the full pipeline with dependency injection for all ports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

import pdfplumber
import structlog

if TYPE_CHECKING:
    from pipeline.discovery.schema_cache import SchemaCache

from api.config import Settings
from api.errors import ErrorCode
from api.models.response import Abstention, Field, FinalOutput, Provenance, Table
from api.models.tenant import TenantContext
from pipeline.assembler import assemble
from pipeline.classifier import classify_page
from pipeline.delivery import on_job_complete
from pipeline.extractors.camelot_extractor import extract_tables_camelot
from pipeline.extractors.digital import extract_digital_page
from pipeline.ingestion import ingest, IngestionError
from pipeline.models import (
    AssembledDocument,
    CachedResult,
    EntityRedactionConfig,
    IngestedDocument,
    PageOutput,
    Token,
    VLMFieldResult,
)
from pipeline.packager import package_result
from pipeline.ports import DeliveryPort, OCRClientPort, RedactorPort, VLMClientPort
from pipeline.schemas.router import route_and_extract, route_and_extract_async
from pipeline.triangulation import triangulate_table
from pipeline.validator import run_validators
from pipeline.vlm.chunked_extractor import (
    extract_chunked,
    select_extraction_tier,
    WindowConfig,
)
from pipeline.vlm.llm_extractor import extract_document_with_llm
from pipeline.vlm.token_budget import TokenBudget

logger = structlog.get_logger()


@dataclass
class PipelinePorts:
    """Container for all port implementations injected into the pipeline."""

    vlm_client: VLMClientPort
    ocr_client: OCRClientPort
    redactor: RedactorPort
    delivery_client: DeliveryPort


@dataclass
class PipelineResult:
    """Result of processing a document through the pipeline."""

    output: FinalOutput | None = None
    cached: bool = False
    error: str | None = None
    error_code: str | None = None


async def process_document(
    file_bytes: bytes,
    filename: str,
    tenant: TenantContext,
    settings: Settings,
    ports: PipelinePorts,
    trace_id: str = "",
    schema_type_hint: str | None = None,
    job_id: str | None = None,
    dedup_lookup: Callable[[str], CachedResult | None] | None = None,
    schema_cache: "SchemaCache | None" = None,
) -> PipelineResult:
    """Process a single document through the full extraction pipeline.

    Stages:
        1. Ingestion — validate, dedup, repair
        2. Classification — per-page DIGITAL/SCANNED
        3. Extraction — digital (pdfplumber) or OCR (PaddleOCR)
        4. Triangulation — compare pdfplumber vs camelot tables
        5. Assembly — merge pages, reading order, table stitching
        6. Schema extraction — rule-based field extraction
        7. VLM fallback — for abstained fields (if tenant consents)
        8. Validation — domain constraint checks
        9. Packaging — assemble FinalOutput
        10. Delivery — push to callback_url (if configured)

    Args:
        file_bytes: Raw PDF file bytes.
        filename: Original filename.
        tenant: Authenticated tenant context.
        settings: Application settings.
        ports: Injected port implementations.
        trace_id: Request trace ID for logging correlation.
        schema_type_hint: Optional pre-determined schema type.
        job_id: Optional job ID for tracking.
        dedup_lookup: Optional dedup check function.

    Returns:
        PipelineResult with the extraction output or error details.
    """
    structlog.contextvars.bind_contextvars(trace_id=trace_id, job_id=job_id)

    logger.info("extraction.submitted", filename=filename, tenant_id=tenant.id)

    # ── Progress tracking ────────────────────────────────────────────────────
    from api.progress import progress_store

    progress = progress_store.create(job_id or "unknown") if job_id else None

    # ── Stage 1: Ingestion ───────────────────────────────────────────────────
    try:
        ingested = await ingest(
            file_bytes=file_bytes,
            filename=filename,
            settings=settings,
            dedup_lookup=dedup_lookup,
        )
    except IngestionError as e:
        logger.error("extraction.error", code=e.code, message=e.message)
        return PipelineResult(error=e.message, error_code=e.code)

    # Handle cached/deduplicated result
    if isinstance(ingested, CachedResult):
        logger.info("extraction.deduplicated", hash=ingested.hash)
        return PipelineResult(cached=True)

    doc: IngestedDocument = ingested
    doc_id = f"sha256:{doc.hash}"

    # ── Stage 2 & 3: Classification + Extraction ─────────────────────────────
    page_outputs: list[PageOutput] = []
    pages_digital = 0
    pages_scanned = 0

    try:
        import io
        import asyncio

        with pdfplumber.open(io.BytesIO(doc.content)) as pdf:
            # First pass: classify all pages and extract digital pages synchronously
            # (pdfplumber is not thread-safe, so we do this in the main thread)
            page_data: list[tuple[int, str, Any]] = []  # (page_num, classification, page)
            digital_outputs: dict[int, PageOutput] = {}
            scanned_pages: list[tuple[int, bytes]] = []  # (page_num, image_bytes)

            total_pdf_pages = len(pdf.pages)
            if progress:
                progress.total_pages = total_pdf_pages
                progress.current_stage = "classifying"
                progress.stage_detail = f"Classifying {total_pdf_pages} pages"

            for page_num, page in enumerate(pdf.pages, start=1):
                classification = classify_page(page)
                page_data.append((page_num, classification, page))

                if classification == "DIGITAL":
                    pages_digital += 1
                    page_output = extract_digital_page(page, page_num)

                    # Camelot extraction for triangulation
                    camelot_tables = extract_tables_camelot(
                        doc.content, page_num
                    )

                    # ── Stage 4: Triangulation ───────────────────────────────
                    for i, pdfplumber_table in enumerate(page_output.tables):
                        if i < len(camelot_tables):
                            tri_result = triangulate_table(
                                pdfplumber_table,
                                camelot_tables[i],
                                job_id=job_id,
                                tenant_id=tenant.id,
                            )
                            pdfplumber_table["triangulation"] = {
                                "score": tri_result.disagreement_score,
                                "verdict": tri_result.verdict,
                                "winner": tri_result.winner,
                                "methods": tri_result.methods,
                            }

                    digital_outputs[page_num] = page_output
                else:
                    pages_scanned += 1
                    # Render page image for OCR (must happen while pdf is open)
                    page_image = _render_page_image(page)
                    scanned_pages.append((page_num, page_image))

            # Second pass: OCR scanned pages in parallel
            if progress:
                progress.current_stage = "extracting"
                progress.stage_detail = f"OCR on {len(scanned_pages)} scanned pages"
                progress.pages_classified = len(page_data)
                # Digital pages are already "done"
                progress.pages_ocr_complete = pages_digital

            async def _ocr_page(page_num: int, page_image: bytes) -> tuple[int, PageOutput]:
                import time as _time
                _start = _time.time()
                tokens = await asyncio.to_thread(
                    ports.ocr_client.extract_tokens, page_image
                )
                if progress:
                    elapsed_ms = (_time.time() - _start) * 1000
                    progress.record_page_complete(elapsed_ms)
                page_output = PageOutput(
                    page_number=page_num,
                    classification="SCANNED",
                    tokens=tokens,
                    tables=[],
                    text_blocks=[
                        {
                            "text": t.text,
                            "bbox": list(t.bbox),
                            "provenance": {
                                "page": page_num,
                                "bbox": list(t.bbox),
                                "source": "ocr",
                                "extraction_rule": "paddleocr",
                            },
                        }
                        for t in tokens
                    ],
                )
                return page_num, page_output

            # Run OCR concurrently (limit concurrency to avoid overwhelming resources)
            ocr_semaphore = asyncio.Semaphore(settings.ocr_concurrency)

            async def _ocr_with_semaphore(page_num: int, page_image: bytes) -> tuple[int, PageOutput]:
                async with ocr_semaphore:
                    return await _ocr_page(page_num, page_image)

            if scanned_pages:
                ocr_tasks = [
                    _ocr_with_semaphore(page_num, image)
                    for page_num, image in scanned_pages
                ]
                ocr_results = await asyncio.gather(*ocr_tasks)
                scanned_outputs: dict[int, PageOutput] = {
                    page_num: output for page_num, output in ocr_results
                }
            else:
                scanned_outputs = {}

            # Assemble page_outputs in original page order
            for page_num, classification, _ in page_data:
                if classification == "DIGITAL":
                    page_outputs.append(digital_outputs[page_num])
                else:
                    page_outputs.append(scanned_outputs[page_num])

    except Exception as e:
        logger.error("extraction.error", code="ERR_EXTRACT_003", message=str(e))
        return PipelineResult(error=str(e), error_code="ERR_EXTRACT_003")

    if not page_outputs:
        logger.error(
            "extraction.error",
            code=ErrorCode.INGESTION_ZERO_PAGES,
            message="Document has zero processable pages",
        )
        return PipelineResult(
            error="Document has zero processable pages",
            error_code=ErrorCode.INGESTION_ZERO_PAGES,
        )

    # ── Stage 5: Section Segmentation ───────────────────────────────────────
    from pipeline.section_segmenter import segment_document, DocumentSection

    sections = segment_document(page_outputs)

    # ── Pre-extract all page texts once (avoid re-opening PDF per section) ───
    # For scanned pages, use OCR tokens since pdfplumber returns empty text
    all_page_texts: list[str] = []
    try:
        import io as _io
        with pdfplumber.open(_io.BytesIO(doc.content)) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                # If pdfplumber returned little text, use OCR tokens instead
                if len(text.strip()) < 50 and page_idx < len(page_outputs):
                    ocr_text = " ".join(
                        t.text for t in page_outputs[page_idx].tokens if t.text
                    )
                    if ocr_text:
                        text = ocr_text
                all_page_texts.append(text)
    except Exception:
        # Fallback: build from OCR tokens
        all_page_texts = [
            " ".join(t.text for t in po.tokens if t.text)
            for po in page_outputs
        ]

    # Log page text quality
    non_empty = sum(1 for t in all_page_texts if len(t.strip()) > 10)
    logger.info("page_texts.built", total=len(all_page_texts), non_empty=non_empty)

    # ── Stage 5b: Assembly (per-section) ─────────────────────────────────────
    # If only one section, use the traditional single-pass approach.
    # If multiple sections, extract each independently and merge.

    all_fields: dict[str, Field] = {}
    all_tables: list[Table] = []
    all_abstentions: list[Abstention] = []
    resolved_schema_type: str = "unknown"

    # ── Phase 1: Rule-based extraction for all sections (fast, no I/O) ────────
    section_data: list[dict] = []  # Stores per-section intermediate results

    for section_idx, section in enumerate(sections):
        section_assembled = assemble(section.page_outputs)

        section_schema_hint = schema_type_hint if schema_type_hint else None
        if section.dominant_schema != "unknown" and not section_schema_hint:
            section_schema_hint = section.dominant_schema

        # Use async discovery path when tenant has VLM enabled and schema_cache
        # is available. This enables auto-schema discovery for unknown documents.
        if tenant.vlm_enabled and schema_cache is not None:
            from pipeline.vlm.token_budget import TokenBudget as _TB

            discovery_budget = _TB(
                max_tokens=settings.vlm_max_tokens_per_job,
                budget_exceeded_action=settings.vlm_budget_exceeded_action,
            )
            section_schema, section_result = await route_and_extract_async(
                section_assembled,
                schema_type_hint=section_schema_hint,
                tenant=tenant,
                vlm_client=ports.vlm_client,
                redactor=ports.redactor,
                schema_cache=schema_cache,
                token_budget=discovery_budget,
                trace_id=trace_id,
            )
        else:
            section_schema, section_result = route_and_extract(
                section_assembled, schema_type_hint=section_schema_hint
            )

        section_fields: dict[str, Field] = section_result.get("fields", {})
        section_tables: list[Table] = section_result.get("tables", [])
        section_abstentions: list[Abstention] = section_result.get("abstentions", [])

        section_data.append({
            "idx": section_idx,
            "section": section,
            "assembled": section_assembled,
            "schema": section_schema,
            "fields": section_fields,
            "tables": section_tables,
            "abstentions": section_abstentions,
        })

        # Update progress with partial results from rule-based extraction
        if progress and section_fields:
            partial = {k: v.value for k, v in section_fields.items() if v.value is not None}
            progress.update_partial_fields(partial)
            progress.update_partial_tables(
                progress.partial_tables_count + len(section_tables)
            )

    # ── Phase 2: VLM fallback for all sections in parallel ────────────────────
    if progress:
        progress.current_stage = "vlm"
        total_vlm_sections = sum(
            1 for sd in section_data
            if tenant.vlm_enabled and (sd["abstentions"] or sd["schema"] == "unknown")
        )
        progress.vlm_total_windows = total_vlm_sections
        progress.vlm_windows_complete = 0
        progress.stage_detail = f"LLM extraction ({total_vlm_sections} sections in parallel)"

    async def _process_section_vlm(sd: dict) -> dict:
        """Run VLM fallback for a single section. Returns updated section data."""
        section_idx = sd["idx"]
        section = sd["section"]
        section_assembled = sd["assembled"]
        section_schema = sd["schema"]
        section_abstentions = sd["abstentions"]
        section_fields = sd["fields"]

        if not (tenant.vlm_enabled and (section_abstentions or section_schema == "unknown")):
            logger.debug(
                "vlm.skipped",
                section_index=section_idx,
                vlm_enabled=tenant.vlm_enabled,
                has_abstentions=bool(section_abstentions),
                schema=section_schema,
            )
            return sd

        logger.info(
            "vlm.section_triggered",
            section_index=section_idx,
            schema=section_schema,
            abstentions=len(section_abstentions),
        )

        # When schema is unknown, trigger full VLM extraction
        if section_schema == "unknown" and not any(a.field is not None for a in section_abstentions):
            from api.models.response import Abstention as AbstentionModel
            synthetic_abstentions = [
                AbstentionModel(
                    field=f_name,
                    table_id=None,
                    reason="ERR_EXTRACT_002",
                    detail=f"Schema unknown for section {section_idx + 1} (pages {section.start_page}-{section.end_page})",
                    vlm_attempted=False,
                )
                for f_name in ["institution", "client_name", "account_number",
                               "statement_date", "opening_balance", "closing_balance"]
            ]
            section_abstentions = synthetic_abstentions + section_abstentions

        new_fields, new_abstentions = await _vlm_fallback(
            abstentions=section_abstentions,
            assembled_doc=section_assembled,
            schema_type=section_schema,
            tenant=tenant,
            ports=ports,
            page_outputs=section.page_outputs,
            pdf_content=doc.content,
            settings=settings,
            job_id=job_id or "",
            section_page_texts=all_page_texts[section.start_page - 1:section.end_page],
            progress=None,  # Don't update progress per-section (tracked at batch level)
        )

        if progress:
            progress.vlm_windows_complete += 1

        # If VLM resolved fields on an unknown schema, upgrade
        if section_schema == "unknown" and new_fields:
            doc_type_field = new_fields.get("document_type")
            if doc_type_field and doc_type_field.value:
                section_schema = doc_type_field.value
            else:
                section_schema = "bank_statement"

        # Merge VLM fields into existing fields (VLM results take priority)
        merged_fields = dict(section_fields)
        merged_fields.update(new_fields)
        sd["fields"] = merged_fields
        sd["abstentions"] = new_abstentions
        sd["schema"] = section_schema

        # Update progress store with partial results as fields are extracted
        if progress:
            partial = {k: v.value for k, v in merged_fields.items() if v.value is not None}
            progress.update_partial_fields(partial)

        return sd

    # Run all VLM calls concurrently (with concurrency limit to avoid rate limiting)
    import asyncio as _asyncio

    _vlm_section_semaphore = _asyncio.Semaphore(10)  # Max 10 concurrent Bedrock calls

    async def _bounded_process_section_vlm(sd: dict) -> dict:
        async with _vlm_section_semaphore:
            try:
                return await _process_section_vlm(sd)
            except Exception as exc:
                logger.error(
                    "vlm.section_error",
                    section_index=sd["idx"],
                    error=str(exc),
                )
                return sd  # Return unmodified on error

    vlm_tasks = [_bounded_process_section_vlm(sd) for sd in section_data]
    logger.info("vlm.gather_start", num_tasks=len(vlm_tasks), vlm_enabled=tenant.vlm_enabled)
    section_data = await _asyncio.gather(*vlm_tasks)
    logger.info("vlm.gather_complete", num_results=len(section_data))

    # ── Phase 3: Merge all section results ────────────────────────────────────
    for sd in section_data:
        section_schema = sd["schema"]
        section_fields = sd["fields"]
        section_tables = sd["tables"]
        section_abstentions = sd["abstentions"]
        section = sd["section"]
        section_idx = sd["idx"]

        if resolved_schema_type == "unknown" and section_schema != "unknown":
            resolved_schema_type = section_schema

        # Merge fields: accumulate accounts from all sections, take first
        # non-null value for scalar fields
        for field_name, field_value in section_fields.items():
            if field_name == "accounts":
                # Always merge accounts arrays across sections
                if field_name not in all_fields:
                    all_fields[field_name] = field_value
                elif field_value.value:
                    existing_accounts = all_fields[field_name].value or []
                    new_accounts = field_value.value if isinstance(field_value.value, list) else []
                    if isinstance(existing_accounts, list):
                        all_fields[field_name] = Field(
                            value=existing_accounts + new_accounts,
                            original_string=field_value.original_string,
                            confidence=min(all_fields[field_name].confidence, field_value.confidence),
                            vlm_used=all_fields[field_name].vlm_used or field_value.vlm_used,
                            redaction_applied=all_fields[field_name].redaction_applied or field_value.redaction_applied,
                            provenance=field_value.provenance,
                        )
            elif field_name not in all_fields:
                all_fields[field_name] = field_value
            elif all_fields[field_name].value is None and field_value.value is not None:
                # Fill in nulls from later sections
                all_fields[field_name] = field_value

        all_tables.extend(section_tables)
        all_abstentions.extend(section_abstentions)

        logger.info(
            "section.extracted",
            section_index=section_idx,
            pages=f"{section.start_page}-{section.end_page}",
            schema=section_schema,
            fields_extracted=len(section_fields),
            abstentions=len(section_abstentions),
        )

    # ── Deduplicate accounts by account number ─────────────────────────────────
    if "accounts" in all_fields and all_fields["accounts"].value:
        raw_accounts = all_fields["accounts"].value
        if isinstance(raw_accounts, list) and len(raw_accounts) > 1:
            merged_accounts: dict[str, dict] = {}  # keyed by account_number or iban
            for acct in raw_accounts:
                if not isinstance(acct, dict):
                    continue
                key = acct.get("account_number") or acct.get("iban")
                # Skip accounts with no identifier AND no transactions/tables
                if not key:
                    txns = acct.get("transactions", [])
                    tables = acct.get("tables", [])
                    if not txns and not tables:
                        continue
                    key = f"unidentified_{len(merged_accounts)}"

                if key in merged_accounts:
                    existing = merged_accounts[key]
                    # Merge transactions (same schema: date/desc/debit/credit/balance)
                    existing_txns = existing.get("transactions", []) or []
                    new_txns = acct.get("transactions", []) or []
                    existing["transactions"] = existing_txns + new_txns
                    # Merge additional tables (different schemas like settlement/clearing)
                    existing_tables = existing.get("tables", []) or []
                    new_tables = acct.get("tables", []) or []
                    existing["tables"] = existing_tables + new_tables
                    # Fill in missing scalar fields
                    for k, v in acct.items():
                        if k not in ("transactions", "tables") and v is not None and not existing.get(k):
                            existing[k] = v
                else:
                    merged_accounts[key] = dict(acct)
                    # Ensure tables key exists
                    if "tables" not in merged_accounts[key]:
                        merged_accounts[key]["tables"] = []

            # Filter out accounts with no useful data
            final_accounts = [
                acct for acct in merged_accounts.values()
                if (acct.get("transactions") or acct.get("tables") or
                    acct.get("opening_balance") is not None or acct.get("closing_balance") is not None)
            ]

            all_fields["accounts"] = Field(
                value=final_accounts,
                original_string=all_fields["accounts"].original_string,
                confidence=all_fields["accounts"].confidence,
                vlm_used=all_fields["accounts"].vlm_used,
                redaction_applied=all_fields["accounts"].redaction_applied,
                provenance=all_fields["accounts"].provenance,
            )

    # Use merged results
    schema_type = resolved_schema_type if resolved_schema_type != "unknown" else (schema_type_hint or "unknown")
    fields = all_fields
    tables = all_tables
    abstentions = all_abstentions

    # Remove stale abstentions that were resolved by VLM
    if "accounts" in fields and fields["accounts"].value:
        accounts_val = fields["accounts"].value
        has_data = any(
            isinstance(a, dict) and (a.get("transactions") or a.get("tables"))
            for a in (accounts_val if isinstance(accounts_val, list) else [])
        )
        if has_data:
            # Remove transaction table abstentions
            abstentions = [
                a for a in abstentions
                if not (a.table_id and "transactions" in str(a.table_id))
            ]
            # Remove positions table abstentions (custody schema)
            abstentions = [
                a for a in abstentions
                if not (a.table_id and "positions" in str(a.table_id))
            ]
            # Remove custody-specific field abstentions when VLM extracted accounts
            custody_fields = {"portfolio_id", "valuation_date", "total_value",
                              "trade_date", "settlement_date", "isin", "quantity",
                              "price", "counterparty_bic", "opening_balance"}
            abstentions = [
                a for a in abstentions
                if a.field not in custody_fields
            ]

    # Remove field abstentions for fields that were actually extracted
    resolved_field_names = set(fields.keys())
    abstentions = [
        a for a in abstentions
        if a.field is None or a.field not in resolved_field_names
    ]

    # ── Self-Healing: Check if retry is needed ───────────────────────────────
    from pipeline.self_healing.diagnostic_retry import DiagnosticRetry

    diagnostic = DiagnosticRetry(ports.vlm_client)
    if await diagnostic.should_retry(fields, abstentions, schema_type):
        # Build sample text for diagnosis
        sample_for_diagnosis = "\n".join(all_page_texts[:3]) if all_page_texts else ""

        diagnosis = await diagnostic.diagnose(
            sample_text=sample_for_diagnosis,
            schema_type=schema_type,
            fields=fields,
            abstentions=abstentions,
            trace_id=trace_id,
        )

        strategy = diagnostic.get_retry_strategy(diagnosis)

        if strategy == "auto_discovery" and schema_cache and tenant.vlm_enabled:
            # Retry with auto-discovery (force unknown schema)
            logger.info("self_healing.retrying_with_discovery", trace_id=trace_id, strategy=strategy)
            from pipeline.discovery.auto_discovery import AutoSchemaDiscovery
            from pipeline.discovery.dynamic_extractor import DynamicExtractor
            from pipeline.vlm.token_budget import TokenBudget as _RetryBudget

            retry_budget = _RetryBudget(
                max_tokens=settings.vlm_max_tokens_per_job,
                budget_exceeded_action=settings.vlm_budget_exceeded_action,
            )
            discovery = AutoSchemaDiscovery(ports.vlm_client, ports.redactor, schema_cache)
            assembled_for_retry = assemble(page_outputs)
            discovered = await discovery.discover(assembled_for_retry, tenant, retry_budget, trace_id)

            if not isinstance(discovered, Abstention):
                extractor = DynamicExtractor(ports.vlm_client, ports.redactor)
                retry_result = await extractor.extract(
                    assembled_for_retry, discovered, tenant, retry_budget, trace_id
                )
                # Replace results if retry produced better output
                retry_fields = retry_result.get("fields", {})
                retry_abstentions = retry_result.get("abstentions", [])
                retry_field_count = len(retry_fields)
                original_field_count = len(fields)

                if retry_field_count > original_field_count:
                    logger.info(
                        "self_healing.retry_improved",
                        trace_id=trace_id,
                        original_fields=original_field_count,
                        retry_fields=retry_field_count,
                    )
                    all_fields = retry_fields
                    all_abstentions = retry_abstentions
                    schema_type = retry_result.get("schema_type", schema_type)
                    fields = all_fields
                    abstentions = all_abstentions

    assembled_doc = assemble(page_outputs)  # Full doc assembly for validation

    # ── Stage 8: Validation ──────────────────────────────────────────────────
    # Build a preliminary FinalOutput for validation
    from pipeline.validator import ValidationReport
    preliminary_output = package_result(
        doc_id=doc_id,
        schema_type=schema_type,
        fields=fields,
        tables=tables,
        abstentions=abstentions,
        validation=ValidationReport(passed=True),
        pages_digital=pages_digital,
        pages_scanned=pages_scanned,
    )

    # Run validators on the preliminary output
    validation_report = run_validators(preliminary_output, total_pages=len(page_outputs))

    # Log validation failures
    for failure in validation_report.failures:
        logger.warning(
            "validation.failed",
            validator_name=failure.validator_name,
            field_name=failure.field_name,
            error_code=failure.error_code,
        )

    # ── Stage 9: Packaging ───────────────────────────────────────────────────
    if progress:
        progress.current_stage = "packaging"
        progress.stage_detail = "Assembling final output"

    final_output = package_result(
        doc_id=doc_id,
        schema_type=schema_type,
        fields=fields,
        tables=tables,
        abstentions=abstentions,
        validation=validation_report,
        pages_digital=pages_digital,
        pages_scanned=pages_scanned,
    )

    logger.info(
        "extraction.complete",
        doc_id=doc_id,
        schema_type=schema_type,
        fields_extracted=len(fields),
        fields_abstained=len([a for a in abstentions if a.field]),
        vlm_used=any(f.vlm_used for f in fields.values()),
        status=final_output.status,
    )

    # ── Stage 10: Delivery ───────────────────────────────────────────────────
    # Delivery is triggered asynchronously after job completion.
    # The caller (route handler) is responsible for calling on_job_complete()
    # after persisting the result. We return the output here.

    if progress:
        progress.current_stage = "complete"
        progress.stage_detail = "Done"

    structlog.contextvars.unbind_contextvars("trace_id", "job_id")

    return PipelineResult(output=final_output)


async def _vlm_fallback(
    abstentions: list[Abstention],
    assembled_doc: AssembledDocument,
    schema_type: str,
    tenant: TenantContext,
    ports: PipelinePorts,
    page_outputs: list[PageOutput],
    pdf_content: bytes = b"",
    settings: Settings | None = None,
    job_id: str = "",
    section_page_texts: list[str] | None = None,
    progress: "JobProgress | None" = None,
) -> tuple[dict[str, Field], list[Abstention]]:
    """Use LLM extraction for abstained fields, with chunked support for large docs.

    For documents that fit within the model's context window, sends the full
    document text in one call. For larger documents, uses tiered chunked
    extraction (targeted pages, sliding window, or two-pass).

    Args:
        abstentions: Current list of abstentions.
        assembled_doc: The assembled document.
        schema_type: Detected schema type.
        tenant: Tenant context with redaction config.
        ports: Pipeline port implementations.
        page_outputs: Per-page outputs.
        pdf_content: Raw PDF bytes for text extraction.
        settings: Application settings for token budget configuration.
        job_id: Job identifier for logging and tracking.
        section_page_texts: Pre-extracted page texts for this section.
            If provided, skips re-opening the PDF.

    Returns:
        Tuple of (updated_fields, remaining_abstentions).
    """
    resolved_fields: dict[str, Field] = {}
    remaining_abstentions: list[Abstention] = []

    # Separate table abstentions (not handled by LLM extraction)
    field_abstentions = [a for a in abstentions if a.field is not None]
    table_abstentions = [a for a in abstentions if a.field is None]
    has_transaction_abstention = any(
        "transaction" in str(a.table_id or "").lower() for a in table_abstentions
    )

    if not field_abstentions and not has_transaction_abstention:
        remaining_abstentions.extend(table_abstentions)
        return resolved_fields, remaining_abstentions

    if not has_transaction_abstention:
        remaining_abstentions.extend(table_abstentions)

    # Build redaction config from tenant settings
    redaction_config = _build_redaction_config(tenant, schema_type)

    # Use pre-extracted page texts if available, otherwise extract from PDF
    if section_page_texts is not None:
        page_texts = section_page_texts
    else:
        page_texts = []
        try:
            import io as _io
            with pdfplumber.open(_io.BytesIO(pdf_content)) as pdf:
                for page in pdf.pages:
                    page_text_raw = page.extract_text() or ""
                    page_texts.append(page_text_raw)
        except Exception:
            # Fallback to assembled blocks if direct extraction fails
            fallback_text = " ".join(
                block.get("text", "") if isinstance(block, dict) else ""
                for block in assembled_doc.blocks
            )
            page_texts = [fallback_text] if fallback_text else []

    page_text = "\n".join(page_texts)

    logger.info("vlm.page_text_built", text_length=len(page_text), text_preview=page_text[:100])

    # ── Token Budget and Tier Selection ──────────────────────────────────────
    # Use settings for budget configuration, with sensible defaults
    max_tokens = settings.vlm_max_tokens_per_job if settings else 100_000
    budget_action = settings.vlm_budget_exceeded_action if settings else "flag"

    token_budget = TokenBudget(
        max_tokens=max_tokens,
        budget_exceeded_action=budget_action,
    )

    # Select extraction tier
    abstained_field_names = [a.field for a in field_abstentions]
    tier = select_extraction_tier(page_texts, abstained_field_names, ports.vlm_client)

    logger.info(
        "vlm.tier_selected",
        tier=tier,
        job_id=job_id,
        tenant_id=tenant.id,
        total_pages=len(page_texts),
        abstained_fields=abstained_field_names,
    )

    # ── Dispatch based on tier ───────────────────────────────────────────────
    if tier != "single":
        # Use chunked extraction for large documents
        window_config = WindowConfig(
            window_size=settings.vlm_window_size if settings else 12,
            overlap=settings.vlm_window_overlap if settings else 3,
            max_concurrent=settings.vlm_max_concurrent_windows if settings else 3,
        )

        llm_result = await extract_chunked(
            page_texts=page_texts,
            abstained_fields=abstained_field_names,
            vlm_client=ports.vlm_client,
            token_budget=token_budget,
            schema_type=schema_type,
            job_id=job_id,
            tenant_id=tenant.id,
            window_config=window_config,
            on_window_complete=lambda: _increment_vlm_progress(progress),
        )

        # Handle budget exceeded action
        if token_budget.is_exceeded:
            if budget_action == "skip":
                logger.warning(
                    "vlm.budget_exceeded",
                    job_id=job_id,
                    action="skip",
                    consumed=token_budget.total_consumed,
                    max_tokens=max_tokens,
                )
                # Abstain remaining fields that weren't resolved
                for abstention in field_abstentions:
                    field_name = abstention.field
                    if field_name not in llm_result:
                        remaining_abstentions.append(
                            Abstention(
                                field=field_name,
                                table_id=None,
                                reason=ErrorCode.VLM_BUDGET_EXCEEDED,
                                detail=f"Token budget exceeded (consumed {token_budget.total_consumed}/{max_tokens})",
                                vlm_attempted=True,
                            )
                        )
            elif budget_action == "flag":
                logger.warning(
                    "vlm.budget_exceeded",
                    job_id=job_id,
                    action="flag",
                    consumed=token_budget.total_consumed,
                    max_tokens=max_tokens,
                )
            # "proceed" — no special handling needed

        # Map chunked result to resolved fields
        llm_fields = _flatten_llm_result(llm_result) if llm_result else {}

        # Also check for direct field keys in the result (tier1 returns flat keys)
        for key, value in llm_result.items():
            if key not in ("header_fields", "transactions", "accounts") and value is not None:
                llm_fields.setdefault(key, value)

        # Extract header_fields if present (tier2/tier3 format)
        header_fields = llm_result.get("header_fields", {})
        if header_fields:
            for key, value in header_fields.items():
                if value is not None:
                    llm_fields.setdefault(key, value)

        for abstention in field_abstentions:
            field_name = abstention.field
            if field_name in llm_fields and llm_fields[field_name] is not None:
                provenance = Provenance(
                    page=1,
                    bbox=[0, 0, 0, 0],
                    source="vlm",
                    extraction_rule=f"llm_chunked_{tier}",
                )
                resolved_fields[field_name] = Field(
                    value=llm_fields[field_name],
                    original_string=str(llm_fields[field_name]),
                    confidence=0.85,
                    vlm_used=True,
                    redaction_applied=False,
                    provenance=provenance,
                )
            else:
                # Only add to remaining if not already added by budget skip
                if not (token_budget.is_exceeded and budget_action == "skip"):
                    remaining_abstentions.append(
                        Abstention(
                            field=field_name,
                            table_id=None,
                            reason=ErrorCode.VLM_RETURNED_NULL,
                            detail=f"Chunked extraction ({tier}) did not return value for {field_name}",
                            vlm_attempted=True,
                        )
                    )

        # If there are table abstentions (transactions not found by regex),
        # run the two-phase transaction extraction
        if has_transaction_abstention:
            logger.info("vlm.transaction_extraction_triggered", job_id=job_id, total_pages=len(page_texts))
            txn_result = await extract_document_with_llm(
                document_text=page_text,
                vlm_client=ports.vlm_client,
                schema_type_hint=schema_type,
                page_texts=page_texts,
            )
            if txn_result and "accounts" in txn_result and txn_result["accounts"]:
                provenance = Provenance(
                    page=1, bbox=[0, 0, 0, 0], source="vlm",
                    extraction_rule="llm_two_phase_extraction",
                )
                resolved_fields["accounts"] = Field(
                    value=txn_result["accounts"],
                    original_string=json.dumps(txn_result["accounts"])[:200],
                    confidence=0.85,
                    vlm_used=True,
                    redaction_applied=False,
                    provenance=provenance,
                )
                # Also capture metadata fields from the two-phase result
                for key in ("institution", "client_name", "statement_date", "period_from", "period_to"):
                    if key in txn_result and txn_result[key] is not None and key not in resolved_fields:
                        resolved_fields[key] = Field(
                            value=txn_result[key],
                            original_string=str(txn_result[key]),
                            confidence=0.85,
                            vlm_used=True,
                            redaction_applied=False,
                            provenance=provenance,
                        )

        return resolved_fields, remaining_abstentions

    # ── Single tier: existing full-document extraction path ──────────────────
    # Redact before sending to LLM
    redacted_text, redaction_log = ports.redactor.redact_page_text(
        text=page_text,
        config=redaction_config,
    )

    logger.info(
        "vlm.full_extraction_triggered",
        schema_type=schema_type,
        abstained_fields=[a.field for a in field_abstentions],
        redacted_entities=redaction_log.redacted_count,
    )

    # Two-phase LLM extraction: metadata + per-page transactions
    llm_result = await extract_document_with_llm(
        document_text=redacted_text,
        vlm_client=ports.vlm_client,
        schema_type_hint=schema_type,
        page_texts=page_texts,
    )

    logger.info(
        "vlm.two_phase_result",
        has_accounts=bool(llm_result.get("accounts")),
        num_accounts=len(llm_result.get("accounts", [])),
        has_error=bool(llm_result.get("error")),
    )

    # Check for extraction error
    if "error" in llm_result:
        logger.warning(
            "vlm.full_extraction_failed",
            error=llm_result.get("error"),
            detail=llm_result.get("detail"),
        )
        # All field abstentions remain unresolved
        for abstention in field_abstentions:
            remaining_abstentions.append(
                Abstention(
                    field=abstention.field,
                    table_id=None,
                    reason=llm_result.get("error", ErrorCode.VLM_RETURNED_NULL),
                    detail=llm_result.get("detail", "LLM full extraction failed"),
                    vlm_attempted=True,
                )
            )
        return resolved_fields, remaining_abstentions

    # Map LLM result fields to resolved fields — trust the LLM output
    llm_fields = _flatten_llm_result(llm_result)

    # Always capture key metadata fields from VLM (even if not abstained)
    for key_field in ("institution", "client_name", "statement_date", "period_from", "period_to"):
        if key_field in llm_fields and llm_fields[key_field] is not None:
            if key_field not in resolved_fields:
                provenance = Provenance(
                    page=1,
                    bbox=[0, 0, 0, 0],
                    source="vlm",
                    extraction_rule="llm_full_extraction",
                )
                resolved_fields[key_field] = Field(
                    value=llm_fields[key_field],
                    original_string=str(llm_fields[key_field]),
                    confidence=0.85,
                    vlm_used=True,
                    redaction_applied=redaction_log.redacted_count > 0,
                    provenance=provenance,
                )

    for abstention in field_abstentions:
        field_name = abstention.field
        if field_name in llm_fields and llm_fields[field_name] is not None:
            provenance = Provenance(
                page=1,
                bbox=[0, 0, 0, 0],
                source="vlm",
                extraction_rule="llm_full_extraction",
            )
            resolved_fields[field_name] = Field(
                value=llm_fields[field_name],
                original_string=str(llm_fields[field_name]),
                confidence=0.85,
                vlm_used=True,
                redaction_applied=redaction_log.redacted_count > 0,
                provenance=provenance,
            )
        else:
            remaining_abstentions.append(
                Abstention(
                    field=field_name,
                    table_id=None,
                    reason=ErrorCode.VLM_RETURNED_NULL,
                    detail=f"LLM full extraction did not return value for {field_name}",
                    vlm_attempted=True,
                )
            )

    # Store accounts data as a special field if present
    if "accounts" in llm_result and llm_result["accounts"]:
        provenance = Provenance(
            page=1,
            bbox=[0, 0, 0, 0],
            source="vlm",
            extraction_rule="llm_full_extraction",
        )
        resolved_fields["accounts"] = Field(
            value=llm_result["accounts"],
            original_string=json.dumps(llm_result["accounts"]),
            confidence=0.85,
            vlm_used=True,
            redaction_applied=redaction_log.redacted_count > 0,
            provenance=provenance,
        )

    return resolved_fields, remaining_abstentions


def _flatten_llm_result(llm_result: dict) -> dict:
    """Flatten the LLM extraction result into a simple field name → value map.

    Maps the structured LLM output to field names that match the schema
    extraction field names used by the regex-based extractors.

    Args:
        llm_result: Parsed JSON from the LLM extraction.

    Returns:
        Dict mapping field names to their extracted values.
    """
    flat: dict = {}

    # Top-level fields
    for key in ("document_type", "statement_date", "period_from", "period_to",
                "institution", "client_name"):
        if key in llm_result and llm_result[key] is not None:
            flat[key] = llm_result[key]

    # Extract fields from the first account (for single-account documents)
    accounts = llm_result.get("accounts", [])
    if accounts and len(accounts) > 0:
        first_account = accounts[0]
        for key in ("account_number", "iban", "currency", "account_type",
                    "opening_balance", "closing_balance"):
            if key in first_account and first_account[key] is not None:
                flat[key] = first_account[key]

    return flat


def _build_redaction_config(
    tenant: TenantContext, schema_type: str
) -> list[EntityRedactionConfig]:
    """Build the redaction config list from tenant settings.

    Uses per-schema override if available, otherwise global config.
    """
    from pipeline.models import EntityRedactionConfig as PipelineEntityConfig

    redaction_settings = tenant.redaction_config

    # Check for schema-specific override
    if schema_type in redaction_settings.schema_overrides:
        return [
            PipelineEntityConfig(
                entity_type=e.entity_type,
                enabled=e.enabled,
            )
            for e in redaction_settings.schema_overrides[schema_type]
        ]

    # Fall back to global config
    return [
        PipelineEntityConfig(
            entity_type=e.entity_type,
            enabled=e.enabled,
        )
        for e in redaction_settings.global_entities
    ]


def _render_page_image(page: Any) -> bytes:
    """Render a pdfplumber page to PNG image bytes.

    Used for OCR and VLM processing of page content.

    Args:
        page: A pdfplumber page object.

    Returns:
        PNG image bytes.
    """
    try:
        im = page.to_image(resolution=150)
        import io
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        # Return minimal placeholder if rendering fails
        return b""




def _increment_vlm_progress(progress) -> None:
    """Increment VLM window completion counter on the progress tracker."""
    if progress is not None:
        progress.vlm_windows_complete += 1
