"""Unit tests for RBAC middleware."""

from __future__ import annotations

import uuid

import pytest
from fastapi import Depends, FastAPI, Query
from httpx import ASGITransport, AsyncClient

from api.admin.auth_utils import create_access_token
from api.middleware.rbac import Permission, require_permission

pytestmark = pytest.mark.anyio


# ─── Test App Setup ───────────────────────────────────────────────────────────

def _create_test_app() -> FastAPI:
    """Create a minimal FastAPI app with RBAC-protected routes for testing."""
    app = FastAPI()

    @app.get("/read-only")
    async def read_only_endpoint(user=Depends(require_permission(Permission.READ))):
        return {"user": user["sub"], "role": user["role"]}

    @app.get("/write-required")
    async def write_endpoint(user=Depends(require_permission(Permission.WRITE))):
        return {"user": user["sub"], "role": user["role"]}

    @app.get("/admin-only")
    async def admin_endpoint(user=Depends(require_permission(Permission.ADMIN))):
        return {"user": user["sub"], "role": user["role"]}

    @app.get("/tenant/{tenant_id}/data")
    async def tenant_scoped_endpoint(
        tenant_id: str,
        user=Depends(require_permission(Permission.READ, tenant_id_param="tenant_id")),
    ):
        return {"user": user["sub"], "tenant_id": tenant_id}

    @app.get("/tenant-query")
    async def tenant_query_endpoint(
        tenant_id: str = Query(...),
        user=Depends(require_permission(Permission.READ, tenant_id_param="tenant_id")),
    ):
        return {"user": user["sub"], "tenant_id": tenant_id}

    return app


@pytest.fixture
def app():
    return _create_test_app()


@pytest.fixture
def admin_token():
    return create_access_token(
        user_id=str(uuid.uuid4()),
        email="admin@example.com",
        role="admin",
        tenant_ids=[],
    )


@pytest.fixture
def operator_token():
    return create_access_token(
        user_id=str(uuid.uuid4()),
        email="operator@example.com",
        role="operator",
        tenant_ids=["tenant-1", "tenant-2"],
    )


@pytest.fixture
def viewer_token():
    return create_access_token(
        user_id=str(uuid.uuid4()),
        email="viewer@example.com",
        role="viewer",
        tenant_ids=["tenant-1"],
    )


# ─── Tests: Token Validation ─────────────────────────────────────────────────


class TestTokenValidation:
    """Tests for JWT token validation in RBAC middleware."""

    async def test_missing_authorization_header(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/read-only")
            assert resp.status_code == 422  # FastAPI validation error for missing header

    async def test_invalid_authorization_format(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/read-only", headers={"Authorization": "Basic abc123"}
            )
            assert resp.status_code == 401

    async def test_invalid_token(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/read-only", headers={"Authorization": "Bearer invalid.token.here"}
            )
            assert resp.status_code == 401

    async def test_revoked_token(self, app, admin_token):
        from api.admin.auth_utils import decode_token
        from api.routes.admin_auth import _REVOKED_TOKENS

        # Revoke the token
        payload = decode_token(admin_token)
        jti = payload["jti"]
        _REVOKED_TOKENS[jti] = {"revoked_at": "2024-01-01T00:00:00Z", "expires_at": "2024-01-02T00:00:00Z"}

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/read-only", headers={"Authorization": f"Bearer {admin_token}"}
                )
                assert resp.status_code == 401
                assert "revoked" in resp.json()["detail"].lower()
        finally:
            # Clean up
            del _REVOKED_TOKENS[jti]


# ─── Tests: Role-Based Permission Checks ─────────────────────────────────────


class TestRolePermissions:
    """Tests for role-based permission enforcement."""

    async def test_admin_can_access_read(self, app, admin_token):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/read-only", headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert resp.status_code == 200

    async def test_admin_can_access_write(self, app, admin_token):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/write-required", headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert resp.status_code == 200

    async def test_admin_can_access_admin(self, app, admin_token):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/admin-only", headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert resp.status_code == 200

    async def test_operator_can_access_read(self, app, operator_token):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/read-only", headers={"Authorization": f"Bearer {operator_token}"}
            )
            assert resp.status_code == 200

    async def test_operator_can_access_write(self, app, operator_token):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/write-required", headers={"Authorization": f"Bearer {operator_token}"}
            )
            assert resp.status_code == 200

    async def test_operator_cannot_access_admin(self, app, operator_token):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/admin-only", headers={"Authorization": f"Bearer {operator_token}"}
            )
            assert resp.status_code == 403

    async def test_viewer_can_access_read(self, app, viewer_token):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/read-only", headers={"Authorization": f"Bearer {viewer_token}"}
            )
            assert resp.status_code == 200

    async def test_viewer_cannot_access_write(self, app, viewer_token):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/write-required", headers={"Authorization": f"Bearer {viewer_token}"}
            )
            assert resp.status_code == 403

    async def test_viewer_cannot_access_admin(self, app, viewer_token):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/admin-only", headers={"Authorization": f"Bearer {viewer_token}"}
            )
            assert resp.status_code == 403


# ─── Tests: Tenant-Scoped Access ─────────────────────────────────────────────


class TestTenantAccess:
    """Tests for tenant-scoped permission enforcement."""

    async def test_admin_can_access_any_tenant(self, app, admin_token):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/tenant/any-tenant-id/data",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert resp.status_code == 200

    async def test_operator_can_access_assigned_tenant(self, app, operator_token):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/tenant/tenant-1/data",
                headers={"Authorization": f"Bearer {operator_token}"},
            )
            assert resp.status_code == 200

    async def test_operator_cannot_access_unassigned_tenant(self, app, operator_token):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/tenant/tenant-999/data",
                headers={"Authorization": f"Bearer {operator_token}"},
            )
            assert resp.status_code == 403
            assert "tenant" in resp.json()["detail"].lower()

    async def test_viewer_can_access_assigned_tenant(self, app, viewer_token):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/tenant/tenant-1/data",
                headers={"Authorization": f"Bearer {viewer_token}"},
            )
            assert resp.status_code == 200

    async def test_viewer_cannot_access_unassigned_tenant(self, app, viewer_token):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/tenant/tenant-2/data",
                headers={"Authorization": f"Bearer {viewer_token}"},
            )
            assert resp.status_code == 403

    async def test_tenant_id_from_query_param(self, app, operator_token):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Assigned tenant via query param
            resp = await client.get(
                "/tenant-query?tenant_id=tenant-1",
                headers={"Authorization": f"Bearer {operator_token}"},
            )
            assert resp.status_code == 200

    async def test_tenant_id_from_query_param_denied(self, app, operator_token):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Unassigned tenant via query param
            resp = await client.get(
                "/tenant-query?tenant_id=tenant-999",
                headers={"Authorization": f"Bearer {operator_token}"},
            )
            assert resp.status_code == 403


# ─── Tests: Return Value ─────────────────────────────────────────────────────


class TestReturnValue:
    """Tests that the dependency returns the decoded JWT payload."""

    async def test_returns_user_context(self, app, admin_token):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/read-only", headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "user" in data
            assert "role" in data
            assert data["role"] == "admin"
