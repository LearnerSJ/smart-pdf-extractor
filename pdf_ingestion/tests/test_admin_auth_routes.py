"""Unit tests for admin auth routes (login, logout, refresh)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from api.admin.auth_utils import create_access_token, decode_token
from api.routes.admin_auth import _DEMO_USERS, _REVOKED_TOKENS, router

# Build a minimal FastAPI app for testing
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)


@pytest.fixture(autouse=True)
def clear_revoked_tokens():
    """Clear revoked tokens between tests."""
    _REVOKED_TOKENS.clear()
    yield
    _REVOKED_TOKENS.clear()


@pytest.fixture
async def client():
    """Async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestLogin:
    """Tests for POST /v1/admin/auth/login."""

    @pytest.mark.anyio
    async def test_valid_login_returns_token(self, client):
        response = await client.post(
            "/v1/admin/auth/login",
            json={"email": "admin@example.com", "password": "admin123"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    @pytest.mark.anyio
    async def test_valid_login_token_is_decodable(self, client):
        response = await client.post(
            "/v1/admin/auth/login",
            json={"email": "admin@example.com", "password": "admin123"},
        )
        token = response.json()["data"]["access_token"]
        payload = decode_token(token)
        assert payload["email"] == "admin@example.com"
        assert payload["role"] == "admin"

    @pytest.mark.anyio
    async def test_invalid_email_returns_401(self, client):
        response = await client.post(
            "/v1/admin/auth/login",
            json={"email": "nonexistent@example.com", "password": "admin123"},
        )
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_invalid_password_returns_401(self, client):
        response = await client.post(
            "/v1/admin/auth/login",
            json={"email": "admin@example.com", "password": "wrongpassword"},
        )
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_response_has_meta(self, client):
        response = await client.post(
            "/v1/admin/auth/login",
            json={"email": "admin@example.com", "password": "admin123"},
        )
        meta = response.json()["meta"]
        assert "request_id" in meta
        assert "timestamp" in meta


class TestLogout:
    """Tests for POST /v1/admin/auth/logout."""

    @pytest.mark.anyio
    async def test_valid_logout(self, client):
        # Login first
        login_resp = await client.post(
            "/v1/admin/auth/login",
            json={"email": "admin@example.com", "password": "admin123"},
        )
        token = login_resp.json()["data"]["access_token"]

        # Logout
        response = await client.post(
            "/v1/admin/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["success"] is True

    @pytest.mark.anyio
    async def test_logout_revokes_token(self, client):
        # Login first
        login_resp = await client.post(
            "/v1/admin/auth/login",
            json={"email": "admin@example.com", "password": "admin123"},
        )
        token = login_resp.json()["data"]["access_token"]
        payload = decode_token(token)
        jti = payload["jti"]

        # Logout
        await client.post(
            "/v1/admin/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Verify token is revoked
        assert jti in _REVOKED_TOKENS

    @pytest.mark.anyio
    async def test_logout_with_invalid_token_returns_401(self, client):
        response = await client.post(
            "/v1/admin/auth/logout",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_logout_already_revoked_returns_401(self, client):
        # Login first
        login_resp = await client.post(
            "/v1/admin/auth/login",
            json={"email": "admin@example.com", "password": "admin123"},
        )
        token = login_resp.json()["data"]["access_token"]

        # Logout once
        await client.post(
            "/v1/admin/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Logout again with same token
        response = await client.post(
            "/v1/admin/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_logout_without_bearer_prefix_returns_401(self, client):
        response = await client.post(
            "/v1/admin/auth/logout",
            headers={"Authorization": "some-token-without-bearer"},
        )
        assert response.status_code == 401


class TestRefresh:
    """Tests for POST /v1/admin/auth/refresh."""

    @pytest.mark.anyio
    async def test_valid_refresh_returns_new_token(self, client):
        # Login first
        login_resp = await client.post(
            "/v1/admin/auth/login",
            json={"email": "operator@example.com", "password": "operator123"},
        )
        token = login_resp.json()["data"]["access_token"]

        # Refresh
        response = await client.post(
            "/v1/admin/auth/refresh",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0
        # New token should be different from old one
        assert data["access_token"] != token

    @pytest.mark.anyio
    async def test_refresh_preserves_claims(self, client):
        # Login first
        login_resp = await client.post(
            "/v1/admin/auth/login",
            json={"email": "operator@example.com", "password": "operator123"},
        )
        token = login_resp.json()["data"]["access_token"]
        original_payload = decode_token(token)

        # Refresh
        response = await client.post(
            "/v1/admin/auth/refresh",
            headers={"Authorization": f"Bearer {token}"},
        )
        new_token = response.json()["data"]["access_token"]
        new_payload = decode_token(new_token)

        # Claims should be preserved
        assert new_payload["email"] == original_payload["email"]
        assert new_payload["role"] == original_payload["role"]
        assert new_payload["tenant_ids"] == original_payload["tenant_ids"]
        assert new_payload["sub"] == original_payload["sub"]

    @pytest.mark.anyio
    async def test_refresh_with_revoked_token_returns_401(self, client):
        # Login first
        login_resp = await client.post(
            "/v1/admin/auth/login",
            json={"email": "admin@example.com", "password": "admin123"},
        )
        token = login_resp.json()["data"]["access_token"]

        # Logout (revoke the token)
        await client.post(
            "/v1/admin/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Try to refresh with revoked token
        response = await client.post(
            "/v1/admin/auth/refresh",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_refresh_with_invalid_token_returns_401(self, client):
        response = await client.post(
            "/v1/admin/auth/refresh",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code == 401
