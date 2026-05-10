"""Tests for admin usage query routes.

Tests the three usage endpoints:
- GET /v1/admin/usage (paginated list with filters)
- GET /v1/admin/usage/summary (aggregated totals with cost)
- GET /v1/admin/usage/timeseries (bucketed time-series)
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.admin.auth_utils import create_access_token
from api.routes.admin_usage import _USAGE_RECORDS, router

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


class TestGetUsage:
    """Tests for GET /v1/admin/usage endpoint."""

    @pytest.mark.anyio
    async def test_returns_paginated_results(self, client, admin_headers):
        resp = await client.get("/v1/admin/usage", headers=admin_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "data" in body["data"]
        assert "pagination" in body["data"]
        assert body["data"]["pagination"]["page"] == 1
        assert body["data"]["pagination"]["page_size"] == 50
        assert body["data"]["pagination"]["total"] == len(_USAGE_RECORDS)

    @pytest.mark.anyio
    async def test_pagination_page_size(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/usage?page=1&page_size=10", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]["data"]) == 10
        assert body["data"]["pagination"]["page_size"] == 10

    @pytest.mark.anyio
    async def test_pagination_second_page(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/usage?page=2&page_size=10", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]["data"]) == 10
        assert body["data"]["pagination"]["page"] == 2

    @pytest.mark.anyio
    async def test_filter_by_tenant_id(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/usage?tenant_id=tenant-1", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        records = body["data"]["data"]
        assert len(records) > 0
        for record in records:
            assert record["tenant_id"] == "tenant-1"

    @pytest.mark.anyio
    async def test_filter_by_model_id(self, client, admin_headers):
        model = "us.anthropic.claude-sonnet-4-6"
        resp = await client.get(
            f"/v1/admin/usage?model_id={model}", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        records = body["data"]["data"]
        assert len(records) > 0
        for record in records:
            assert record["model_id"] == model

    @pytest.mark.anyio
    async def test_filter_by_time_range(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/usage?start_time=2025-01-15T00:00:00%2B00:00&end_time=2025-02-01T00:00:00%2B00:00",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        body = resp.json()
        records = body["data"]["data"]
        for record in records:
            assert record["timestamp"] >= "2025-01-15T00:00:00"
            assert record["timestamp"] < "2025-02-01T00:00:00"

    @pytest.mark.anyio
    async def test_record_has_expected_fields(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/usage?page_size=1", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        record = body["data"]["data"][0]
        assert "id" in record
        assert "tenant_id" in record
        assert "job_id" in record
        assert "model_id" in record
        assert "input_tokens" in record
        assert "output_tokens" in record
        assert "total_tokens" in record
        assert "estimated_cost" in record
        assert "timestamp" in record

    @pytest.mark.anyio
    async def test_requires_auth(self, client):
        resp = await client.get("/v1/admin/usage")
        assert resp.status_code == 422  # Missing authorization header

    @pytest.mark.anyio
    async def test_rbac_operator_can_access_assigned_tenant(self, client, operator_headers):
        resp = await client.get(
            "/v1/admin/usage?tenant_id=tenant-1", headers=operator_headers
        )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_rbac_operator_denied_unassigned_tenant(self, client, operator_headers):
        resp = await client.get(
            "/v1/admin/usage?tenant_id=tenant-3", headers=operator_headers
        )
        assert resp.status_code == 403


class TestGetUsageSummary:
    """Tests for GET /v1/admin/usage/summary endpoint."""

    @pytest.mark.anyio
    async def test_returns_aggregated_totals(self, client, admin_headers):
        resp = await client.get("/v1/admin/usage/summary", headers=admin_headers)

        assert resp.status_code == 200
        body = resp.json()
        data = body["data"]
        assert "total_input_tokens" in data
        assert "total_output_tokens" in data
        assert "total_tokens" in data
        assert "estimated_cost" in data
        assert "by_model" in data
        assert data["total_tokens"] == data["total_input_tokens"] + data["total_output_tokens"]

    @pytest.mark.anyio
    async def test_by_model_breakdown(self, client, admin_headers):
        resp = await client.get("/v1/admin/usage/summary", headers=admin_headers)

        assert resp.status_code == 200
        body = resp.json()
        by_model = body["data"]["by_model"]
        assert len(by_model) > 0
        for model_entry in by_model:
            assert "model_id" in model_entry
            assert "input_tokens" in model_entry
            assert "output_tokens" in model_entry
            assert "total_tokens" in model_entry
            assert "estimated_cost" in model_entry
            assert model_entry["total_tokens"] == (
                model_entry["input_tokens"] + model_entry["output_tokens"]
            )

    @pytest.mark.anyio
    async def test_summary_with_tenant_filter(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/usage/summary?tenant_id=tenant-1", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total_tokens"] > 0

    @pytest.mark.anyio
    async def test_cost_computation_formula(self, client, admin_headers):
        """Verify cost = input_tokens * 0.003/1000 + output_tokens * 0.015/1000."""
        resp = await client.get("/v1/admin/usage/summary", headers=admin_headers)

        assert resp.status_code == 200
        body = resp.json()
        data = body["data"]
        expected_cost = (
            data["total_input_tokens"] * 0.003 / 1000
            + data["total_output_tokens"] * 0.015 / 1000
        )
        assert abs(data["estimated_cost"] - expected_cost) < 0.001


class TestGetUsageTimeseries:
    """Tests for GET /v1/admin/usage/timeseries endpoint."""

    @pytest.mark.anyio
    async def test_returns_buckets(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/usage/timeseries", headers=admin_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        assert "buckets" in body["data"]
        assert len(body["data"]["buckets"]) > 0

    @pytest.mark.anyio
    async def test_bucket_has_expected_fields(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/usage/timeseries", headers=admin_headers
        )

        assert resp.status_code == 200
        bucket = resp.json()["data"]["buckets"][0]
        assert "period" in bucket
        assert "input_tokens" in bucket
        assert "output_tokens" in bucket
        assert "total_tokens" in bucket
        assert "estimated_cost" in bucket

    @pytest.mark.anyio
    async def test_day_granularity(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/usage/timeseries?granularity=day", headers=admin_headers
        )

        assert resp.status_code == 200
        buckets = resp.json()["data"]["buckets"]
        # Day buckets should be in YYYY-MM-DD format
        for bucket in buckets:
            assert len(bucket["period"]) == 10  # YYYY-MM-DD

    @pytest.mark.anyio
    async def test_week_granularity(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/usage/timeseries?granularity=week", headers=admin_headers
        )

        assert resp.status_code == 200
        buckets = resp.json()["data"]["buckets"]
        assert len(buckets) > 0

    @pytest.mark.anyio
    async def test_month_granularity(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/usage/timeseries?granularity=month", headers=admin_headers
        )

        assert resp.status_code == 200
        buckets = resp.json()["data"]["buckets"]
        # Data spans Jan-Mar, so should have 3 monthly buckets
        assert len(buckets) == 3
        # Month buckets should be YYYY-MM-01 format
        for bucket in buckets:
            assert bucket["period"].endswith("-01")

    @pytest.mark.anyio
    async def test_timeseries_with_filters(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/usage/timeseries?tenant_id=tenant-1&granularity=month",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        buckets = resp.json()["data"]["buckets"]
        assert len(buckets) > 0

    @pytest.mark.anyio
    async def test_buckets_are_sorted_chronologically(self, client, admin_headers):
        resp = await client.get(
            "/v1/admin/usage/timeseries?granularity=day", headers=admin_headers
        )

        assert resp.status_code == 200
        buckets = resp.json()["data"]["buckets"]
        periods = [b["period"] for b in buckets]
        assert periods == sorted(periods)
