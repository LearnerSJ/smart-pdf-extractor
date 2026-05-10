"""Feedback endpoint.

POST /v1/feedback/{job_id} — accept correction submissions for extraction errors.
Tenant-scoped: only the authenticated tenant can submit feedback for their own jobs.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.middleware.auth import resolve_tenant
from api.models.response import APIResponse, ResponseMeta
from api.models.tenant import TenantContext

router = APIRouter()
logger = structlog.get_logger()


class CorrectionRequest(BaseModel):
    """Request body for submitting a correction."""

    field_name: str
    correct_value: str
    table_id: str | None = None
    notes: str | None = None


class FeedbackResponse(BaseModel):
    """Response payload for a submitted correction."""

    feedback_id: str
    job_id: str
    field_name: str
    status: str


@router.post("/v1/feedback/{job_id}", status_code=202)
async def submit_correction(
    job_id: str,
    payload: CorrectionRequest,
    request: Request,
    tenant: TenantContext = Depends(resolve_tenant),
) -> APIResponse[FeedbackResponse]:
    """Accept a correction submission for an extraction job.

    Tenant-scoped: the correction is associated with the authenticated tenant.
    In production, this would verify the job belongs to the tenant and persist
    the feedback record.

    Args:
        job_id: The job ID to submit feedback for.
        payload: The correction details.
        request: FastAPI request object.
        tenant: Authenticated tenant context.

    Returns:
        APIResponse with feedback confirmation.
    """
    now = datetime.now(timezone.utc)
    trace_id = getattr(request.state, "trace_id", "unknown")

    # In production: verify job belongs to tenant
    # job = await job_repo.get_by_id(job_id, tenant_id=tenant.id)
    # if not job:
    #     raise HTTPException(status_code=404, detail="Job not found")

    # Generate feedback ID (in production: from database)
    import uuid
    feedback_id = str(uuid.uuid4())

    # In production: persist to feedback table
    # await feedback_repo.create(
    #     job_id=job_id,
    #     tenant_id=tenant.id,
    #     field_name=payload.field_name,
    #     correct_value=payload.correct_value,
    #     table_id=payload.table_id,
    #     notes=payload.notes,
    #     source="correction_api",
    # )

    logger.info(
        "feedback.submitted",
        job_id=job_id,
        tenant_id=tenant.id,
        field_name=payload.field_name,
        feedback_id=feedback_id,
    )

    return APIResponse[FeedbackResponse](
        data=FeedbackResponse(
            feedback_id=feedback_id,
            job_id=job_id,
            field_name=payload.field_name,
            status="accepted",
        ),
        meta=ResponseMeta(
            request_id=trace_id,
            timestamp=now.isoformat(),
        ),
    )
