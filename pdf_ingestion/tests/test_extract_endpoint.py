"""Tests for POST /v1/extract endpoint."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.middleware.auth import _STUB_TENANTS, _hash_key
from api.models.tenant import TenantContext


@pytest.fixture
def app():
    """Create a test app with a stub tenant."""
    application = create_app()
    # Register a stub tenant for auth
    tenant = TenantContext(
        id="test-tenant-001",
        name="Test Tenant",
        api_key_hash=_hash_key("test-api-key"),
        vlm_enabled=True,
        is_suspended=False,
    )
    _STUB_TENANTS[_hash_key("test-api-key")] = tenant
    yield application
    _STUB_TENANTS.clear()


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


def test_extract_returns_202_with_job_response(client):
    """POST /v1/extract returns 202 with job_id, trace_id, and status."""
    pdf_content = b"%PDF-1.4 test content"
    response = client.post(
        "/v1/extract",
        files={"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")},
        data={"schema_type": "bank_statement"},
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["data"]["status"] == "submitted"
    assert "job_id" in body["data"]
    assert "trace_id" in body["data"]
    assert body["meta"]["request_id"] == body["data"]["trace_id"]
    assert body["meta"]["timestamp"] is not None


def test_extract_with_batch_id(client):
    """POST /v1/extract accepts optional batch_id parameter."""
    pdf_content = b"%PDF-1.4 test content"
    response = client.post(
        "/v1/extract",
        files={"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")},
        data={"batch_id": "batch-123"},
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["data"]["status"] == "submitted"


def test_extract_requires_auth(client):
    """POST /v1/extract returns 401 without auth header."""
    pdf_content = b"%PDF-1.4 test content"
    response = client.post(
        "/v1/extract",
        files={"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    assert response.status_code == 401


def test_extract_response_envelope_structure(client):
    """Response conforms to APIResponse[JobResponse] envelope."""
    pdf_content = b"%PDF-1.4 test content"
    response = client.post(
        "/v1/extract",
        files={"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")},
        headers={"Authorization": "Bearer test-api-key"},
    )
    body = response.json()
    assert "data" in body
    assert "meta" in body
    assert "error" not in body or body["error"] is None
