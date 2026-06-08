"""Durable job worker pool.

A small pool of async workers that drain the Postgres-backed queue (db.job_queue).
Each worker claims a job via the SECURITY DEFINER claim function (FOR UPDATE SKIP
LOCKED), reconstructs the tenant, runs the extraction pipeline, and records the
outcome:

- success            -> queue.complete (needs_review = had abstentions)
- pipeline failure   -> queue.fail (deterministic; e.g. unreadable PDF — no retry)
- raised exception   -> transient: retry with backoff up to max_attempts, then fail

Crash recovery is free: claim_next_job also reclaims 'processing' rows whose
worker died (claimed_at older than stale_seconds), so an in-flight job from a
crashed process is picked up by a live worker.

Runs in the API process today (asyncio tasks); the same JobQueue + claim function
work unchanged across multiple worker processes/hosts when scaling out.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog

from api.models.tenant import TenantContext

logger = structlog.get_logger()

# Failure means a re-run will fail the same way (bad input), so we do NOT retry a
# pipeline-reported failure — only raised exceptions (infra/transient) are retried.
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_POLL_INTERVAL = 1.0  # seconds between empty-claim polls
DEFAULT_STALE_SECONDS = 900  # reclaim a job whose worker has been silent this long


class JobWorkerPool:
    """Pool of async workers draining the durable queue."""

    def __init__(
        self,
        template_store: object = None,
        schema_cache: object = None,
        n_workers: int = 2,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        stale_seconds: int = DEFAULT_STALE_SECONDS,
    ) -> None:
        self._template_store = template_store
        self._schema_cache = schema_cache
        self._n = n_workers
        self._poll = poll_interval
        self._max_attempts = max_attempts
        self._stale_seconds = stale_seconds
        self._tasks: list[asyncio.Task] = []
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tasks = [asyncio.create_task(self._loop(f"w{i}")) for i in range(self._n)]
        logger.info("worker_pool.started", workers=self._n)

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks = []
        logger.info("worker_pool.stopped")

    async def _loop(self, worker_id: str) -> None:
        from db.job_queue import JobQueue

        queue = JobQueue()
        while self._running:
            try:
                claimed = await queue.claim(worker_id, stale_seconds=self._stale_seconds)
            except Exception as e:  # noqa: BLE001 — never let one bad claim kill the loop
                logger.warning("worker.claim_error", worker=worker_id, error=str(e))
                await asyncio.sleep(self._poll)
                continue
            if claimed is None:
                await asyncio.sleep(self._poll)
                continue
            await self._process(queue, claimed)

    async def _process(self, queue, claimed) -> None:
        from api.routes.extract import execute_pipeline, record_job_result
        from db.job_repo import JobRepo

        trace_id = str(uuid.uuid4())
        tenant = await self._build_tenant(claimed.tenant_id)

        try:
            status, output_dict, abstentions = await execute_pipeline(
                job_id=claimed.job_id,
                file_bytes=claimed.content,
                filename=claimed.filename,
                doc_hash=claimed.doc_hash,
                schema_type=claimed.schema_type,
                tenant=tenant,
                trace_id=trace_id,
                schema_cache=self._schema_cache,
                template_store=self._template_store,
            )
        except Exception as e:  # transient/infra — retry with backoff, then give up
            if claimed.attempts < self._max_attempts:
                delay = min(60, 2 ** claimed.attempts)
                await queue.retry_later(claimed.job_id, claimed.tenant_id, str(e), delay)
            else:
                logger.error("worker.exhausted_retries", job_id=claimed.job_id, error=str(e))
                await queue.fail(claimed.job_id, claimed.tenant_id, str(e))
                record_job_result(
                    job_id=claimed.job_id, tenant_id=claimed.tenant_id, trace_id=trace_id,
                    status="failed", output_dict={"error": str(e)},
                )
                await JobRepo().save_result(claimed.job_id, claimed.tenant_id, {"error": str(e)})
            return

        # Persist the result row, then close out the queue entry.
        needs_review = bool(abstentions)
        try:
            await JobRepo().save_result(claimed.job_id, claimed.tenant_id, output_dict)
        except Exception as e:  # noqa: BLE001
            logger.warning("worker.save_result_failed", job_id=claimed.job_id, error=str(e))

        if status == "failed":
            await queue.fail(claimed.job_id, claimed.tenant_id, output_dict.get("error", "failed"))
        else:
            await queue.complete(claimed.job_id, claimed.tenant_id, needs_review=needs_review)

        record_job_result(
            job_id=claimed.job_id, tenant_id=claimed.tenant_id, trace_id=trace_id,
            status=status, output_dict=output_dict,
        )
        logger.info(
            "worker.job_done", job_id=claimed.job_id, status=status, needs_review=needs_review,
        )

    async def _build_tenant(self, tenant_id: str) -> TenantContext:
        """Reconstruct a TenantContext from the tenants table (worker has no request)."""
        from db.job_repo import JobRepo

        row = await JobRepo().get_tenant(tenant_id)
        if row is None:
            # Tenant row missing — process with VLM disabled, deterministic only.
            return TenantContext(id=tenant_id, name=tenant_id, api_key_hash="", vlm_enabled=False)
        return TenantContext(
            id=row["id"], name=row["name"],
            api_key_hash=row["api_key_hash"] or "", vlm_enabled=bool(row["vlm_enabled"]),
        )
