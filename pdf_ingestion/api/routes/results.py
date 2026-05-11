"""GET /v1/results/{id} endpoint.

Retrieves extraction results scoped to the authenticated tenant.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from api.middleware.auth import resolve_tenant
from api.models.response import APIResponse, ResponseMeta
from api.models.tenant import TenantContext

from pydantic import BaseModel

router = APIRouter()
logger = structlog.get_logger()


class ResultResponse(BaseModel):
    """Response payload for extraction result retrieval."""

    job_id: str
    trace_id: str
    output: dict  # type: ignore[type-arg]


@router.get("/v1/results/{job_id}")
async def get_result(
    job_id: str,
    request: Request,
    tenant: TenantContext = Depends(resolve_tenant),
) -> APIResponse[ResultResponse]:
    """Retrieve extraction result by job ID, scoped to the authenticated tenant.

    Returns 404 if the result does not exist or does not belong to this tenant.
    """
    # First check the in-memory store from extract.py (demo mode)
    from api.routes.extract import get_result as get_inmemory_result

    result_dict = get_inmemory_result(job_id=job_id, tenant_id=tenant.id)

    # Fall back to app.state.result_store if available (production mode)
    if result_dict is None:
        result_store = getattr(request.app.state, "result_store", None)
        if result_store is not None:
            result = await result_store.get_result(job_id=job_id, tenant_id=tenant.id)
            if result is not None:
                result_dict = {
                    "job_id": str(result.job_id),
                    "trace_id": result.trace_id if hasattr(result, "trace_id") else "",
                    "output": result.output if isinstance(result.output, dict) else {},
                }

    if result_dict is None:
        raise HTTPException(
            status_code=404,
            detail="Result not found",
        )

    now = datetime.now(timezone.utc)

    return APIResponse[ResultResponse](
        data=ResultResponse(
            job_id=result_dict.get("job_id", job_id),
            trace_id=result_dict.get("trace_id", ""),
            output=result_dict.get("output", {}),
        ),
        meta=ResponseMeta(
            request_id=result_dict.get("trace_id", ""),
            timestamp=now.isoformat(),
        ),
    )


@router.get("/v1/jobs/{job_id}/pdf")
async def get_job_pdf(
    job_id: str,
    request: Request,
    tenant: TenantContext = Depends(resolve_tenant),
) -> Response:
    """Return the original PDF file for a job (for viewer).

    Retrieves stored PDF bytes from app.state.pdf_store.
    In production this would be S3/blob storage.
    """
    pdf_store = getattr(request.app.state, "pdf_store", {})
    pdf_bytes = pdf_store.get(job_id)
    if not pdf_bytes:
        raise HTTPException(status_code=404, detail="PDF not found")
    return Response(content=pdf_bytes, media_type="application/pdf")
