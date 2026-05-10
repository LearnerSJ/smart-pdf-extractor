"""GET /v1/batches/{batch_id} endpoint.

Retrieves batch status and job list scoped to the authenticated tenant.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from api.errors import ErrorCode
from api.middleware.auth import resolve_tenant
from api.models.response import APIResponse, BatchStatus, JobSummary, ResponseMeta
from api.models.tenant import TenantContext

router = APIRouter()
logger = structlog.get_logger()


@router.get("/v1/batches/{batch_id}")
async def get_batch_status(
    batch_id: str,
    request: Request,
    tenant: TenantContext = Depends(resolve_tenant),
) -> APIResponse[BatchStatus]:
    """Retrieve batch status and constituent job list.

    Scoped to the authenticated tenant. Returns 404 with ERR_DELIVERY_003
    if the batch_id is not found for this tenant.
    """
    batch_store = getattr(request.app.state, "batch_store", None)
    batch = None
    jobs: list = []

    if batch_store is not None:
        batch = await batch_store.get_batch(batch_id=batch_id, tenant_id=tenant.id)
        if batch is not None:
            jobs = await batch_store.get_batch_jobs(batch_id=batch_id, tenant_id=tenant.id)

    if batch is None:
        raise HTTPException(
            status_code=404,
            detail=f"{ErrorCode.DELIVERY_BATCH_NOT_FOUND}: batch not found",
        )

    now = datetime.now(timezone.utc)

    job_summaries = [
        JobSummary(
            job_id=str(j.id),
            status=j.status,
            schema_type=j.schema_type,
        )
        for j in jobs
    ]

    return APIResponse[BatchStatus](
        data=BatchStatus(
            batch_id=batch.batch_id,
            tenant_id=batch.tenant_id,
            status=batch.status,
            jobs=job_summaries,
            created_at=batch.created_at.isoformat() if hasattr(batch.created_at, "isoformat") else str(batch.created_at),
            completed_at=batch.completed_at.isoformat() if batch.completed_at and hasattr(batch.completed_at, "isoformat") else None,
            delivery_status=batch.delivery_status,
        ),
        meta=ResponseMeta(
            request_id=str(batch_id),
            timestamp=now.isoformat(),
        ),
    )
