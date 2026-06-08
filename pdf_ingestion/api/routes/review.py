"""Abstention review queue.

Unattended extraction abstains rather than guessing when a value can't be
grounded. Those jobs are flagged needs_review by the worker. This endpoint is
the human-on-exception surface: list what needs a look, and acknowledge once
handled. Tenant-scoped; RLS confines every query to the caller's rows.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException

from api.middleware.auth import resolve_tenant
from api.models.response import APIResponse, ResponseMeta
from api.models.tenant import TenantContext
from pydantic import BaseModel

router = APIRouter()
logger = structlog.get_logger()


class ReviewItem(BaseModel):
    job_id: str
    filename: str
    schema_type: str | None = None
    completed_at: str | None = None
    attempts: int
    abstention_count: int
    abstentions: list


class ReviewList(BaseModel):
    count: int
    items: list[ReviewItem]


@router.get("/v1/review")
async def list_review_queue(
    limit: int = 100,
    tenant: TenantContext = Depends(resolve_tenant),
) -> APIResponse[ReviewList]:
    """List jobs flagged for human review (had abstentions), newest first."""
    from db.job_repo import JobRepo

    rows = await JobRepo().list_needs_review(tenant.id, limit=limit)
    now = datetime.now(timezone.utc)
    return APIResponse[ReviewList](
        data=ReviewList(count=len(rows), items=[ReviewItem(**r) for r in rows]),
        meta=ResponseMeta(request_id="", timestamp=now.isoformat()),
    )


@router.post("/v1/review/{job_id}/acknowledge")
async def acknowledge_review(
    job_id: str,
    tenant: TenantContext = Depends(resolve_tenant),
) -> APIResponse[dict]:
    """Clear the review flag for a job once a human has handled it."""
    from db.job_repo import JobRepo

    updated = await JobRepo().acknowledge_review(job_id, tenant.id)
    if not updated:
        raise HTTPException(status_code=404, detail="No job awaiting review with that id")
    now = datetime.now(timezone.utc)
    return APIResponse[dict](
        data={"job_id": job_id, "acknowledged": True},
        meta=ResponseMeta(request_id="", timestamp=now.isoformat()),
    )
