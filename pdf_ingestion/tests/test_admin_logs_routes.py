"""Tests for admin log query routes.

Tests the two log endpoints:
- GET /v1/admin/logs (paginated list with filters)
- GET /v1/admin/logs/trace/{trace_id} (all logs for a trace)
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.admin.auth_utils import create_access_token
from api.middleware.log_sink import _LOG_STORE, _LOG_STORE_LOCK, clear_logs
from api.routes.admin_logs import router

# Build a minimal FastAPI app for testing
app = FastAPI()
app.include_router(router)


def _admin_token() -> str:
    """Generate a valid admin JWT for testing."""
    return create_access_token(
        user_id="test-admin-id",
        email="admin@test.com",
        role="admin",
        tenant_ids=[],
    )


def _operator_token(tenant_ids: list[str] | None = None) -> str:
    """Generate a valid operator JWT for testing."""
    return create_access_token(
        user_id="test-operator-id",
        email="operator@test.com",
        role="operator",
        tenant_ids=tenant_ids or ["tenant-1"],
    )


def _seed_test_logs() -> None:
    """Seed the in-memory log store with test data."""
    import api.middleware.log_sink as log_sink

    clear_logs()

    test_entries = [
        {
            "id": 1,
            "timestamp": "2025-01-10T10:00:00+00:00",
            "severity": "info",
            "event_name": "job.started",
            "tenant_id": "tenant-1",
            "job_id": "job-001",
            "trace_id": "trace-abc",
            "message": "Job started",
            "fields": {"schema_type": "bank_statement"},
        },
        {
            "id": 2,
            "timestamp": "2025-01-10T10:01:00+00:00",
            "severity": "debug",
            "event_name": "extraction.begin",
            "tenant_id": "tenant-1",
            "job_id": "job-001",
            "trace_id": "trace-abc",
            "message": "Starting extraction",
            "fields": None,
        },
        {
            "id": 3,
            "timestamp": "2025-01-10T10:02:00+00:00",
            "severity": "warning",
            "event_name": "vlm.retry",
            "tenant_id": "tenant-1",
            "job_id": "job-001",
            "trace_id": "trace-abc",
            "message": "VLM call retried",
            "fields": {"attempt": 2},
        },
        {
            "id": 4,
            "timestamp": "2025-01-10T11:00:00+00:00",
            "severity": "error",
            "event_name": "job.failed",
            "tenant_id": "tenant-2",
            "job_id": "job-002",
            "trace_id": "trace-def",
            "message": "Job failed due to timeout",
            "fields": {"error_code": "ERR_TIMEOUT"},
        },
        {
            "id": 5,
            "timestamp": "2025-01-10T12:00:00+00:00",
            "severity": "critical",
            "event_name": "system.crash",
            "tenant_id": "tenant-2",
            "job_id": "job-003",
            "trace_id": "trace-ghi",
            "message": "System crash detected",
            "fields": {"component": "vlm_client"},
        },
        {
            "id": 6,
            "timestamp": "2025-01-11T09:00:00+00:00",
            "severity": "info",
            "event_name": "job.completed",
            "tenant_id": "tenant-1",
            "job_id": "job-004",
            "trace_id": "trace-jkl",
            "message": "Job completed successfully",
            "fields": None,
        },
    ]

    with _LOG_STORE_LOCK:
        log_sink._ID_COUNTER = 6
        _LOG_STORE.extend(test_entries)


@pytest.fixture(autouse=True)
def setup_logs():
    """Seed test logs before each test and clean up after."""
    _seed_test_logs()
    yield
    clear_logs()


@pytest.fixture
async def client():
    """Async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def admin_headers():
    return {"Authorization": f"Bearer {_admin_token()}"}


@pytest.fixture
def operator_headers():
    return {"Authorization": f"Bearer {_operator_token()}"}


