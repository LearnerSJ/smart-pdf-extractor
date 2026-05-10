"""Role-Based Access Control (RBAC) middleware for the Admin Dashboard.

Provides a reusable FastAPI dependency that enforces permission checks
based on JWT claims (role + tenant assignments). Designed to be used
with FastAPI's Depends() system.

Usage:
    @router.get("/v1/admin/usage")
    async def get_usage(
        tenant_id: str,
        user=Depends(require_permission(Permission.READ, tenant_id_param="tenant_id")),
    ):
        ...
"""

from __future__ import annotations

from enum import Enum

import structlog
from fastapi import Header, HTTPException, Request

from api.admin.auth_utils import decode_token

logger = structlog.get_logger()


class Permission(Enum):
    """Permission levels for RBAC enforcement."""

    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


# Role → allowed permissions mapping
_ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    "admin": {Permission.READ, Permission.WRITE, Permission.ADMIN},
    "operator": {Permission.READ, Permission.WRITE},
    "viewer": {Permission.READ},
}


def _get_revoked_tokens() -> dict:
    """Lazily import revoked tokens store to avoid circular imports."""
    from api.routes.admin_auth import _REVOKED_TOKENS

    return _REVOKED_TOKENS


def require_permission(permission: Permission, tenant_id_param: str | None = None):
    """Factory that creates a FastAPI dependency enforcing RBAC.

    Args:
        permission: The minimum permission level required for the endpoint.
        tenant_id_param: Optional name of the path/query parameter containing
            the tenant_id to check access against. If None, no tenant-scoped
            check is performed (only role-level check).

    Returns:
        A FastAPI dependency function that validates the JWT, checks role
        permissions, and optionally verifies tenant assignment.

    Raises:
        HTTPException 401: For missing, invalid, expired, or revoked tokens.
        HTTPException 403: For insufficient permissions or unassigned tenant access.
    """

    async def dependency(
        request: Request,
        authorization: str = Header(..., description="Bearer token"),
    ) -> dict:
        """Validate JWT and enforce RBAC permissions.

        Returns:
            The decoded JWT payload (user context) for use in route handlers.
        """
        # 1. Extract Bearer token
        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Invalid authorization header format. Expected 'Bearer <token>'",
            )
        token = authorization[len("Bearer "):]

        if not token:
            raise HTTPException(
                status_code=401,
                detail="Missing token",
            )

        # 2. Decode the JWT
        try:
            payload = decode_token(token)
        except Exception:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired token",
            )

        # 3. Check if token is revoked
        jti = payload.get("jti")
        if jti and jti in _get_revoked_tokens():
            raise HTTPException(
                status_code=401,
                detail="Token has been revoked",
            )

        # 4. Check role-based permission
        role = payload.get("role", "")
        allowed_permissions = _ROLE_PERMISSIONS.get(role, set())

        if permission not in allowed_permissions:
            logger.warning(
                "rbac.permission_denied",
                role=role,
                required_permission=permission.value,
                user_id=payload.get("sub"),
            )
            raise HTTPException(
                status_code=403,
                detail="Insufficient permissions",
            )

        # 5. Check tenant assignment (if tenant_id_param is specified)
        if tenant_id_param is not None:
            # Extract tenant_id from path params or query params
            tenant_id = request.path_params.get(tenant_id_param)
            if tenant_id is None:
                tenant_id = request.query_params.get(tenant_id_param)

            if tenant_id is not None:
                # Admin has access to all tenants
                if role != "admin":
                    user_tenant_ids = payload.get("tenant_ids", [])
                    if tenant_id not in user_tenant_ids:
                        logger.warning(
                            "rbac.tenant_access_denied",
                            role=role,
                            tenant_id=tenant_id,
                            user_id=payload.get("sub"),
                        )
                        raise HTTPException(
                            status_code=403,
                            detail="Access denied for tenant",
                        )

        return payload

    return dependency
