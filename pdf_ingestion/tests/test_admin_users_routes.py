"""Unit tests for admin user management routes."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from api.admin.auth_utils import create_access_token, decode_token
from api.routes.admin_auth import _DEMO_USERS, _REVOKED_TOKENS
from api.routes.admin_users import router

from fastapi import FastAPI

app = FastAPI()
app.include_router(router)

# Also include auth router so we can get tokens via login if needed
from api.routes.admin_auth import router as auth_router

app.include_router(auth_router)


@pytest.fixture(autouse=True)
def reset_demo_state():
    """Reset demo users and revoked tokens between tests."""
    # Save original state
    original_users = dict(_DEMO_USERS)
    _REVOKED_TOKENS.clear()
    yield
    # Restore original state
    _DEMO_USERS.clear()
    _DEMO_USERS.update(original_users)
    _REVOKED_TOKENS.clear()


@pytest.fixture
def admin_token() -> str:
    """Generate a valid admin JWT token."""
    # Find the admin user in demo users
    admin_user = _DEMO_USERS["admin@example.com"]
    return create_access_token(
        user_id=admin_user["id"],
        email=admin_user["email"],
        role="admin",
        tenant_ids=admin_user["tenant_ids"],
    )


@pytest.fixture
def operator_token() -> str:
    """Generate a valid operator JWT token."""
    operator_user = _DEMO_USERS["operator@example.com"]
    return create_access_token(
        user_id=operator_user["id"],
        email=operator_user["email"],
        role="operator",
        tenant_ids=operator_user["tenant_ids"],
    )


@pytest.fixture
def viewer_token() -> str:
    """Generate a valid viewer JWT token."""
    viewer_user = _DEMO_USERS["viewer@example.com"]
    return create_access_token(
        user_id=viewer_user["id"],
        email=viewer_user["email"],
        role="viewer",
        tenant_ids=viewer_user["tenant_ids"],
    )


@pytest.fixture
async def client():
    """Async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestCreateUser:
    """Tests for POST /v1/admin/users."""

    @pytest.mark.anyio
    async def test_admin_can_create_user(self, client, admin_token):
        response = await client.post(
            "/v1/admin/users",
            json={
                "email": "newuser@example.com",
                "password": "newpass123",
                "role": "operator",
                "tenant_ids": ["tenant-1"],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["email"] == "newuser@example.com"
        assert data["role"] == "operator"
        assert data["tenant_ids"] == ["tenant-1"]
        assert data["is_active"] is True
        assert "id" in data

    @pytest.mark.anyio
    async def test_create_user_stores_in_demo_users(self, client, admin_token):
        await client.post(
            "/v1/admin/users",
            json={
                "email": "stored@example.com",
                "password": "pass123",
                "role": "viewer",
                "tenant_ids": [],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert "stored@example.com" in _DEMO_USERS
        assert _DEMO_USERS["stored@example.com"]["role"] == "viewer"

    @pytest.mark.anyio
    async def test_create_user_duplicate_email_returns_409(self, client, admin_token):
        response = await client.post(
            "/v1/admin/users",
            json={
                "email": "admin@example.com",
                "password": "pass123",
                "role": "viewer",
                "tenant_ids": [],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 409

    @pytest.mark.anyio
    async def test_operator_cannot_create_user(self, client, operator_token):
        response = await client.post(
            "/v1/admin/users",
            json={
                "email": "newuser@example.com",
                "password": "pass123",
                "role": "viewer",
                "tenant_ids": [],
            },
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.anyio
    async def test_viewer_cannot_create_user(self, client, viewer_token):
        response = await client.post(
            "/v1/admin/users",
            json={
                "email": "newuser@example.com",
                "password": "pass123",
                "role": "viewer",
                "tenant_ids": [],
            },
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.anyio
    async def test_invalid_token_returns_401(self, client):
        response = await client.post(
            "/v1/admin/users",
            json={
                "email": "newuser@example.com",
                "password": "pass123",
                "role": "viewer",
                "tenant_ids": [],
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_response_has_meta(self, client, admin_token):
        response = await client.post(
            "/v1/admin/users",
            json={
                "email": "meta@example.com",
                "password": "pass123",
                "role": "viewer",
                "tenant_ids": [],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        meta = response.json()["meta"]
        assert "request_id" in meta
        assert "timestamp" in meta


class TestListUsers:
    """Tests for GET /v1/admin/users."""

    @pytest.mark.anyio
    async def test_admin_can_list_users(self, client, admin_token):
        response = await client.get(
            "/v1/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "users" in data
        # Should have at least the 3 seeded demo users
        assert len(data["users"]) >= 3

    @pytest.mark.anyio
    async def test_list_users_returns_expected_fields(self, client, admin_token):
        response = await client.get(
            "/v1/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        users = response.json()["data"]["users"]
        for user in users:
            assert "id" in user
            assert "email" in user
            assert "role" in user
            assert "tenant_ids" in user
            assert "is_active" in user

    @pytest.mark.anyio
    async def test_operator_cannot_list_users(self, client, operator_token):
        response = await client.get(
            "/v1/admin/users",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.anyio
    async def test_viewer_cannot_list_users(self, client, viewer_token):
        response = await client.get(
            "/v1/admin/users",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert response.status_code == 403


class TestUpdateUser:
    """Tests for PUT /v1/admin/users/{user_id}."""

    @pytest.mark.anyio
    async def test_admin_can_update_user_role(self, client, admin_token):
        # Get the operator user's id
        operator_user = _DEMO_USERS["operator@example.com"]
        user_id = operator_user["id"]

        response = await client.put(
            f"/v1/admin/users/{user_id}",
            json={"role": "viewer"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["role"] == "viewer"

    @pytest.mark.anyio
    async def test_admin_can_update_tenant_ids(self, client, admin_token):
        operator_user = _DEMO_USERS["operator@example.com"]
        user_id = operator_user["id"]

        response = await client.put(
            f"/v1/admin/users/{user_id}",
            json={"tenant_ids": ["tenant-3", "tenant-4"]},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["tenant_ids"] == ["tenant-3", "tenant-4"]

    @pytest.mark.anyio
    async def test_admin_can_update_both_role_and_tenants(self, client, admin_token):
        operator_user = _DEMO_USERS["operator@example.com"]
        user_id = operator_user["id"]

        response = await client.put(
            f"/v1/admin/users/{user_id}",
            json={"role": "admin", "tenant_ids": []},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["role"] == "admin"
        assert data["tenant_ids"] == []

    @pytest.mark.anyio
    async def test_update_nonexistent_user_returns_404(self, client, admin_token):
        response = await client.put(
            "/v1/admin/users/nonexistent-id",
            json={"role": "viewer"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_operator_cannot_update_user(self, client, operator_token):
        operator_user = _DEMO_USERS["operator@example.com"]
        user_id = operator_user["id"]

        response = await client.put(
            f"/v1/admin/users/{user_id}",
            json={"role": "admin"},
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 403


class TestDeactivateUser:
    """Tests for DELETE /v1/admin/users/{user_id}."""

    @pytest.mark.anyio
    async def test_admin_can_deactivate_user(self, client, admin_token):
        viewer_user = _DEMO_USERS["viewer@example.com"]
        user_id = viewer_user["id"]

        response = await client.delete(
            f"/v1/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["success"] is True

    @pytest.mark.anyio
    async def test_deactivate_sets_is_active_false(self, client, admin_token):
        viewer_user = _DEMO_USERS["viewer@example.com"]
        user_id = viewer_user["id"]

        await client.delete(
            f"/v1/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert viewer_user["is_active"] is False

    @pytest.mark.anyio
    async def test_deactivate_nonexistent_user_returns_404(self, client, admin_token):
        response = await client.delete(
            "/v1/admin/users/nonexistent-id",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_operator_cannot_deactivate_user(self, client, operator_token):
        viewer_user = _DEMO_USERS["viewer@example.com"]
        user_id = viewer_user["id"]

        response = await client.delete(
            f"/v1/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.anyio
    async def test_viewer_cannot_deactivate_user(self, client, viewer_token):
        viewer_user = _DEMO_USERS["viewer@example.com"]
        user_id = viewer_user["id"]

        response = await client.delete(
            f"/v1/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert response.status_code == 403
