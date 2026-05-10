"""Admin authentication routes.

Handles login, logout, and token refresh for dashboard users.
Uses JWT-based authentication independent of tenant API keys.

NOTE: Rate limiting is not yet implemented but should be added
before production deployment (5 attempts per minute per IP recommended).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, EmailStr

from api.admin.auth_utils import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from api.models.response import APIResponse, ResponseMeta

router = APIRouter()
logger = structlog.get_logger()


# ─── Request / Response Models ────────────────────────────────────────────────


class LoginRequest(BaseModel):
    """Login request body."""

    email: str
    password: str


class TokenResponse(BaseModel):
    """Response payload for login and refresh endpoints."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class LogoutResponse(BaseModel):
    """Response payload for logout endpoint."""

    success: bool = True


# ─── In-Memory Demo Store ─────────────────────────────────────────────────────
# For the demo/MVP, we use an in-memory store for users and revoked tokens.
# In production, these would be backed by the dashboard_users and
# token_revocations tables via SQLAlchemy async sessions.

_DEMO_USERS: dict[str, dict] = {}
_REVOKED_TOKENS: dict[str, dict] = {}  # jti -> {revoked_at, expires_at}


def _seed_demo_users() -> None:
    """Seed demo users on module load for testing."""
    demo_accounts = [
        {
            "id": str(uuid.uuid4()),
            "email": "admin@example.com",
            "password": "admin123",
            "role": "admin",
            "is_active": True,
            "tenant_ids": [],
        },
        {
            "id": str(uuid.uuid4()),
            "email": "operator@example.com",
            "password": "operator123",
            "role": "operator",
            "is_active": True,
            "tenant_ids": ["tenant-1", "tenant-2"],
        },
        {
            "id": str(uuid.uuid4()),
            "email": "viewer@example.com",
            "password": "viewer123",
            "role": "viewer",
            "is_active": True,
            "tenant_ids": ["tenant-1"],
        },
    ]
    for account in demo_accounts:
        _DEMO_USERS[account["email"]] = {
            "id": account["id"],
            "email": account["email"],
            "password_hash": hash_password(account["password"]),
            "role": account["role"],
            "is_active": account["is_active"],
            "tenant_ids": account["tenant_ids"],
        }


# Seed on module load
_seed_demo_users()


def _is_token_revoked(jti: str) -> bool:
    """Check if a token's jti has been revoked."""
    return jti in _REVOKED_TOKENS


def _get_expiration_seconds() -> int:
    """Get the configured JWT expiration in seconds."""
    from api.config import get_settings

    settings = get_settings()
    return settings.jwt_expiration_hours * 3600


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/v1/admin/auth/login", status_code=200)
async def login(body: LoginRequest) -> APIResponse[TokenResponse]:
    """Authenticate a dashboard user and return a JWT access token.

    Validates email/password against the dashboard_users store.
    Returns 401 for invalid credentials or inactive accounts.
    """
    request_id = str(uuid.uuid4())
    logger.info("admin.auth.login_attempt", email=body.email)

    # Look up user by email
    user = _DEMO_USERS.get(body.email)
    if user is None:
        logger.warning("admin.auth.login_failed", email=body.email, reason="user_not_found")
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    # Verify password
    if not verify_password(body.password, user["password_hash"]):
        logger.warning("admin.auth.login_failed", email=body.email, reason="invalid_password")
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    # Check if account is active
    if not user["is_active"]:
        logger.warning("admin.auth.login_failed", email=body.email, reason="account_inactive")
        raise HTTPException(
            status_code=401,
            detail="Account is inactive",
        )

    # Generate JWT
    access_token = create_access_token(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        tenant_ids=user["tenant_ids"],
    )

    expires_in = _get_expiration_seconds()

    logger.info("admin.auth.login_success", email=body.email, user_id=user["id"])

    return APIResponse[TokenResponse](
        data=TokenResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=expires_in,
        ),
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )


@router.post("/v1/admin/auth/logout", status_code=200)
async def logout(
    authorization: str = Header(..., description="Bearer token"),
) -> APIResponse[LogoutResponse]:
    """Invalidate the current JWT by adding its jti to the revocation store.

    The token's jti is extracted and stored in token_revocations so that
    subsequent requests with this token are rejected.
    """
    request_id = str(uuid.uuid4())

    # Extract token from Authorization header
    token = _extract_bearer_token(authorization)

    # Decode and validate the token
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
        )

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(
            status_code=401,
            detail="Invalid token: missing jti",
        )

    # Check if already revoked
    if _is_token_revoked(jti):
        raise HTTPException(
            status_code=401,
            detail="Token already revoked",
        )

    # Revoke the token
    _REVOKED_TOKENS[jti] = {
        "revoked_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": datetime.fromtimestamp(payload["exp"], tz=timezone.utc).isoformat(),
    }

    logger.info("admin.auth.logout", user_id=payload.get("sub"), jti=jti)

    return APIResponse[LogoutResponse](
        data=LogoutResponse(success=True),
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )


@router.post("/v1/admin/auth/refresh", status_code=200)
async def refresh(
    authorization: str = Header(..., description="Bearer token"),
) -> APIResponse[TokenResponse]:
    """Issue a new JWT if the current token is valid and not revoked.

    The old token remains valid until its natural expiration (or explicit logout).
    A new token is issued with a fresh expiration time.
    """
    request_id = str(uuid.uuid4())

    # Extract token from Authorization header
    token = _extract_bearer_token(authorization)

    # Decode and validate the token
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
        )

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(
            status_code=401,
            detail="Invalid token: missing jti",
        )

    # Check if the token has been revoked
    if _is_token_revoked(jti):
        raise HTTPException(
            status_code=401,
            detail="Token has been revoked",
        )

    # Issue a new token with the same claims
    user_id = payload.get("sub")
    email = payload.get("email")
    role = payload.get("role")
    tenant_ids = payload.get("tenant_ids", [])

    new_token = create_access_token(
        user_id=user_id,
        email=email,
        role=role,
        tenant_ids=tenant_ids,
    )

    expires_in = _get_expiration_seconds()

    logger.info("admin.auth.refresh", user_id=user_id)

    return APIResponse[TokenResponse](
        data=TokenResponse(
            access_token=new_token,
            token_type="bearer",
            expires_in=expires_in,
        ),
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _extract_bearer_token(authorization: str) -> str:
    """Extract the token from a 'Bearer <token>' authorization header value."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header format. Expected 'Bearer <token>'",
        )
    return authorization[len("Bearer "):]
