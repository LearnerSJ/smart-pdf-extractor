"""GET /v1/jobs/{id} endpoint.

Retrieves job status scoped to the authenticated tenant.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from api.errors import ErrorCode
from api.middleware.auth import resolve_tenant
from api.models.response import APIResponse, ResponseMeta
from api.models.tenant import TenantContext
from api.progress import progress_store

from pydantic import BaseModel

router = APIRouter()
logger = structlog.get_logger()


class JobStatusResponse(BaseModel):
    """Response payload for job status retrieval."""

    job_id: str
    trace_id: str
    status: str
    schema_type: str | None = None
    filename: str
    batch_id: str | None = None
    created_at: str
    completed_at: str | None = None


@router.get("/v1/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    request: Request,
    tenant: TenantContext = Depends(resolve_tenant),
) -> APIResponse[JobStatusResponse]:
    """Retrieve job status by ID, scoped to the authenticated tenant.

    Returns 404 if the job does not exist or does not belong to this tenant.
    """
    # First check the in-memory store from extract.py (demo mode)
    from api.routes.extract import get_job as get_inmemory_job

    job_dict = get_inmemory_job(job_id=job_id, tenant_id=tenant.id)

    # Fall back to app.state.job_store if available (production mode)
    if job_dict is None:
        job_store = getattr(request.app.state, "job_store", None)
        if job_store is not None:
            job = await job_store.get_job(job_id=job_id, tenant_id=tenant.id)
            if job is not None:
                job_dict = {
                    "job_id": str(job.id),
                    "trace_id": job.trace_id,
                    "status": job.status,
                    "schema_type": job.schema_type,
                    "filename": job.filename,
                    "batch_id": job.batch_id,
                    "created_at": job.created_at.isoformat() if hasattr(job.created_at, "isoformat") else str(job.created_at),
                    "completed_at": job.completed_at.isoformat() if job.completed_at and hasattr(job.completed_at, "isoformat") else None,
                }

    if job_dict is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    now = datetime.now(timezone.utc)

    return APIResponse[JobStatusResponse](
        data=JobStatusResponse(
            job_id=job_dict.get("job_id", job_id),
            trace_id=job_dict.get("trace_id", ""),
            status=job_dict.get("status", "unknown"),
            schema_type=job_dict.get("schema_type"),
            filename=job_dict.get("filename", ""),
            batch_id=job_dict.get("batch_id"),
            created_at=job_dict.get("created_at", now.isoformat()),
            completed_at=job_dict.get("completed_at"),
        ),
        meta=ResponseMeta(
            request_id=job_dict.get("trace_id", ""),
            timestamp=now.isoformat(),
        ),
    )


@router.get("/v1/jobs/{job_id}/progress")
async def get_job_progress(
    job_id: str,
    tenant: TenantContext = Depends(resolve_tenant),
) -> dict:
    """Get real-time processing progress for a job.

    Returns page counts, current stage, estimated time remaining,
    and partial extraction results (fields_extracted_so_far, latest_field).
    Does not require tenant ownership check for simplicity in demo mode.
    """
    progress = progress_store.get(job_id)
    if progress is None:
        # Job might be complete or not started yet
        return {
            "job_id": job_id,
            "total_pages": 0,
            "pages_processed": 0,
            "current_stage": "unknown",
            "stage_detail": "",
            "progress_percent": 0,
            "elapsed_seconds": 0,
            "estimated_remaining_seconds": None,
            "fields_extracted_so_far": 0,
            "tables_extracted_so_far": 0,
            "latest_field": None,
        }

    return progress.to_dict()


@router.post("/v1/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    tenant: TenantContext = Depends(resolve_tenant),
) -> dict:
    """Cancel a processing job.

    Sets the job status to 'cancelled'. The background task checks this
    flag and stops processing.
    """
    from api.routes.extract import _JOBS

    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.get("tenant_id") != tenant.id:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.get("status") != "processing":
        return {"job_id": job_id, "status": job.get("status"), "message": "Job is not processing"}

    job["status"] = "cancelled"
    job["completed_at"] = datetime.now(timezone.utc).isoformat()

    return {"job_id": job_id, "status": "cancelled", "message": "Job cancelled"}
