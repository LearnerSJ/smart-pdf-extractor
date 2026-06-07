"""POST /v1/extract endpoint.

Accepts a PDF file upload, generates a trace_id, runs the extraction pipeline,
and returns the result. For demo purposes, processing is synchronous.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel

from api.middleware.auth import resolve_tenant
from api.models.response import APIResponse, ResponseMeta
from api.models.tenant import TenantContext

router = APIRouter()
logger = structlog.get_logger()


class JobResponse(BaseModel):
    """Response payload for a submitted extraction job."""

    job_id: str
    trace_id: str
    status: str
    result: dict | None = None


# In-memory store for demo — jobs and results accessible by other endpoints
_JOBS: dict[str, dict] = {}
_RESULTS: dict[str, dict] = {}


def get_job(job_id: str, tenant_id: str) -> dict | None:
    """Retrieve a job by ID (used by jobs endpoint)."""
    job = _JOBS.get(job_id)
    if job and job.get("tenant_id") == tenant_id:
        return job
    return None


def get_result(job_id: str, tenant_id: str) -> dict | None:
    """Retrieve a result by job ID (used by results endpoint)."""
    result = _RESULTS.get(job_id)
    if result and result.get("tenant_id") == tenant_id:
        return result
    return None


# ─── Durable persistence (dual-write to Postgres; best-effort) ────────────────


async def _persist_job_create(*, job_id, tenant, trace_id, filename, doc_hash, schema_type) -> None:
    """Persist a new job. Never let a DB error fail the request (cache still holds it)."""
    try:
        from db.job_repo import JobRepo

        repo = JobRepo()
        await repo.ensure_tenant(tenant.id, tenant.name, tenant.api_key_hash, tenant.vlm_enabled)
        await repo.create_job(
            job_id=job_id, tenant_id=tenant.id, trace_id=trace_id,
            filename=filename, doc_hash=doc_hash, schema_type=schema_type,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("job.persist_create_failed", error=str(e), job_id=job_id)


async def _persist_job_finish(job_id, tenant, status, output_dict) -> None:
    """Persist final status + result. Best-effort."""
    try:
        from db.job_repo import JobRepo

        repo = JobRepo()
        await repo.set_status(job_id, tenant.id, status)
        await repo.save_result(job_id, tenant.id, output_dict)
    except Exception as e:  # noqa: BLE001
        logger.warning("job.persist_finish_failed", error=str(e), job_id=job_id)


async def warm_job_cache() -> None:
    """Reload persisted jobs + results into the in-memory caches on startup, so
    the queue and results survive a restart."""
    try:
        from db.job_repo import JobRepo

        jobs, results = await JobRepo().load_all()
        _JOBS.update(jobs)
        _RESULTS.update(results)
        logger.info("job.cache_warmed", jobs=len(jobs), results=len(results))
    except Exception as e:  # noqa: BLE001
        logger.warning("job.cache_warm_failed", error=str(e))


@router.post("/v1/extract", status_code=202)
async def submit_extraction(
    request: Request,
    file: UploadFile = File(...),
    schema_type: str | None = Form(default=None),
    batch_id: str | None = Form(default=None),
    force_reprocess: str | None = Form(default=None),
    tenant: TenantContext = Depends(resolve_tenant),
) -> APIResponse[JobResponse]:
    """Accept a PDF file and start extraction in the background.

    Returns 202 immediately with job_id. Poll /v1/jobs/{id}/progress for
    real-time progress and /v1/jobs/{id} for completion status.
    """
    trace_id = str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(trace_id=trace_id, tenant_id=tenant.id)

    # Read file content
    file_bytes = await file.read()
    doc_hash = hashlib.sha256(file_bytes).hexdigest()
    filename = file.filename or "unknown.pdf"
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    logger.info(
        "extraction.submitted",
        job_id=job_id,
        trace_id=trace_id,
        tenant_id=tenant.id,
        filename=filename,
        schema_type=schema_type,
        batch_id=batch_id,
    )

    # Check dedup store for previously processed identical document
    dedup_store = getattr(request.app.state, "dedup_store", None)
    should_force = force_reprocess and force_reprocess.lower() in ("true", "1", "yes")
    if dedup_store and not should_force:
        existing_job = dedup_store.lookup(doc_hash)
        if existing_job:
            logger.info(
                "extraction.dedup_hit",
                existing_job_id=existing_job,
                doc_hash=doc_hash,
                tenant_id=tenant.id,
            )
            return APIResponse[JobResponse](
                data=JobResponse(
                    job_id=existing_job,
                    trace_id=trace_id,
                    status="duplicate",
                    result=None,
                ),
                meta=ResponseMeta(
                    request_id=trace_id,
                    timestamp=now.isoformat(),
                ),
            )
    elif dedup_store and should_force:
        # Remove stale hash so this submission is treated as fresh
        dedup_store.remove(doc_hash)

    # Determine job priority based on file size
    file_size = len(file_bytes)
    priority = "high" if file_size < 1_000_000 else "normal"

    # Store job as processing
    _JOBS[job_id] = {
        "job_id": job_id,
        "tenant_id": tenant.id,
        "trace_id": trace_id,
        "filename": filename,
        "doc_hash": doc_hash,
        "schema_type": schema_type,
        "batch_id": batch_id,
        "status": "processing",
        "priority": priority,
        "created_at": now.isoformat(),
        "completed_at": None,
    }

    # Durable dual-write: persist the job to Postgres (tenant-scoped). The
    # in-memory _JOBS stays the fast read path; DB makes it survive restarts.
    await _persist_job_create(
        job_id=job_id, tenant=tenant, trace_id=trace_id,
        filename=filename, doc_hash=doc_hash, schema_type=schema_type,
    )

    # Store hash in dedup store for future lookups
    if dedup_store:
        dedup_store.store(doc_hash, job_id)

    # Store PDF bytes for the viewer
    pdf_store = getattr(request.app.state, "pdf_store", None)
    if pdf_store is not None:
        pdf_store[job_id] = file_bytes

    # Launch background processing
    asyncio.create_task(_run_pipeline_background(
        job_id=job_id,
        file_bytes=file_bytes,
        filename=filename,
        doc_hash=doc_hash,
        schema_type=schema_type,
        tenant=tenant,
        trace_id=trace_id,
        schema_cache=getattr(request.app.state, "schema_cache", None),
        template_store=getattr(request.app.state, "template_store", None),
        dedup_store=dedup_store,
    ))

    return APIResponse[JobResponse](
        data=JobResponse(
            job_id=job_id,
            trace_id=trace_id,
            status="processing",
            result=None,
        ),
        meta=ResponseMeta(
            request_id=trace_id,
            timestamp=now.isoformat(),
        ),
    )


async def _run_pipeline_background(
    job_id: str,
    file_bytes: bytes,
    filename: str,
    doc_hash: str,
    schema_type: str | None,
    tenant: "TenantContext",
    trace_id: str,
    schema_cache: "SchemaCache | None" = None,
    template_store: object = None,
    dedup_store: object = None,
) -> None:
    """Run the extraction pipeline as a background task."""
    try:
        from api.config import get_settings
        from pipeline.runner import PipelinePorts, process_document
        from pipeline.vlm.bedrock_client import BedrockVLMClient
        from pipeline.extractors.paddle_native_ocr import PaddleNativeOCRClient
        from pipeline.extractors.tesseract_ocr import TesseractOCRClient
        from pipeline.extractors.ocr import PaddleOCRClient
        from tests.mocks import MockDeliveryClient, MockRedactor

        settings = get_settings()

        # OCR priority: PaddleOCR native > Tesseract > PaddleOCR HTTP (Docker)
        paddle_native = PaddleNativeOCRClient()
        tesseract = TesseractOCRClient()
        if paddle_native.is_available():
            ocr_client = paddle_native
        elif tesseract.is_available():
            ocr_client = tesseract
        else:
            ocr_client = PaddleOCRClient(endpoint=settings.paddleocr_endpoint)

        ports = PipelinePorts(
            vlm_client=BedrockVLMClient(
                region=settings.aws_region,
                model_id=settings.bedrock_model_id,
                vlm_enabled=tenant.vlm_enabled,
            ),
            ocr_client=ocr_client,
            redactor=MockRedactor(),
            delivery_client=MockDeliveryClient(),
        )

        pipeline_result = await process_document(
            file_bytes=file_bytes,
            filename=filename,
            tenant=tenant,
            settings=settings,
            ports=ports,
            trace_id=trace_id,
            schema_type_hint=schema_type,
            job_id=job_id,
            schema_cache=schema_cache,
            template_store=template_store,
        )

        if pipeline_result.output is not None:
            output_dict = pipeline_result.output.model_dump()
            status = pipeline_result.output.status
        elif pipeline_result.cached:
            output_dict = {"cached": True, "doc_hash": doc_hash}
            status = "complete"
        else:
            output_dict = {"error": pipeline_result.error, "error_code": pipeline_result.error_code}
            status = "failed"

        # ── Self-Healing: Record failures for pattern mining ─────────────────
        from api.main import app as _app
        pattern_miner = getattr(_app.state, "pattern_miner", None)

        if pipeline_result.output and pattern_miner:
            for abstention in pipeline_result.output.abstentions:
                pattern_miner.record_failure(
                    job_id=job_id,
                    tenant_id=tenant.id,
                    schema_type=pipeline_result.output.schema_type or "unknown",
                    error_code=abstention.reason,
                    field_name=abstention.field,
                    institution=None,
                )

        # Update job status
        completed_at = datetime.now(timezone.utc).isoformat()
        _JOBS[job_id]["status"] = status
        _JOBS[job_id]["completed_at"] = completed_at

        # If the job failed, remove from dedup so the user can re-submit
        if status == "failed":
            if dedup_store:
                dedup_store.remove(doc_hash)

        # Store result
        _RESULTS[job_id] = {
            "job_id": job_id,
            "tenant_id": tenant.id,
            "trace_id": trace_id,
            "output": output_dict,
        }

        # Durable dual-write (tenant-scoped)
        await _persist_job_finish(job_id, tenant, status, output_dict)

    except Exception as e:
        logger.error("extraction.error", error=str(e), job_id=job_id)
        _JOBS[job_id]["status"] = "failed"
        _JOBS[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()

        _RESULTS[job_id] = {
            "job_id": job_id,
            "tenant_id": tenant.id,
            "trace_id": trace_id,
            "output": {"error": str(e)},
        }
        await _persist_job_finish(job_id, tenant, "failed", {"error": str(e)})
