"""Tenant redaction config endpoints.

GET /v1/tenants/{tenant_id}/redaction-config — retrieve current config
PUT /v1/tenants/{tenant_id}/redaction-config — update config

Both endpoints are tenant-scoped: the authenticated tenant can only
access their own configuration.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from api.middleware.auth import resolve_tenant
from api.models.response import APIResponse, ResponseMeta
from api.models.tenant import TenantContext, TenantRedactionSettings

router = APIRouter()
logger = structlog.get_logger()


@router.get("/v1/tenants/{tenant_id}/redaction-config")
async def get_redaction_config(
    tenant_id: str,
    request: Request,
    tenant: TenantContext = Depends(resolve_tenant),
) -> APIResponse[TenantRedactionSettings]:
    """Retrieve the tenant's redaction configuration.

    Tenant-scoped: only the authenticated tenant can access their own config.
    Returns 403 if tenant_id does not match the authenticated tenant.
    """
    # Tenant-scoped access control
    if tenant.id != tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied: cannot access another tenant's configuration",
        )

    now = datetime.now(timezone.utc)
    trace_id = getattr(request.state, "trace_id", "unknown")

    logger.info(
        "tenants.redaction_config.get",
        tenant_id=tenant_id,
    )

    return APIResponse[TenantRedactionSettings](
        data=tenant.redaction_config,
        meta=ResponseMeta(
            request_id=trace_id,
            timestamp=now.isoformat(),
        ),
    )


@router.put("/v1/tenants/{tenant_id}/redaction-config")
async def update_redaction_config(
    tenant_id: str,
    config: TenantRedactionSettings,
    request: Request,
    tenant: TenantContext = Depends(resolve_tenant),
) -> APIResponse[TenantRedactionSettings]:
    """Update the tenant's redaction configuration.

    Tenant-scoped: only the authenticated tenant can update their own config.
    Returns 403 if tenant_id does not match the authenticated tenant.

    In production, this would persist to the database. Currently returns
    the submitted config as confirmation.
    """
    # Tenant-scoped access control
    if tenant.id != tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied: cannot modify another tenant's configuration",
        )

    now = datetime.now(timezone.utc)
    trace_id = getattr(request.state, "trace_id", "unknown")

    # In production: persist to database
    # await tenant_repo.update_redaction_config(tenant_id, config)

    logger.info(
        "tenants.redaction_config.updated",
        tenant_id=tenant_id,
        global_entities_count=len(config.global_entities),
        schema_overrides_count=len(config.schema_overrides),
    )

    return APIResponse[TenantRedactionSettings](
        data=config,
        meta=ResponseMeta(
            request_id=trace_id,
            timestamp=now.isoformat(),
        ),
    )
