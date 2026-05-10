"""Tests for admin alert rule CRUD routes.

Tests the alert endpoints:
- GET /v1/admin/alerts/rules (list all rules)
- POST /v1/admin/alerts/rules (create rule with validation)
- PUT /v1/admin/alerts/rules/{rule_id} (update rule)
- DELETE /v1/admin/alerts/rules/{rule_id} (delete rule - Admin only)
- GET /v1/admin/alerts/history (list alert history)
- POST /v1/admin/alerts/{alert_id}/ack (acknowledge alert)
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.admin.auth_utils import create_access_token
from api.routes.admin_alerts import _ALERT_HISTORY, _ALERT_RULES, router

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


def _viewer_token(tenant_ids: list[str] | None = None) -> str:
    """Generate a valid viewer JWT for testing."""
    return create_access_token(
        user_id="test-viewer-id",
        email="viewer@test.com",
        role="viewer",
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


@pytest.fixture
def viewer_headers():
    return {"Authorization": f"Bearer {_viewer_token()}"}


class TestListAlertRules:
    """Tests for GET /v1/admin/alerts/rules endpoint."""

    @pytest.mark.anyio
    async def test_admin_can_list_rules(self, client, admin_headers):
        resp = await client.get("/v1/admin/alerts/rules", headers=admin_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "rules" in body["data"]
        assert len(body["data"]["rules"]) >= 3  # seeded demo rules

    @pytest.mark.anyio
    async def test_operator_can_list_rules(self, client, operator_headers):
        resp = await client.get("/v1/admin/alerts/rules", headers=operator_headers)
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_viewer_cannot_list_rules(self, client, viewer_headers):
        resp = await client.get("/v1/admin/alerts/rules", headers=viewer_headers)
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_rule_has_expected_fields(self, client, admin_headers):
        resp = await client.get("/v1/admin/alerts/rules", headers=admin_headers)

        assert resp.status_code == 200
        rule = resp.json()["data"]["rules"][0]
        assert "id" in rule
        assert "name" in rule
        assert "rule_type" in rule
        assert "config" in rule
        assert "notification_channel" in rule
        assert "notification_target" in rule
        assert "enabled" in rule
        assert "state" in rule
        assert "created_at" in rule


class TestCreateAlertRule:
    """Tests for POST /v1/admin/alerts/rules endpoint."""

    @pytest.mark.anyio
    async def test_create_budget_rule(self, client, admin_headers):
        payload = {
            "name": "Test Budget Rule",
            "rule_type": "budget",
            "tenant_id": "tenant-1",
            "config": {"threshold_tokens": 500000, "billing_period": "monthly"},
            "notification_channel": "webhook",
            "notification_target": "https://hooks.example.com/test",
        }
        resp = await client.post("/v1/admin/alerts/rules", json=payload, headers=admin_headers)

        assert resp.status_code == 201
        body = resp.json()
        rule = body["data"]
        assert rule["name"] == "Test Budget Rule"
        assert rule["rule_type"] == "budget"
        assert rule["state"] == "idle"
        assert rule["enabled"] is True

        # Cleanup
        _ALERT_RULES[:] = [r for r in _ALERT_RULES if r["id"] != rule["id"]]

    @pytest.mark.anyio
    async def test_create_error_rate_rule(self, client, admin_headers):
        payload = {
            "name": "Test Error Rate Rule",
            "rule_type": "error_rate",
            "config": {"threshold_percent": 5.0, "evaluation_window_minutes": 10},
            "notification_channel": "email",
            "notification_target": "ops@example.com",
        }
        resp = await client.post("/v1/admin/alerts/rules", json=payload, headers=admin_headers)

        assert resp.status_code == 201
        body = resp.json()
        rule = body["data"]
        assert rule["rule_type"] == "error_rate"
        assert rule["tenant_id"] is None

        # Cleanup
        _ALERT_RULES[:] = [r for r in _ALERT_RULES if r["id"] != rule["id"]]

    @pytest.mark.anyio
    async def test_create_circuit_breaker_rule(self, client, admin_headers):
        payload = {
            "name": "Test CB Rule",
            "rule_type": "circuit_breaker",
            "tenant_id": "tenant-2",
            "config": {"service_name": "payment-api"},
            "notification_channel": "webhook",
            "notification_target": "https://hooks.example.com/cb",
        }
        resp = await client.post("/v1/admin/alerts/rules", json=payload, headers=admin_headers)

        assert resp.status_code == 201
        body = resp.json()
        assert body["data"]["rule_type"] == "circuit_breaker"

        # Cleanup
        _ALERT_RULES[:] = [r for r in _ALERT_RULES if r["id"] != body["data"]["id"]]

    @pytest.mark.anyio
    async def test_422_invalid_budget_config_missing_threshold(self, client, admin_headers):
        payload = {
            "name": "Bad Budget Rule",
            "rule_type": "budget",
            "config": {"billing_period": "monthly"},
            "notification_channel": "webhook",
            "notification_target": "https://hooks.example.com/test",
        }
        resp = await client.post("/v1/admin/alerts/rules", json=payload, headers=admin_headers)
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_422_invalid_budget_config_negative_threshold(self, client, admin_headers):
        payload = {
            "name": "Bad Budget Rule",
            "rule_type": "budget",
            "config": {"threshold_tokens": -100, "billing_period": "monthly"},
            "notification_channel": "webhook",
            "notification_target": "https://hooks.example.com/test",
        }
        resp = await client.post("/v1/admin/alerts/rules", json=payload, headers=admin_headers)
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_422_invalid_budget_config_bad_billing_period(self, client, admin_headers):
        payload = {
            "name": "Bad Budget Rule",
            "rule_type": "budget",
            "config": {"threshold_tokens": 1000, "billing_period": "daily"},
            "notification_channel": "webhook",
            "notification_target": "https://hooks.example.com/test",
        }
        resp = await client.post("/v1/admin/alerts/rules", json=payload, headers=admin_headers)
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_422_invalid_error_rate_threshold_out_of_range(self, client, admin_headers):
        payload = {
            "name": "Bad Error Rate Rule",
            "rule_type": "error_rate",
            "config": {"threshold_percent": 150.0, "evaluation_window_minutes": 10},
            "notification_channel": "email",
            "notification_target": "ops@example.com",
        }
        resp = await client.post("/v1/admin/alerts/rules", json=payload, headers=admin_headers)
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_422_invalid_error_rate_negative_window(self, client, admin_headers):
        payload = {
            "name": "Bad Error Rate Rule",
            "rule_type": "error_rate",
            "config": {"threshold_percent": 5.0, "evaluation_window_minutes": -5},
            "notification_channel": "email",
            "notification_target": "ops@example.com",
        }
        resp = await client.post("/v1/admin/alerts/rules", json=payload, headers=admin_headers)
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_422_invalid_circuit_breaker_empty_service_name(self, client, admin_headers):
        payload = {
            "name": "Bad CB Rule",
            "rule_type": "circuit_breaker",
            "config": {"service_name": "   "},
            "notification_channel": "webhook",
            "notification_target": "https://hooks.example.com/cb",
        }
        resp = await client.post("/v1/admin/alerts/rules", json=payload, headers=admin_headers)
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_422_invalid_webhook_target(self, client, admin_headers):
        payload = {
            "name": "Bad Webhook Target",
            "rule_type": "budget",
            "config": {"threshold_tokens": 1000, "billing_period": "monthly"},
            "notification_channel": "webhook",
            "notification_target": "not-a-url",
        }
        resp = await client.post("/v1/admin/alerts/rules", json=payload, headers=admin_headers)
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_422_invalid_email_target(self, client, admin_headers):
        payload = {
            "name": "Bad Email Target",
            "rule_type": "budget",
            "config": {"threshold_tokens": 1000, "billing_period": "monthly"},
            "notification_channel": "email",
            "notification_target": "not-an-email",
        }
        resp = await client.post("/v1/admin/alerts/rules", json=payload, headers=admin_headers)
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_operator_can_create_rule(self, client, operator_headers):
        payload = {
            "name": "Operator Rule",
            "rule_type": "budget",
            "config": {"threshold_tokens": 1000, "billing_period": "weekly"},
            "notification_channel": "email",
            "notification_target": "ops@example.com",
        }
        resp = await client.post("/v1/admin/alerts/rules", json=payload, headers=operator_headers)
        assert resp.status_code == 201

        # Cleanup
        rule_id = resp.json()["data"]["id"]
        _ALERT_RULES[:] = [r for r in _ALERT_RULES if r["id"] != rule_id]

    @pytest.mark.anyio
    async def test_viewer_cannot_create_rule(self, client, viewer_headers):
        payload = {
            "name": "Viewer Rule",
            "rule_type": "budget",
            "config": {"threshold_tokens": 1000, "billing_period": "monthly"},
            "notification_channel": "webhook",
            "notification_target": "https://hooks.example.com/test",
        }
        resp = await client.post("/v1/admin/alerts/rules", json=payload, headers=viewer_headers)
        assert resp.status_code == 403


class TestUpdateAlertRule:
    """Tests for PUT /v1/admin/alerts/rules/{rule_id} endpoint."""

    @pytest.mark.anyio
    async def test_update_rule_name(self, client, admin_headers):
        rule_id = _ALERT_RULES[0]["id"]
        original_name = _ALERT_RULES[0]["name"]

        resp = await client.put(
            f"/v1/admin/alerts/rules/{rule_id}",
            json={"name": "Updated Name"},
            headers=admin_headers,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["name"] == "Updated Name"

        # Restore
        _ALERT_RULES[0]["name"] = original_name

    @pytest.mark.anyio
    async def test_update_rule_enabled(self, client, admin_headers):
        rule_id = _ALERT_RULES[0]["id"]
        original_enabled = _ALERT_RULES[0]["enabled"]

        resp = await client.put(
            f"/v1/admin/alerts/rules/{rule_id}",
            json={"enabled": False},
            headers=admin_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["enabled"] is False

        # Restore
        _ALERT_RULES[0]["enabled"] = original_enabled

    @pytest.mark.anyio
    async def test_update_rule_config(self, client, admin_headers):
        rule_id = _ALERT_RULES[0]["id"]
        original_config = _ALERT_RULES[0]["config"].copy()

        resp = await client.put(
            f"/v1/admin/alerts/rules/{rule_id}",
            json={"config": {"threshold_tokens": 2000000, "billing_period": "weekly"}},
            headers=admin_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["config"]["threshold_tokens"] == 2000000

        # Restore
        _ALERT_RULES[0]["config"] = original_config

    @pytest.mark.anyio
    async def test_update_nonexistent_rule_returns_404(self, client, admin_headers):
        resp = await client.put(
            "/v1/admin/alerts/rules/nonexistent-id",
            json={"name": "Nope"},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_update_with_invalid_config_returns_422(self, client, admin_headers):
        rule_id = _ALERT_RULES[0]["id"]

        resp = await client.put(
            f"/v1/admin/alerts/rules/{rule_id}",
            json={"config": {"threshold_tokens": -1, "billing_period": "monthly"}},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_viewer_cannot_update_rule(self, client, viewer_headers):
        rule_id = _ALERT_RULES[0]["id"]

        resp = await client.put(
            f"/v1/admin/alerts/rules/{rule_id}",
            json={"name": "Viewer Update"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403


class TestDeleteAlertRule:
    """Tests for DELETE /v1/admin/alerts/rules/{rule_id} endpoint."""

    @pytest.mark.anyio
    async def test_admin_can_delete_rule(self, client, admin_headers):
        # Create a rule to delete
        payload = {
            "name": "To Delete",
            "rule_type": "budget",
            "config": {"threshold_tokens": 1000, "billing_period": "monthly"},
            "notification_channel": "webhook",
            "notification_target": "https://hooks.example.com/del",
        }
        create_resp = await client.post("/v1/admin/alerts/rules", json=payload, headers=admin_headers)
        rule_id = create_resp.json()["data"]["id"]

        resp = await client.delete(f"/v1/admin/alerts/rules/{rule_id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["success"] is True

    @pytest.mark.anyio
    async def test_operator_cannot_delete_rule(self, client, operator_headers):
        rule_id = _ALERT_RULES[0]["id"]

        resp = await client.delete(f"/v1/admin/alerts/rules/{rule_id}", headers=operator_headers)
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_delete_nonexistent_rule_returns_404(self, client, admin_headers):
        resp = await client.delete("/v1/admin/alerts/rules/nonexistent-id", headers=admin_headers)
        assert resp.status_code == 404


class TestAlertHistory:
    """Tests for GET /v1/admin/alerts/history endpoint."""

    @pytest.mark.anyio
    async def test_list_alert_history(self, client, admin_headers):
        resp = await client.get("/v1/admin/alerts/history", headers=admin_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert "entries" in body["data"]
        assert len(body["data"]["entries"]) >= 1

    @pytest.mark.anyio
    async def test_history_entry_has_expected_fields(self, client, admin_headers):
        resp = await client.get("/v1/admin/alerts/history", headers=admin_headers)

        assert resp.status_code == 200
        entry = resp.json()["data"]["entries"][0]
        assert "id" in entry
        assert "rule_id" in entry
        assert "fired_at" in entry
        assert "notification_sent" in entry
        assert "context" in entry

    @pytest.mark.anyio
    async def test_filter_history_by_rule_id(self, client, admin_headers):
        rule_id = _ALERT_HISTORY[0]["rule_id"]
        resp = await client.get(
            f"/v1/admin/alerts/history?rule_id={rule_id}", headers=admin_headers
        )

        assert resp.status_code == 200
        entries = resp.json()["data"]["entries"]
        for entry in entries:
            assert entry["rule_id"] == rule_id

    @pytest.mark.anyio
    async def test_viewer_can_read_history(self, client, viewer_headers):
        """Viewers have READ permission so they can view history."""
        resp = await client.get("/v1/admin/alerts/history", headers=viewer_headers)
        assert resp.status_code == 200


class TestAcknowledgeAlert:
    """Tests for POST /v1/admin/alerts/{alert_id}/ack endpoint."""

    @pytest.mark.anyio
    async def test_acknowledge_alert(self, client, admin_headers):
        alert_id = _ALERT_HISTORY[0]["id"]
        original_ack_by = _ALERT_HISTORY[0]["acknowledged_by"]
        original_ack_at = _ALERT_HISTORY[0]["acknowledged_at"]

        resp = await client.post(
            f"/v1/admin/alerts/{alert_id}/ack", headers=admin_headers
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["acknowledged"] is True

        # Verify the history entry was updated
        assert _ALERT_HISTORY[0]["acknowledged_by"] == "test-admin-id"
        assert _ALERT_HISTORY[0]["acknowledged_at"] is not None

        # Restore
        _ALERT_HISTORY[0]["acknowledged_by"] = original_ack_by
        _ALERT_HISTORY[0]["acknowledged_at"] = original_ack_at

    @pytest.mark.anyio
    async def test_acknowledge_nonexistent_alert_returns_404(self, client, admin_headers):
        resp = await client.post(
            "/v1/admin/alerts/nonexistent-id/ack", headers=admin_headers
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_viewer_cannot_acknowledge_alert(self, client, viewer_headers):
        alert_id = _ALERT_HISTORY[0]["id"]
        resp = await client.post(
            f"/v1/admin/alerts/{alert_id}/ack", headers=viewer_headers
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_operator_can_acknowledge_alert(self, client, operator_headers):
        alert_id = _ALERT_HISTORY[0]["id"]
        original_ack_by = _ALERT_HISTORY[0]["acknowledged_by"]
        original_ack_at = _ALERT_HISTORY[0]["acknowledged_at"]

        resp = await client.post(
            f"/v1/admin/alerts/{alert_id}/ack", headers=operator_headers
        )
        assert resp.status_code == 200

        # Restore
        _ALERT_HISTORY[0]["acknowledged_by"] = original_ack_by
        _ALERT_HISTORY[0]["acknowledged_at"] = original_ack_at
