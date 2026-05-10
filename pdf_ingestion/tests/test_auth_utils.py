"""Unit tests for JWT utility functions."""

import time
import uuid

import jwt
import pytest

from api.admin.auth_utils import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


class TestCreateAccessToken:
    """Tests for create_access_token."""

    def test_creates_valid_jwt(self):
        token = create_access_token(
            user_id="user-123",
            email="admin@example.com",
            role="admin",
            tenant_ids=["tenant-a", "tenant-b"],
        )
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_expected_claims(self):
        user_id = str(uuid.uuid4())
        token = create_access_token(
            user_id=user_id,
            email="op@example.com",
            role="operator",
            tenant_ids=["t1"],
        )
        payload = decode_token(token)

        assert payload["sub"] == user_id
        assert payload["email"] == "op@example.com"
        assert payload["role"] == "operator"
        assert payload["tenant_ids"] == ["t1"]
        assert "jti" in payload
        assert "iat" in payload
        assert "exp" in payload

    def test_jti_is_unique_per_token(self):
        token1 = create_access_token("u1", "a@b.com", "admin", [])
        token2 = create_access_token("u1", "a@b.com", "admin", [])
        payload1 = decode_token(token1)
        payload2 = decode_token(token2)
        assert payload1["jti"] != payload2["jti"]

    def test_empty_tenant_ids(self):
        token = create_access_token("u1", "a@b.com", "viewer", [])
        payload = decode_token(token)
        assert payload["tenant_ids"] == []


class TestDecodeToken:
    """Tests for decode_token."""

    def test_decodes_valid_token(self):
        token = create_access_token("u1", "test@test.com", "admin", ["t1"])
        payload = decode_token(token)
        assert payload["sub"] == "u1"

    def test_raises_on_expired_token(self):
        """Manually create an expired token and verify rejection."""
        from api.config import get_settings

        settings = get_settings()
        payload = {
            "sub": "u1",
            "email": "x@y.com",
            "role": "admin",
            "tenant_ids": [],
            "jti": str(uuid.uuid4()),
            "iat": time.time() - 7200,
            "exp": time.time() - 3600,  # expired 1 hour ago
        }
        token = jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")

        with pytest.raises(jwt.ExpiredSignatureError):
            decode_token(token)

    def test_raises_on_invalid_signature(self):
        payload = {
            "sub": "u1",
            "email": "x@y.com",
            "role": "admin",
            "tenant_ids": [],
            "jti": str(uuid.uuid4()),
            "iat": time.time(),
            "exp": time.time() + 3600,
        }
        token = jwt.encode(payload, "wrong-secret-key", algorithm="HS256")

        with pytest.raises(jwt.InvalidSignatureError):
            decode_token(token)

    def test_raises_on_malformed_token(self):
        with pytest.raises(jwt.InvalidTokenError):
            decode_token("not.a.valid.jwt.token")


class TestPasswordHashing:
    """Tests for hash_password and verify_password."""

    def test_hash_and_verify_correct_password(self):
        password = "SecureP@ss123!"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_hash_is_not_plaintext(self):
        password = "my-secret"
        hashed = hash_password(password)
        assert hashed != password
        assert hashed.startswith("$2b$")  # bcrypt prefix

    def test_same_password_produces_different_hashes(self):
        password = "same-password"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2  # bcrypt uses random salt
        # But both should verify
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True
