"""Schema cache management endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from api.middleware.auth import resolve_tenant
from api.models.response import APIResponse, ResponseMeta
from api.models.tenant import TenantContext
from pipeline.discovery.schema_cache import SchemaCache
from pipeline.models import SchemaFingerprint

router = APIRouter()


def _get_schema_cache():
    """Get schema cache from app state. Placeholder for DI."""
    from api.main import app
    return getattr(app.state, "schema_cache", None)


@router.get("/v1/tenants/{tenant_id}/schema-cache")
async def list_cached_schemas(
    tenant_id: str,
    tenant: TenantContext = Depends(resolve_tenant),
) -> APIResponse:
    """List all cached discovered schemas for the authenticated tenant."""
    if str(tenant.id) != tenant_id:
        raise HTTPException(status_code=403, detail="Tenant ID mismatch")

    cache = _get_schema_cache()
    if cache is None:
        return APIResponse(
            data=[],
            meta=ResponseMeta(request_id="", timestamp=datetime.now(timezone.utc).isoformat()),
        )

    entries = await cache.list_for_tenant(tenant_id)
    return APIResponse(
        data=entries,
        meta=ResponseMeta(request_id="", timestamp=datetime.now(timezone.utc).isoformat()),
    )


@router.delete("/v1/tenants/{tenant_id}/schema-cache/{fingerprint}")
async def invalidate_cached_schema(
    tenant_id: str,
    fingerprint: str,
    tenant: TenantContext = Depends(resolve_tenant),
) -> APIResponse:
    """Invalidate a cached discovered schema."""
    if str(tenant.id) != tenant_id:
        raise HTTPException(status_code=403, detail="Tenant ID mismatch")

    cache = _get_schema_cache()
    if cache is None:
        raise HTTPException(status_code=404, detail="Schema cache not available")

    fp = SchemaFingerprint.from_key(fingerprint)
    deleted = await cache.invalidate(fp, tenant_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Schema not found in cache")

    return APIResponse(
        data={"fingerprint": fingerprint, "deleted": True},
        meta=ResponseMeta(request_id="", timestamp=datetime.now(timezone.utc).isoformat()),
    )


@router.get("/v1/admin/improvement-suggestions")
async def get_improvement_suggestions(
    tenant: TenantContext = Depends(resolve_tenant),
) -> APIResponse:
    """Get auto-generated improvement suggestions from pattern mining."""
    from api.main import app
    pattern_miner = getattr(app.state, "pattern_miner", None)
    schema_learner = getattr(app.state, "schema_learner", None)

    suggestions = pattern_miner.get_suggestions() if pattern_miner else []
    performance = schema_learner.get_performance_summary() if schema_learner else []

    return APIResponse(
        data={
            "suggestions": suggestions,
            "schema_performance": performance,
        },
        meta=ResponseMeta(request_id="", timestamp=datetime.now(timezone.utc).isoformat()),
    )
