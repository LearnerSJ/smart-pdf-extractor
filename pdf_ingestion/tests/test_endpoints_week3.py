"""Tests for Week 3 API endpoints (tenants, feedback)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture
def client() -> TestClient:
    """Create a test client with the app."""
    app = create_app()
    return TestClient(app)


class TestTenantRedactionConfigEndpoints:
    """Tests for GET/PUT /v1/tenants/{id}/redaction-config."""

    def test_get_redaction_config_requires_auth(self, client: TestClient) -> None:
        """GET should require authentication."""
        response = client.get("/v1/tenants/tenant-1/redaction-config")
        assert response.status_code == 401

    def test_put_redaction_config_requires_auth(self, client: TestClient) -> None:
        """PUT should require authentication."""
        response = client.put(
            "/v1/tenants/tenant-1/redaction-config",
            json={"global_entities": [], "schema_overrides": {}},
        )
        assert response.status_code == 401


class TestFeedbackEndpoint:
    """Tests for POST /v1/feedback/{job_id}."""

    def test_feedback_requires_auth(self, client: TestClient) -> None:
        """POST should require authentication."""
        response = client.post(
            "/v1/feedback/job-123",
            json={
                "field_name": "account_number",
                "correct_value": "12345",
            },
        )
        assert response.status_code == 401
