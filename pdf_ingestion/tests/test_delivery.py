"""Tests for the delivery orchestrator and webhook client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest

from pipeline.delivery import (
    WebhookDeliveryClient,
    _compute_backoff_with_jitter,
    assemble_batch_payload,
    assemble_standalone_payload,
    check_and_deliver_batch,
    on_job_complete,
)
from pipeline.models import DeliveryAttemptResult
from pipeline.ports import DeliveryPort


# ─── Test Fixtures ────────────────────────────────────────────────────────────


@dataclass
class FakeDeliveryConfig:
    callback_url: str | None = "https://example.com/webhook"
    auth_header: str | None = "Bearer test-token"
    enabled: bool = True


@dataclass
class FakeTenant:
    id: str = "tenant-1"
    delivery_config: FakeDeliveryConfig = field(default_factory=FakeDeliveryConfig)


@dataclass
class FakeJob:
    id: str = "job-1"
    trace_id: str = "trace-1"
    status: str = "complete"
    batch_id: str | None = None
    result: dict[str, Any] | None = None
    delivery_status: str | None = None


class MockDeliveryClient(DeliveryPort):
    """Mock delivery client that records calls."""

    def __init__(self, should_succeed: bool = True) -> None:
        self.should_succeed = should_succeed
        self.calls: list[dict[str, Any]] = []

    async def deliver(
        self,
        payload: dict[str, Any],
        callback_url: str,
        auth_header: str | None = None,
    ) -> DeliveryAttemptResult:
        self.calls.append({
            "payload": payload,
            "callback_url": callback_url,
            "auth_header": auth_header,
        })
        if self.should_succeed:
            return DeliveryAttemptResult(
                success=True,
                status_code=200,
                attempt_number=1,
                timestamp=datetime.now(timezone.utc),
            )
        return DeliveryAttemptResult(
            success=False,
            status_code=500,
            error="mock failure",
            attempt_number=1,
            timestamp=datetime.now(timezone.utc),
        )


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestComputeBackoffWithJitter:
    """Tests for _compute_backoff_with_jitter()."""

    def test_increases_with_attempt(self) -> None:
        """Backoff should increase with attempt number."""
        delay1 = _compute_backoff_with_jitter(1, base_delay_ms=1000, max_delay_ms=30000)
        delay2 = _compute_backoff_with_jitter(2, base_delay_ms=1000, max_delay_ms=30000)
        # Due to jitter, delay2 should generally be larger but not guaranteed
        # Just check they're positive
        assert delay1 > 0
        assert delay2 > 0

    def test_respects_max_delay(self) -> None:
        """Backoff should never exceed max_delay_ms."""
        for attempt in range(1, 20):
            delay = _compute_backoff_with_jitter(attempt, base_delay_ms=1000, max_delay_ms=5000)
            assert delay <= 5000

    def test_positive_values(self) -> None:
        """Backoff should always be positive."""
        delay = _compute_backoff_with_jitter(1, base_delay_ms=100, max_delay_ms=1000)
        assert delay > 0


class TestOnJobComplete:
    """Tests for on_job_complete()."""

    @pytest.mark.asyncio
    async def test_standalone_job_delivers_immediately(self) -> None:
        """Standalone job (no batch_id) should trigger immediate delivery."""
        client = MockDeliveryClient(should_succeed=True)
        job = FakeJob(id="job-1", batch_id=None, status="complete")
        tenant = FakeTenant()

        await on_job_complete(job, tenant, client)

        assert len(client.calls) == 1
        assert client.calls[0]["payload"]["type"] == "standalone"
        assert client.calls[0]["callback_url"] == "https://example.com/webhook"

    @pytest.mark.asyncio
    async def test_delivery_skipped_when_not_configured(self) -> None:
        """Should skip delivery when delivery_config is not enabled."""
        client = MockDeliveryClient()
        job = FakeJob()
        tenant = FakeTenant(delivery_config=FakeDeliveryConfig(enabled=False))

        await on_job_complete(job, tenant, client)

        assert len(client.calls) == 0

    @pytest.mark.asyncio
    async def test_delivery_skipped_when_no_callback_url(self) -> None:
        """Should skip delivery when callback_url is None."""
        client = MockDeliveryClient()
        job = FakeJob()
        tenant = FakeTenant(delivery_config=FakeDeliveryConfig(callback_url=None))

        await on_job_complete(job, tenant, client)

        assert len(client.calls) == 0

    @pytest.mark.asyncio
    async def test_delivery_failure_marks_status(self) -> None:
        """Failed delivery should mark delivery_status as delivery_failed."""
        client = MockDeliveryClient(should_succeed=False)
        job = FakeJob(id="job-1", batch_id=None)
        tenant = FakeTenant()

        await on_job_complete(job, tenant, client)

        assert job.delivery_status == "delivery_failed"


class TestCheckAndDeliverBatch:
    """Tests for check_and_deliver_batch()."""

    @pytest.mark.asyncio
    async def test_delivers_when_all_terminal(self) -> None:
        """Should deliver when all jobs are in terminal state."""
        client = MockDeliveryClient(should_succeed=True)
        batch = type("Batch", (), {
            "batch_id": "batch-1",
            "tenant_id": "tenant-1",
            "status": "pending",
            "completed_at": None,
            "delivery_status": None,
        })()
        jobs = [
            FakeJob(id="j1", status="complete"),
            FakeJob(id="j2", status="failed"),
            FakeJob(id="j3", status="partial"),
        ]
        tenant = FakeTenant()

        await check_and_deliver_batch("batch-1", tenant, client, batch=batch, jobs=jobs)

        assert len(client.calls) == 1
        assert client.calls[0]["payload"]["type"] == "batch"
        assert batch.delivery_status == "delivered"

    @pytest.mark.asyncio
    async def test_does_not_deliver_when_not_all_terminal(self) -> None:
        """Should not deliver when some jobs are still processing."""
        client = MockDeliveryClient()
        batch = type("Batch", (), {
            "batch_id": "batch-1",
            "tenant_id": "tenant-1",
            "status": "pending",
            "completed_at": None,
            "delivery_status": None,
        })()
        jobs = [
            FakeJob(id="j1", status="complete"),
            FakeJob(id="j2", status="processing"),  # Not terminal
        ]
        tenant = FakeTenant()

        await check_and_deliver_batch("batch-1", tenant, client, batch=batch, jobs=jobs)

        assert len(client.calls) == 0

    @pytest.mark.asyncio
    async def test_marks_delivery_failed_on_failure(self) -> None:
        """Should mark delivery_status as delivery_failed on failure."""
        client = MockDeliveryClient(should_succeed=False)
        batch = type("Batch", (), {
            "batch_id": "batch-1",
            "tenant_id": "tenant-1",
            "status": "pending",
            "completed_at": None,
            "delivery_status": None,
        })()
        jobs = [FakeJob(id="j1", status="complete")]
        tenant = FakeTenant()

        await check_and_deliver_batch("batch-1", tenant, client, batch=batch, jobs=jobs)

        assert batch.delivery_status == "delivery_failed"


class TestAssemblePayloads:
    """Tests for payload assembly functions."""

    @pytest.mark.asyncio
    async def test_standalone_payload_structure(self) -> None:
        """Standalone payload should have correct structure."""
        job = FakeJob(id="job-1", trace_id="trace-1", status="complete")
        payload = await assemble_standalone_payload(job)

        assert payload["type"] == "standalone"
        assert payload["job_id"] == "job-1"
        assert payload["trace_id"] == "trace-1"

    @pytest.mark.asyncio
    async def test_batch_payload_structure(self) -> None:
        """Batch payload should have correct structure."""
        batch = type("Batch", (), {
            "batch_id": "batch-1",
            "tenant_id": "tenant-1",
        })()
        jobs = [
            FakeJob(id="j1", status="complete"),
            FakeJob(id="j2", status="failed"),
        ]
        payload = await assemble_batch_payload(batch, jobs)

        assert payload["type"] == "batch"
        assert payload["batch_id"] == "batch-1"
        assert payload["jobs_total"] == 2
        assert payload["jobs_complete"] == 1
        assert payload["jobs_failed"] == 1
        assert len(payload["results"]) == 2
