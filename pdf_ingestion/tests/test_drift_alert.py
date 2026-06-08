"""Tests for the abstention-rate (drift) alert rule state machine.

Pure logic — JobRepo.abstention_stats is monkeypatched so no DB is needed.
"""

from __future__ import annotations

import pytest

import db.job_repo as job_repo_mod
from pipeline.alerts.engine import AlertEngine


class _CaptureNotifier:
    def __init__(self) -> None:
        self.webhooks: list[dict] = []

    async def send_webhook(self, target, payload) -> None:
        self.webhooks.append(payload)

    async def send_email(self, target, subject, body) -> None:
        self.webhooks.append({"subject": subject})


def _rule() -> dict:
    return {
        "id": "drift-1",
        "rule_type": "abstention_rate",
        "enabled": True,
        "state": "idle",
        "tenant_id": "tenant-x",
        "notification_channel": "webhook",
        "notification_target": "https://example.test/hook",
        "name": "Drift",
        "config": {"threshold_percent": 20.0, "evaluation_window_minutes": 60},
    }


def _patch_stats(monkeypatch, total: int, flagged: int) -> None:
    async def fake(self, window_minutes, tenant_id=None):
        return total, flagged

    monkeypatch.setattr(job_repo_mod.JobRepo, "abstention_stats", fake)


@pytest.mark.asyncio
async def test_fires_when_abstention_rate_exceeds_threshold(monkeypatch) -> None:
    _patch_stats(monkeypatch, total=10, flagged=5)  # 50% > 20%
    engine = AlertEngine()
    notifier = _CaptureNotifier()
    engine.set_notifier(notifier)
    rule = _rule()

    await engine.evaluate_abstention_rate_rule(rule)
    assert rule["state"] == "firing"
    assert len(notifier.webhooks) == 1
    assert notifier.webhooks[0]["context"]["actual_percent"] == 50.0


@pytest.mark.asyncio
async def test_stays_idle_below_threshold(monkeypatch) -> None:
    _patch_stats(monkeypatch, total=10, flagged=1)  # 10% < 20%
    engine = AlertEngine()
    engine.set_notifier(_CaptureNotifier())
    rule = _rule()

    await engine.evaluate_abstention_rate_rule(rule)
    assert rule["state"] == "idle"


@pytest.mark.asyncio
async def test_resolves_when_rate_recovers(monkeypatch) -> None:
    engine = AlertEngine()
    notifier = _CaptureNotifier()
    engine.set_notifier(notifier)
    rule = _rule()

    _patch_stats(monkeypatch, total=10, flagged=5)  # fire
    await engine.evaluate_abstention_rate_rule(rule)
    assert rule["state"] == "firing"

    _patch_stats(monkeypatch, total=10, flagged=0)  # recover
    await engine.evaluate_abstention_rate_rule(rule)
    assert rule["state"] == "resolved"


@pytest.mark.asyncio
async def test_no_jobs_does_not_fire(monkeypatch) -> None:
    _patch_stats(monkeypatch, total=0, flagged=0)
    engine = AlertEngine()
    engine.set_notifier(_CaptureNotifier())
    rule = _rule()

    await engine.evaluate_abstention_rate_rule(rule)
    assert rule["state"] == "idle"
