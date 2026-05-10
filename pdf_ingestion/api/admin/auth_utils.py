"""JWT authentication and password hashing utilities for the Admin Dashboard."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from api.config import get_settings


def create_access_token(
    user_id: str,
    email: str,
    role: str,
    tenant_ids: list[str],
) -> str:
    """Create a signed JWT access token with user claims.

    Args:
        user_id: The unique identifier of the dashboard user.
        email: The user's email address.
        role: The user's role (admin, operator, viewer).
        tenant_ids: List of tenant IDs the user is assigned to.

    Returns:
        A signed JWT string containing the user's claims.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=settings.jwt_expiration_hours)

    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "tenant_ids": tenant_ids,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": expire,
    }

    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT access token.

    Args:
        token: The JWT string to decode.

    Returns:
        The decoded payload as a dictionary.

    Raises:
        jwt.ExpiredSignatureError: If the token has expired.
        jwt.InvalidTokenError: If the token is malformed or has an invalid signature.
    """
    settings = get_settings()

    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )


def hash_password(password: str) -> str:
    """Hash a password using bcrypt.

    Args:
        password: The plaintext password to hash.

    Returns:
        The bcrypt hash string.
    """
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def verify_password(password: str, hash: str) -> bool:
    """Verify a password against its bcrypt hash.

    Args:
        password: The plaintext password to verify.
        hash: The bcrypt hash to verify against.

    Returns:
        True if the password matches the hash, False otherwise.
    """
    password_bytes = password.encode("utf-8")
    hash_bytes = hash.encode("utf-8")
    return bcrypt.checkpw(password_bytes, hash_bytes)
