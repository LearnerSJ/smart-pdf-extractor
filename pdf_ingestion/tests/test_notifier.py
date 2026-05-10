"""Unit tests for the notification dispatcher."""

from __future__ import annotations

import pytest

from pipeline.alerts.notifier import NotificationDispatcher


# ─── Initialization Tests ─────────────────────────────────────────────────────


def test_dispatcher_default_init():
    """NotificationDispatcher initializes with default SMTP settings."""
    dispatcher = NotificationDispatcher()
    assert dispatcher._smtp_host is None
    assert dispatcher._smtp_port == 587
    assert dispatcher._smtp_from == "alerts@pdf-ingestion.local"


def test_dispatcher_custom_init():
    """NotificationDispatcher accepts custom SMTP settings."""
    dispatcher = NotificationDispatcher(
        smtp_host="smtp.example.com",
        smtp_port=465,
        smtp_from="custom@example.com",
    )
    assert dispatcher._smtp_host == "smtp.example.com"
    assert dispatcher._smtp_port == 465
    assert dispatcher._smtp_from == "custom@example.com"


# ─── Webhook Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_webhook_does_not_raise():
    """send_webhook completes without raising exceptions."""
    dispatcher = NotificationDispatcher()
    # Should not raise — logs the webhook for MVP
    await dispatcher.send_webhook(
        url="https://hooks.example.com/alert",
        payload={"rule_id": "test-123", "event_type": "firing"},
    )


@pytest.mark.asyncio
async def test_send_webhook_with_empty_payload():
    """send_webhook handles empty payload gracefully."""
    dispatcher = NotificationDispatcher()
    await dispatcher.send_webhook(url="https://hooks.example.com/test", payload={})


@pytest.mark.asyncio
async def test_send_webhook_with_complex_payload():
    """send_webhook handles complex nested payload."""
    dispatcher = NotificationDispatcher()
    payload = {
        "rule_id": "rule-abc",
        "rule_name": "Budget Alert",
        "context": {
            "threshold_tokens": 10000,
            "actual_tokens": 12500,
            "tenant_id": "tenant-1",
        },
        "timestamp": "2025-01-15T10:30:00Z",
    }
    await dispatcher.send_webhook(url="https://hooks.example.com/alert", payload=payload)


# ─── Email Tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_email_no_smtp_configured():
    """send_email logs the email when SMTP is not configured."""
    dispatcher = NotificationDispatcher(smtp_host=None)
    # Should not raise — logs the email for MVP
    await dispatcher.send_email(
        to="ops@example.com",
        subject="[ALERT] Budget Exceeded",
        body="Token budget exceeded for tenant-1.",
    )


@pytest.mark.asyncio
async def test_send_email_with_smtp_configured():
    """send_email logs the email when SMTP host is set (MVP logs only)."""
    dispatcher = NotificationDispatcher(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_from="alerts@example.com",
    )
    # Should not raise — for MVP, logs even with SMTP configured
    await dispatcher.send_email(
        to="ops@example.com",
        subject="[RESOLVED] Error Rate Recovered",
        body="Error rate has returned to normal levels.",
    )


@pytest.mark.asyncio
async def test_send_email_with_empty_body():
    """send_email handles empty body gracefully."""
    dispatcher = NotificationDispatcher()
    await dispatcher.send_email(
        to="admin@example.com",
        subject="Test Alert",
        body="",
    )


# ─── Integration with AlertEngine ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatcher_injectable_into_engine():
    """NotificationDispatcher can be set on AlertEngine via set_notifier."""
    from pipeline.alerts.engine import AlertEngine

    engine = AlertEngine()
    dispatcher = NotificationDispatcher()

    engine.set_notifier(dispatcher)
    assert engine._notifier is dispatcher


@pytest.mark.asyncio
async def test_dispatcher_interface_matches_engine_expectations():
    """NotificationDispatcher has the methods expected by AlertEngine."""
    dispatcher = NotificationDispatcher()

    # Verify the interface methods exist and are callable
    assert hasattr(dispatcher, "send_webhook")
    assert hasattr(dispatcher, "send_email")
    assert callable(dispatcher.send_webhook)
    assert callable(dispatcher.send_email)
