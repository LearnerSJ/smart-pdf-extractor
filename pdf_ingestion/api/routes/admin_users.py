"""Admin user management routes.

Handles CRUD operations for dashboard users (Admin-only).
Uses the shared in-memory _DEMO_USERS store from admin_auth.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, EmailStr

from api.admin.auth_utils import decode_token, hash_password
from api.models.response import APIResponse, ResponseMeta
from api.routes.admin_auth import _DEMO_USERS, _REVOKED_TOKENS

router = APIRouter()
logger = structlog.get_logger()


# ─── Request / Response Models ────────────────────────────────────────────────


class CreateUserRequest(BaseModel):
    """Request body for creating a new user."""

    email: str
    password: str
    role: str  # admin, operator, viewer
    tenant_ids: list[str] = []


class UpdateUserRequest(BaseModel):
    """Request body for updating a user's role and tenant assignments."""

    role: str | None = None
    tenant_ids: list[str] | None = None


class UserResponse(BaseModel):
    """Response payload for a single user."""

    id: str
    email: str
    role: str
    tenant_ids: list[str]
    is_active: bool


class UserListResponse(BaseModel):
    """Response payload for listing users."""

    users: list[UserResponse]


class DeactivateResponse(BaseModel):
    """Response payload for user deactivation."""

    success: bool = True


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _extract_bearer_token(authorization: str) -> str:
    """Extract the token from a 'Bearer <token>' authorization header value."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header format. Expected 'Bearer <token>'",
        )
    return authorization[len("Bearer "):]


def _require_admin(authorization: str) -> dict:
    """Decode JWT and verify the caller has admin role.

    Returns the decoded token payload if valid and admin.
    Raises 401 for invalid tokens, 403 for non-admin users.
    """
    token = _extract_bearer_token(authorization)

    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Check if token is revoked
    jti = payload.get("jti")
    if jti and jti in _REVOKED_TOKENS:
        raise HTTPException(status_code=401, detail="Token has been revoked")

    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    return payload


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/v1/admin/users", status_code=201)
async def create_user(
    body: CreateUserRequest,
    authorization: str = Header(..., description="Bearer token"),
) -> APIResponse[UserResponse]:
    """Create a new dashboard user (Admin only).

    Accepts email, password, role, and tenant_ids.
    Returns 409 if email already exists.
    Returns 403 if caller is not an admin.
    """
    request_id = str(uuid.uuid4())
    _require_admin(authorization)

    # Check for duplicate email
    if body.email in _DEMO_USERS:
        raise HTTPException(status_code=409, detail="Email already exists")

    # Create the user
    user_id = str(uuid.uuid4())
    _DEMO_USERS[body.email] = {
        "id": user_id,
        "email": body.email,
        "password_hash": hash_password(body.password),
        "role": body.role,
        "is_active": True,
        "tenant_ids": body.tenant_ids,
    }

    logger.info("admin.users.created", email=body.email, role=body.role, user_id=user_id)

    return APIResponse[UserResponse](
        data=UserResponse(
            id=user_id,
            email=body.email,
            role=body.role,
            tenant_ids=body.tenant_ids,
            is_active=True,
        ),
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )


@router.get("/v1/admin/users", status_code=200)
async def list_users(
    authorization: str = Header(..., description="Bearer token"),
) -> APIResponse[UserListResponse]:
    """List all dashboard users (Admin only).

    Returns list of users with id, email, role, tenant_ids, is_active.
    Returns 403 if caller is not an admin.
    """
    request_id = str(uuid.uuid4())
    _require_admin(authorization)

    users = [
        UserResponse(
            id=user["id"],
            email=user["email"],
            role=user["role"],
            tenant_ids=user["tenant_ids"],
            is_active=user["is_active"],
        )
        for user in _DEMO_USERS.values()
    ]

    logger.info("admin.users.listed", count=len(users))

    return APIResponse[UserListResponse](
        data=UserListResponse(users=users),
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )


@router.put("/v1/admin/users/{user_id}", status_code=200)
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    authorization: str = Header(..., description="Bearer token"),
) -> APIResponse[UserResponse]:
    """Update a user's role and tenant assignments (Admin only).

    Returns 404 if user_id not found.
    Returns 403 if caller is not an admin.
    """
    request_id = str(uuid.uuid4())
    _require_admin(authorization)

    # Find user by id
    target_user = None
    target_email = None
    for email, user in _DEMO_USERS.items():
        if user["id"] == user_id:
            target_user = user
            target_email = email
            break

    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Update fields
    if body.role is not None:
        target_user["role"] = body.role
    if body.tenant_ids is not None:
        target_user["tenant_ids"] = body.tenant_ids

    logger.info("admin.users.updated", user_id=user_id, role=target_user["role"])

    return APIResponse[UserResponse](
        data=UserResponse(
            id=target_user["id"],
            email=target_user["email"],
            role=target_user["role"],
            tenant_ids=target_user["tenant_ids"],
            is_active=target_user["is_active"],
        ),
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )


@router.delete("/v1/admin/users/{user_id}", status_code=200)
async def deactivate_user(
    user_id: str,
    authorization: str = Header(..., description="Bearer token"),
) -> APIResponse[DeactivateResponse]:
    """Deactivate a user by setting is_active=false (Admin only).

    Returns 404 if user_id not found.
    Returns 403 if caller is not an admin.
    """
    request_id = str(uuid.uuid4())
    _require_admin(authorization)

    # Find user by id
    target_user = None
    for user in _DEMO_USERS.values():
        if user["id"] == user_id:
            target_user = user
            break

    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    target_user["is_active"] = False

    logger.info("admin.users.deactivated", user_id=user_id)

    return APIResponse[DeactivateResponse](
        data=DeactivateResponse(success=True),
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )
