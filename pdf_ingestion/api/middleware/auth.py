"""Authentication middleware for tenant identity resolution.

Extracts and validates the API key from the Authorization header,
resolves the associated tenant record, and raises appropriate HTTP
errors for missing, invalid, or suspended credentials.
"""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import HTTPException, Request

from api.errors import ErrorCode
from api.models.tenant import TenantContext


def _hash_key(api_key: str) -> str:
    """Compute SHA-256 hash of an API key for lookup."""
    return hashlib.sha256(api_key.encode()).hexdigest()


# Stub tenant store — replaced by real DB lookup once the database layer is wired.
# Seeded with a demo tenant for local development.
_DEMO_API_KEY = "demo-key"
_STUB_TENANTS: dict[str, TenantContext] = {
    _hash_key(_DEMO_API_KEY): TenantContext(
        id="demo-tenant",
        name="Demo Tenant",
        api_key_hash=_hash_key(_DEMO_API_KEY),
        vlm_enabled=True,
        is_suspended=False,
    ),
}


async def resolve_tenant(request: Request) -> TenantContext:
    """FastAPI dependency that resolves and validates tenant identity.

    Extracts the Bearer token from the Authorization header, looks up
    the tenant in the data store, and verifies the tenant is not suspended.

    Raises:
        HTTPException 401: If the API key is missing (ERR_AUTH_001) or invalid (ERR_AUTH_002).
        HTTPException 403: If the tenant is suspended (ERR_AUTH_003).

    Returns:
        TenantContext bound to the current request.
    """
    auth_header = request.headers.get("Authorization", "")
    api_key = auth_header.removeprefix("Bearer ").strip()

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail=f"{ErrorCode.AUTH_MISSING_CREDENTIALS}: missing credentials",
        )

    # Look up tenant — use app-state repo if available, else fall back to stub.
    tenant: TenantContext | None = None
    tenant_repo: Any = getattr(request.app.state, "tenant_repo", None)

    if tenant_repo is not None:
        tenant = await tenant_repo.get_by_api_key(api_key)
    else:
        # Stub lookup by hashed key
        key_hash = _hash_key(api_key)
        tenant = _STUB_TENANTS.get(key_hash)

    if tenant is None:
        raise HTTPException(
            status_code=401,
            detail=f"{ErrorCode.AUTH_INVALID_CREDENTIALS}: invalid credentials",
        )

    if tenant.is_suspended:
        raise HTTPException(
            status_code=403,
            detail=f"{ErrorCode.AUTH_TENANT_SUSPENDED}: tenant suspended",
        )

    # Bind tenant to request state for downstream access.
    request.state.tenant = tenant
    return tenant
