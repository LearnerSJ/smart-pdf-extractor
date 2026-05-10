"""Unit tests for the alert evaluation engine."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from pipeline.alerts.engine import AlertEngine, _JOB_RECORDS


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_stores():
    """Reset in-memory stores before each test."""
    from api.routes.admin_alerts import _ALERT_HISTORY, _ALERT_RULES
    from api.routes.admin_usage import _USAGE_RECORDS

    # Save originals
    original_rules = _ALERT_RULES.copy()
    original_history = _ALERT_HISTORY.copy()
    original_usage = _USAGE_RECORDS.copy()
    original_jobs = _JOB_RECORDS.copy()

    # Clear stores
    _ALERT_RULES.clear()
    _ALERT_HISTORY.clear()
    _USAGE_RECORDS.clear()
    _JOB_RECORDS.clear()

    yield

    # Restore originals
    _ALERT_RULES.clear()
    _ALERT_RULES.extend(original_rules)
    _ALERT_HISTORY.clear()
    _ALERT_HISTORY.extend(original_history)
    _USAGE_RECORDS.clear()
    _USAGE_RECORDS.extend(original_usage)
    _JOB_RECORDS.clear()
    _JOB_RECORDS.extend(original_jobs)


@pytest.fixture
def engine():
    """Create an AlertEngine instance."""
    return AlertEngine()


@pytest.fixture
def mock_notifier():
    """Create a mock notification dispatcher."""
    notifier = MagicMock()
    notifier.send_webhook = AsyncMock()
    notifier.send_email = AsyncMock()
    return notifier


# ─── Start/Stop Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_creates_background_task(engine):
    """Engine start creates a running background task."""
    await engine.start(interval_seconds=60)
    assert engine.running is True
    await engine.stop()
    assert engine.running is False


@pytest.mark.asyncio
async def test_start_when_already_running(engine):
    """Starting an already-running engine is a no-op."""
    await engine.start(interval_seconds=60)
    await engine.start(interval_seconds=60)  # Should not raise
    assert engine.running is True
    await engine.stop()


@pytest.mark.asyncio
async def test_stop_when_not_running(engine):
    """Stopping a non-running engine is a no-op."""
    await engine.stop()  # Should not raise
    assert engine.running is False


# ─── Budget Rule Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_budget_rule_fires_when_threshold_crossed(engine, mock_notifier):
    """Budget rule transitions to firing when tokens exceed threshold."""
    from api.routes.admin_alerts import _ALERT_RULES
    from api.routes.admin_usage import _USAGE_RECORDS

    engine.set_notifier(mock_notifier)

    # Create a budget rule with low threshold
    rule = {
        "id": str(uuid.uuid4()),
        "name": "Test Budget Alert",
        "rule_type": "budget",
        "tenant_id": "tenant-1",
        "config": {"threshold_tokens": 100, "billing_period": "monthly"},
        "notification_channel": "webhook",
        "notification_target": "https://hooks.example.com/test",
        "enabled": True,
        "state": "idle",
        "last_evaluated_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _ALERT_RULES.append(rule)

    # Add usage records that exceed threshold
    now = datetime.now(timezone.utc)
    _USAGE_RECORDS.append({
        "id": str(uuid.uuid4()),
        "tenant_id": "tenant-1",
        "job_id": "job-1",
        "model_id": "test-model",
        "input_tokens": 80,
        "output_tokens": 50,
        "total_tokens": 130,
        "estimated_cost": 0.001,
        "timestamp": now.isoformat(),
    })

    await engine.evaluate_all_rules()

    assert rule["state"] == "firing"
    mock_notifier.send_webhook.assert_called_once()


@pytest.mark.asyncio
async def test_budget_rule_no_duplicate_notification(engine, mock_notifier):
    """Budget rule does not emit duplicate notifications when already firing."""
    from api.routes.admin_alerts import _ALERT_RULES
    from api.routes.admin_usage import _USAGE_RECORDS

    engine.set_notifier(mock_notifier)

    rule = {
        "id": str(uuid.uuid4()),
        "name": "Test Budget Alert",
        "rule_type": "budget",
        "tenant_id": "tenant-1",
        "config": {"threshold_tokens": 100, "billing_period": "monthly"},
        "notification_channel": "webhook",
        "notification_target": "https://hooks.example.com/test",
        "enabled": True,
        "state": "firing",  # Already firing
        "last_evaluated_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _ALERT_RULES.append(rule)

    now = datetime.now(timezone.utc)
    _USAGE_RECORDS.append({
        "id": str(uuid.uuid4()),
        "tenant_id": "tenant-1",
        "job_id": "job-1",
        "model_id": "test-model",
        "input_tokens": 80,
        "output_tokens": 50,
        "total_tokens": 130,
        "estimated_cost": 0.001,
        "timestamp": now.isoformat(),
    })

    await engine.evaluate_all_rules()

    assert rule["state"] == "firing"
    mock_notifier.send_webhook.assert_not_called()


@pytest.mark.asyncio
async def test_budget_rule_recovery_notification(engine, mock_notifier):
    """Budget rule emits recovery notification when tokens drop below threshold."""
    from api.routes.admin_alerts import _ALERT_RULES
    from api.routes.admin_usage import _USAGE_RECORDS

    engine.set_notifier(mock_notifier)

    rule = {
        "id": str(uuid.uuid4()),
        "name": "Test Budget Alert",
        "rule_type": "budget",
        "tenant_id": "tenant-1",
        "config": {"threshold_tokens": 1000, "billing_period": "monthly"},
        "notification_channel": "webhook",
        "notification_target": "https://hooks.example.com/test",
        "enabled": True,
        "state": "firing",  # Currently firing
        "last_evaluated_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _ALERT_RULES.append(rule)

    # Usage is below threshold (no records = 0 tokens)
    await engine.evaluate_all_rules()

    assert rule["state"] == "resolved"
    mock_notifier.send_webhook.assert_called_once()


# ─── Error Rate Rule Tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_error_rate_rule_fires_when_threshold_crossed(engine, mock_notifier):
    """Error rate rule transitions to firing when error rate exceeds threshold."""
    from api.routes.admin_alerts import _ALERT_RULES

    engine.set_notifier(mock_notifier)

    rule = {
        "id": str(uuid.uuid4()),
        "name": "Test Error Rate Alert",
        "rule_type": "error_rate",
        "tenant_id": None,  # Global
        "config": {"threshold_percent": 10.0, "evaluation_window_minutes": 60},
        "notification_channel": "email",
        "notification_target": "ops@example.com",
        "enabled": True,
        "state": "idle",
        "last_evaluated_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _ALERT_RULES.append(rule)

    # Add jobs with high failure rate (50%)
    now = datetime.now(timezone.utc)
    for i in range(10):
        _JOB_RECORDS.append({
            "id": f"job-{i}",
            "tenant_id": "tenant-1",
            "status": "failed" if i < 5 else "completed",
            "created_at": now.isoformat(),
        })

    await engine.evaluate_all_rules()

    assert rule["state"] == "firing"
    mock_notifier.send_email.assert_called_once()


@pytest.mark.asyncio
async def test_error_rate_rule_no_jobs_no_alert(engine, mock_notifier):
    """Error rate rule does not fire when there are no jobs in the window."""
    from api.routes.admin_alerts import _ALERT_RULES

    engine.set_notifier(mock_notifier)

    rule = {
        "id": str(uuid.uuid4()),
        "name": "Test Error Rate Alert",
        "rule_type": "error_rate",
        "tenant_id": None,
        "config": {"threshold_percent": 10.0, "evaluation_window_minutes": 60},
        "notification_channel": "email",
        "notification_target": "ops@example.com",
        "enabled": True,
        "state": "idle",
        "last_evaluated_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _ALERT_RULES.append(rule)

    # No jobs in the window
    await engine.evaluate_all_rules()

    assert rule["state"] == "idle"
    mock_notifier.send_email.assert_not_called()


@pytest.mark.asyncio
async def test_error_rate_rule_recovery(engine, mock_notifier):
    """Error rate rule emits recovery when rate drops below threshold."""
    from api.routes.admin_alerts import _ALERT_RULES

    engine.set_notifier(mock_notifier)

    rule = {
        "id": str(uuid.uuid4()),
        "name": "Test Error Rate Alert",
        "rule_type": "error_rate",
        "tenant_id": None,
        "config": {"threshold_percent": 50.0, "evaluation_window_minutes": 60},
        "notification_channel": "email",
        "notification_target": "ops@example.com",
        "enabled": True,
        "state": "firing",  # Currently firing
        "last_evaluated_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _ALERT_RULES.append(rule)

    # Add jobs with low failure rate (10%)
    now = datetime.now(timezone.utc)
    for i in range(10):
        _JOB_RECORDS.append({
            "id": f"job-{i}",
            "tenant_id": "tenant-1",
            "status": "failed" if i == 0 else "completed",
            "created_at": now.isoformat(),
        })

    await engine.evaluate_all_rules()

    assert rule["state"] == "resolved"
    mock_notifier.send_email.assert_called_once()


# ─── Disabled Rule Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_rules_not_evaluated(engine, mock_notifier):
    """Disabled rules are skipped during evaluation."""
    from api.routes.admin_alerts import _ALERT_RULES
    from api.routes.admin_usage import _USAGE_RECORDS

    engine.set_notifier(mock_notifier)

    rule = {
        "id": str(uuid.uuid4()),
        "name": "Disabled Budget Alert",
        "rule_type": "budget",
        "tenant_id": "tenant-1",
        "config": {"threshold_tokens": 1, "billing_period": "monthly"},
        "notification_channel": "webhook",
        "notification_target": "https://hooks.example.com/test",
        "enabled": False,  # Disabled
        "state": "idle",
        "last_evaluated_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _ALERT_RULES.append(rule)

    # Add usage that would exceed threshold
    now = datetime.now(timezone.utc)
    _USAGE_RECORDS.append({
        "id": str(uuid.uuid4()),
        "tenant_id": "tenant-1",
        "job_id": "job-1",
        "model_id": "test-model",
        "input_tokens": 100,
        "output_tokens": 100,
        "total_tokens": 200,
        "estimated_cost": 0.001,
        "timestamp": now.isoformat(),
    })

    await engine.evaluate_all_rules()

    assert rule["state"] == "idle"
    mock_notifier.send_webhook.assert_not_called()


# ─── Circuit Breaker Tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_circuit_breaker_open_fires_notification(engine, mock_notifier):
    """Circuit breaker closed→open transition emits firing notification."""
    from api.routes.admin_alerts import _ALERT_RULES

    engine.set_notifier(mock_notifier)

    rule = {
        "id": str(uuid.uuid4()),
        "name": "Delivery CB Alert",
        "rule_type": "circuit_breaker",
        "tenant_id": "tenant-1",
        "config": {"service_name": "delivery-api"},
        "notification_channel": "webhook",
        "notification_target": "https://hooks.example.com/cb",
        "enabled": True,
        "state": "idle",
        "last_evaluated_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _ALERT_RULES.append(rule)

    event = {
        "service_name": "delivery-api",
        "tenant_id": "tenant-1",
        "previous_state": "closed",
        "new_state": "open",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    await engine.handle_circuit_breaker_event(event)

    assert rule["state"] == "firing"
    mock_notifier.send_webhook.assert_called_once()


@pytest.mark.asyncio
async def test_circuit_breaker_close_emits_recovery(engine, mock_notifier):
    """Circuit breaker open→closed transition emits recovery notification."""
    from api.routes.admin_alerts import _ALERT_RULES

    engine.set_notifier(mock_notifier)

    rule = {
        "id": str(uuid.uuid4()),
        "name": "Delivery CB Alert",
        "rule_type": "circuit_breaker",
        "tenant_id": "tenant-1",
        "config": {"service_name": "delivery-api"},
        "notification_channel": "webhook",
        "notification_target": "https://hooks.example.com/cb",
        "enabled": True,
        "state": "firing",
        "last_evaluated_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _ALERT_RULES.append(rule)

    event = {
        "service_name": "delivery-api",
        "tenant_id": "tenant-1",
        "previous_state": "open",
        "new_state": "closed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    await engine.handle_circuit_breaker_event(event)

    assert rule["state"] == "resolved"
    mock_notifier.send_webhook.assert_called_once()


@pytest.mark.asyncio
async def test_circuit_breaker_disabled_rule_ignored(engine, mock_notifier):
    """Disabled circuit breaker rules are not triggered by events."""
    from api.routes.admin_alerts import _ALERT_RULES

    engine.set_notifier(mock_notifier)

    rule = {
        "id": str(uuid.uuid4()),
        "name": "Disabled CB Alert",
        "rule_type": "circuit_breaker",
        "tenant_id": "tenant-1",
        "config": {"service_name": "delivery-api"},
        "notification_channel": "webhook",
        "notification_target": "https://hooks.example.com/cb",
        "enabled": False,  # Disabled
        "state": "idle",
        "last_evaluated_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _ALERT_RULES.append(rule)

    event = {
        "service_name": "delivery-api",
        "tenant_id": "tenant-1",
        "previous_state": "closed",
        "new_state": "open",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    await engine.handle_circuit_breaker_event(event)

    assert rule["state"] == "idle"
    mock_notifier.send_webhook.assert_not_called()


# ─── State Transition Tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolved_transitions_to_idle_on_next_cycle(engine, mock_notifier):
    """Resolved rules transition back to idle on the next evaluation cycle."""
    from api.routes.admin_alerts import _ALERT_RULES

    engine.set_notifier(mock_notifier)

    rule = {
        "id": str(uuid.uuid4()),
        "name": "Test Rule",
        "rule_type": "budget",
        "tenant_id": "tenant-1",
        "config": {"threshold_tokens": 1000, "billing_period": "monthly"},
        "notification_channel": "webhook",
        "notification_target": "https://hooks.example.com/test",
        "enabled": True,
        "state": "resolved",  # Currently resolved
        "last_evaluated_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _ALERT_RULES.append(rule)

    await engine.evaluate_all_rules()

    # After evaluation, resolved should transition to idle
    assert rule["state"] == "idle"


@pytest.mark.asyncio
async def test_last_evaluated_at_updated(engine, mock_notifier):
    """last_evaluated_at is updated after each evaluation."""
    from api.routes.admin_alerts import _ALERT_RULES

    engine.set_notifier(mock_notifier)

    rule = {
        "id": str(uuid.uuid4()),
        "name": "Test Rule",
        "rule_type": "budget",
        "tenant_id": "tenant-1",
        "config": {"threshold_tokens": 1000, "billing_period": "monthly"},
        "notification_channel": "webhook",
        "notification_target": "https://hooks.example.com/test",
        "enabled": True,
        "state": "idle",
        "last_evaluated_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _ALERT_RULES.append(rule)

    await engine.evaluate_all_rules()

    assert rule["last_evaluated_at"] is not None


# ─── Alert History Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_firing_creates_history_entry(engine, mock_notifier):
    """Firing a rule creates an alert history entry."""
    from api.routes.admin_alerts import _ALERT_HISTORY, _ALERT_RULES
    from api.routes.admin_usage import _USAGE_RECORDS

    engine.set_notifier(mock_notifier)

    rule_id = str(uuid.uuid4())
    rule = {
        "id": rule_id,
        "name": "Test Budget Alert",
        "rule_type": "budget",
        "tenant_id": "tenant-1",
        "config": {"threshold_tokens": 100, "billing_period": "monthly"},
        "notification_channel": "webhook",
        "notification_target": "https://hooks.example.com/test",
        "enabled": True,
        "state": "idle",
        "last_evaluated_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _ALERT_RULES.append(rule)

    now = datetime.now(timezone.utc)
    _USAGE_RECORDS.append({
        "id": str(uuid.uuid4()),
        "tenant_id": "tenant-1",
        "job_id": "job-1",
        "model_id": "test-model",
        "input_tokens": 80,
        "output_tokens": 50,
        "total_tokens": 130,
        "estimated_cost": 0.001,
        "timestamp": now.isoformat(),
    })

    await engine.evaluate_all_rules()

    assert len(_ALERT_HISTORY) == 1
    entry = _ALERT_HISTORY[0]
    assert entry["rule_id"] == rule_id
    assert entry["fired_at"] is not None
    assert entry["resolved_at"] is None
    assert entry["notification_sent"] is True


@pytest.mark.asyncio
async def test_recovery_updates_history_entry(engine, mock_notifier):
    """Recovery updates the most recent history entry with resolved_at."""
    from api.routes.admin_alerts import _ALERT_HISTORY, _ALERT_RULES

    engine.set_notifier(mock_notifier)

    rule_id = str(uuid.uuid4())
    rule = {
        "id": rule_id,
        "name": "Test Budget Alert",
        "rule_type": "budget",
        "tenant_id": "tenant-1",
        "config": {"threshold_tokens": 1000, "billing_period": "monthly"},
        "notification_channel": "webhook",
        "notification_target": "https://hooks.example.com/test",
        "enabled": True,
        "state": "firing",
        "last_evaluated_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _ALERT_RULES.append(rule)

    # Pre-existing history entry (from when it fired)
    _ALERT_HISTORY.append({
        "id": str(uuid.uuid4()),
        "rule_id": rule_id,
        "tenant_id": "tenant-1",
        "fired_at": datetime.now(timezone.utc).isoformat(),
        "resolved_at": None,
        "notification_sent": True,
        "acknowledged_by": None,
        "acknowledged_at": None,
        "context": {},
    })

    # No usage records = below threshold → recovery
    await engine.evaluate_all_rules()

    assert rule["state"] == "resolved"
    assert _ALERT_HISTORY[0]["resolved_at"] is not None