class TestGetAdminLogs:
    """Tests for GET /v1/admin/logs endpoint."""

    @pytest.mark.anyio
    async def test_returns_paginated_results(self, client, admin_headers):
        resp = await client.get("/v1/admin/logs", headers=admin_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "entries" in body["data"]
        assert "pagination" in body["data"]
        assert body["data"]["pagination"]["page"] == 1
        assert body["data"]["pagination"]["page_size"] == 50
        assert body["data"]["pagination"]["total"] == 6

    @pytest.mark.anyio
    async def test_pagination_page_size(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/logs?page_size=2", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]["entries"]) == 2
        assert body["data"]["pagination"]["page_size"] == 2
        assert body["data"]["pagination"]["total_pages"] == 3

    @pytest.mark.anyio
    async def test_pagination_second_page(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/logs?page=2&page_size=2", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]["entries"]) == 2
        assert body["data"]["pagination"]["page"] == 2

    @pytest.mark.anyio
    async def test_filter_by_tenant_id(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/logs?tenant_id=tenant-1", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        entries = body["data"]["entries"]
        assert len(entries) == 4
        for entry in entries:
            assert entry["tenant_id"] == "tenant-1"

    @pytest.mark.anyio
    async def test_filter_by_job_id(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/logs?job_id=job-001", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        entries = body["data"]["entries"]
        assert len(entries) == 3
        for entry in entries:
            assert entry["job_id"] == "job-001"

    @pytest.mark.anyio
    async def test_filter_by_trace_id(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/logs?trace_id=trace-abc", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        entries = body["data"]["entries"]
        assert len(entries) == 3
        for entry in entries:
            assert entry["trace_id"] == "trace-abc"

    @pytest.mark.anyio
    async def test_filter_by_severity(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/logs?severity=warning", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        entries = body["data"]["entries"]
        # Should include warning, error, critical (entries 3, 4, 5)
        assert len(entries) == 3
        for entry in entries:
            assert entry["severity"] in ("warning", "error", "critical")

    @pytest.mark.anyio
    async def test_filter_by_severity_error(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/logs?severity=error", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        entries = body["data"]["entries"]
        # Should include error and critical (entries 4, 5)
        assert len(entries) == 2
        for entry in entries:
            assert entry["severity"] in ("error", "critical")

    @pytest.mark.anyio
    async def test_filter_by_time_range(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/logs?start_time=2025-01-10T10:30:00%2B00:00&end_time=2025-01-10T12:30:00%2B00:00",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        body = resp.json()
        entries = body["data"]["entries"]
        # Should include entries at 11:00 and 12:00
        assert len(entries) == 2

    @pytest.mark.anyio
    async def test_results_in_chronological_order(self, client, admin_headers):
        resp = await client.get("/v1/admin/logs", headers=admin_headers)

        assert resp.status_code == 200
        body = resp.json()
        entries = body["data"]["entries"]
        timestamps = [e["timestamp"] for e in entries]
        assert timestamps == sorted(timestamps)

    @pytest.mark.anyio
    async def test_entry_has_expected_fields(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/logs?page_size=1", headers=admin_headers
        )

        assert resp.status_code == 200
        entry = resp.json()["data"]["entries"][0]
        assert "id" in entry
        assert "timestamp" in entry
        assert "severity" in entry
        assert "event_name" in entry
        assert "tenant_id" in entry
        assert "job_id" in entry
        assert "trace_id" in entry
        assert "message" in entry
        assert "fields" in entry

    @pytest.mark.anyio
    async def test_invalid_severity_returns_422(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/logs?severity=invalid_level", headers=admin_headers
        )

        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_requires_auth(self, client):
        resp = await client.get("/v1/admin/logs")
        assert resp.status_code == 422  # Missing authorization header

    @pytest.mark.anyio
    async def test_rbac_operator_can_access_assigned_tenant(self, client, operator_headers):
        resp = await client.get(
            "/v1/admin/logs?tenant_id=tenant-1", headers=operator_headers
        )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_rbac_operator_denied_unassigned_tenant(self, client, operator_headers):
        resp = await client.get(
            "/v1/admin/logs?tenant_id=tenant-2", headers=operator_headers
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_combined_filters(self, client, admin_headers):
        """Test AND logic for multiple filters."""
        resp = await client.get(
            "/v1/admin/logs?tenant_id=tenant-1&severity=warning",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        body = resp.json()
        entries = body["data"]["entries"]
        # Only entry 3 matches both tenant-1 AND severity >= warning
        assert len(entries) == 1
        assert entries[0]["tenant_id"] == "tenant-1"
        assert entries[0]["severity"] == "warning"

    @pytest.mark.anyio
    async def test_page_size_max_200(self, client, admin_headers):
        """Page size is clamped to max 200."""
        resp = await client.get(
            "/v1/admin/logs?page_size=201", headers=admin_headers
        )
        # FastAPI Query validation should reject page_size > 200
        assert resp.status_code == 422


class TestGetLogsByTrace:
    """Tests for GET /v1/admin/logs/trace/{trace_id} endpoint."""

    @pytest.mark.anyio
    async def test_returns_all_logs_for_trace(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/logs/trace/trace-abc", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        entries = body["data"]["entries"]
        assert len(entries) == 3
        for entry in entries:
            assert entry["trace_id"] == "trace-abc"

    @pytest.mark.anyio
    async def test_results_in_chronological_order(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/logs/trace/trace-abc", headers=admin_headers
        )

        assert resp.status_code == 200
        entries = resp.json()["data"]["entries"]
        timestamps = [e["timestamp"] for e in entries]
        assert timestamps == sorted(timestamps)

    @pytest.mark.anyio
    async def test_empty_trace_returns_empty_list(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/logs/trace/nonexistent-trace", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["entries"] == []
        assert body["data"]["pagination"]["total"] == 0

    @pytest.mark.anyio
    async def test_single_entry_trace(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/logs/trace/trace-ghi", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        entries = body["data"]["entries"]
        assert len(entries) == 1
        assert entries[0]["trace_id"] == "trace-ghi"
        assert entries[0]["severity"] == "critical"

    @pytest.mark.anyio
    async def test_requires_auth(self, client):
        resp = await client.get("/v1/admin/logs/trace/trace-abc")
        assert resp.status_code == 422  # Missing authorization header

    @pytest.mark.anyio
    async def test_response_has_meta(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/logs/trace/trace-abc", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        assert "meta" in body
        assert "request_id" in body["meta"]
        assert "timestamp" in body["meta"]
