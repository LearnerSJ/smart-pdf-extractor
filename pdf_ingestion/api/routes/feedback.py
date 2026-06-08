"""Feedback endpoint.

POST /v1/feedback/{job_id} — accept correction submissions for extraction errors.
GET  /v1/feedback          — list corrections for the authenticated tenant.
Tenant-scoped: only the authenticated tenant can submit/read its own feedback.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AliasChoices, BaseModel, Field

from api.middleware.auth import resolve_tenant
from api.models.response import APIResponse, ResponseMeta
from api.models.tenant import TenantContext

router = APIRouter()
logger = structlog.get_logger()


class CorrectionRequest(BaseModel):
    """Request body for submitting a correction.

    Field names match what the frontend CorrectionModal sends. `correct_value`
    is accepted as an alias so older API clients keep working.
    """

    field_name: str
    # Accept the modal's `corrected_value` and legacy `correct_value`.
    corrected_value: str = Field(
        validation_alias=AliasChoices("corrected_value", "correct_value")
    )
    original_value: str | None = None
    table_id: str | None = None
    notes: str | None = None

    model_config = {"populate_by_name": True}


class FeedbackResponse(BaseModel):
    """Response payload for a submitted correction."""

    feedback_id: str
    job_id: str
    field_name: str
    status: str


class FeedbackItem(BaseModel):
    """A persisted correction, shaped for the admin Feedback screen."""

    feedback_id: int
    job_id: str
    field_name: str
    table_id: str | None = None
    original_value: str | None = None
    corrected_value: str | None = None
    source: str
    notes: str | None = None
    submitted_by: str
    submitted_at: str | None = None


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

    from db.feedback_repo import FeedbackRepo

    try:
        feedback_id = await FeedbackRepo().create(
            job_id=job_id,
            tenant_id=tenant.id,
            field_name=payload.field_name,
            correct_value=payload.corrected_value,
            extracted_value=payload.original_value,
            table_id=payload.table_id,
            notes=payload.notes,
            source="correction_api",
        )
    except Exception as e:  # FK violation = job not visible to this tenant
        logger.warning("feedback.persist_failed", job_id=job_id, error=str(e))
        raise HTTPException(
            status_code=404, detail="Job not found for this tenant"
        ) from e

    logger.info(
        "feedback.submitted",
        job_id=job_id,
        tenant_id=tenant.id,
        field_name=payload.field_name,
        feedback_id=feedback_id,
    )

    # Learning loop: if this job was extracted by a TEMPLATE, the correction means
    # that layout has drifted — quarantine the template for this tenant so its next
    # same-layout document re-learns via VLM (self-verifying synthesis). Best-effort.
    await _quarantine_if_template(request, job_id, tenant, payload.field_name)

    return APIResponse[FeedbackResponse](
        data=FeedbackResponse(
            feedback_id=str(feedback_id),
            job_id=job_id,
            field_name=payload.field_name,
            status="accepted",
        ),
        meta=ResponseMeta(
            request_id=trace_id,
            timestamp=now.isoformat(),
        ),
    )


async def _quarantine_if_template(
    request: Request, job_id: str, tenant: TenantContext, field_name: str
) -> None:
    """Quarantine the template that produced this job, if any (drift -> re-learn)."""
    try:
        from db.job_repo import JobRepo

        schema_type = await JobRepo().get_result_schema_type(job_id, tenant.id)
        if not schema_type or not schema_type.startswith("template:"):
            return  # not a template extraction — nothing to re-learn
        fingerprint_key = schema_type.split("template:", 1)[1]
        store = getattr(request.app.state, "template_store", None)
        if store is None or not hasattr(store, "quarantine"):
            return
        await store.quarantine(
            tenant.id, fingerprint_key, reason=f"correction:{field_name}"
        )
        logger.info(
            "template.quarantined_by_feedback",
            job_id=job_id, tenant_id=tenant.id,
            fingerprint=fingerprint_key, field_name=field_name,
        )
    except Exception as e:  # never fail the feedback request over this
        logger.warning("feedback.quarantine_failed", job_id=job_id, error=str(e))


@router.get("/v1/feedback")
async def list_feedback(
    tenant: TenantContext = Depends(resolve_tenant),
) -> APIResponse[list[FeedbackItem]]:
    """List corrections submitted by the authenticated tenant, newest first."""
    from db.feedback_repo import FeedbackRepo

    rows = await FeedbackRepo().list_for_tenant(tenant.id)
    now = datetime.now(timezone.utc)
    return APIResponse[list[FeedbackItem]](
        data=[FeedbackItem(**r) for r in rows],
        meta=ResponseMeta(request_id="", timestamp=now.isoformat()),
    )
