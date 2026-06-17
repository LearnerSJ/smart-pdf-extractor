"""Durable job queue operations (Postgres, no external broker).

Companion to JobRepo. The jobs table is the queue; job_payloads holds the input
PDF durably so a crashed job can be reclaimed and reprocessed by another worker.

Claiming is done through the claim_next_job SECURITY DEFINER function (migration
0007): a worker is a system actor that claims across tenants, but the app
connects as the non-superuser pdf_app role with RLS forced, so the controlled
definer-owned function is the only cross-tenant path. Every other operation is
tenant-bound and RLS-validated.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import text

from db.context import set_tenant
from db.session import async_session_factory

logger = structlog.get_logger()


class ClaimedJob:
    """A job claimed from the queue, with its durable payload."""

    __slots__ = ("job_id", "tenant_id", "attempts", "content", "filename", "doc_hash", "schema_type")

    def __init__(self, job_id, tenant_id, attempts, content, filename, doc_hash, schema_type):
        self.job_id = job_id
        self.tenant_id = tenant_id
        self.attempts = attempts
        self.content = content
        self.filename = filename
        self.doc_hash = doc_hash
        self.schema_type = schema_type


class JobQueue:
    """Postgres-backed durable work queue."""

    async def enqueue(
        self, *, job_id: str, tenant_id: str, content: bytes,
        filename: str, doc_hash: str, schema_type: str | None,
    ) -> None:
        """Persist the payload and mark the job queued (job row already created)."""
        async with async_session_factory() as s:
            await set_tenant(s, tenant_id)
            await s.execute(
                text(
                    """
                    INSERT INTO job_payloads (job_id, tenant_id, content, filename, doc_hash, schema_type)
                    VALUES (:jid, :tid, :content, :fn, :dh, :st)
                    ON CONFLICT (job_id) DO NOTHING
                    """
                ),
                {"jid": uuid.UUID(job_id), "tid": tenant_id, "content": content,
                 "fn": filename, "dh": doc_hash, "st": schema_type},
            )
            await s.execute(
                text(
                    "UPDATE jobs SET status='queued', available_at=NOW() "
                    "WHERE id=:jid AND tenant_id=:tid"
                ),
                {"jid": uuid.UUID(job_id), "tid": tenant_id},
            )
            await s.commit()
        logger.info("queue.enqueued", job_id=job_id, tenant_id=tenant_id)

    async def claim(self, worker_id: str, stale_seconds: int = 900) -> ClaimedJob | None:
        """Atomically claim the next queued (or stale-processing) job + its payload.

        Uses the SECURITY DEFINER claim function (FOR UPDATE SKIP LOCKED) so
        concurrent workers never claim the same row, and stale 'processing' rows
        from a crashed worker are reclaimed automatically (crash recovery).
        """
        async with async_session_factory() as s:
            row = (
                await s.execute(
                    text("SELECT job_id, tenant_id, attempts FROM claim_next_job(:w, :st)"),
                    {"w": worker_id, "st": stale_seconds},
                )
            ).first()
            await s.commit()
            if not row:
                return None
            job_id, tenant_id, attempts = row[0], row[1], row[2]

            # Load the payload under the claimed job's tenant (RLS-bound).
            await set_tenant(s, tenant_id)
            prow = (
                await s.execute(
                    text(
                        "SELECT content, filename, doc_hash, schema_type "
                        "FROM job_payloads WHERE job_id=:jid AND tenant_id=:tid"
                    ),
                    {"jid": job_id, "tid": tenant_id},
                )
            ).first()
        if prow is None:
            logger.warning("queue.claim_missing_payload", job_id=str(job_id), tenant_id=tenant_id)
            await self.fail(str(job_id), tenant_id, "payload missing")
            return None
        logger.info("queue.claimed", job_id=str(job_id), tenant_id=tenant_id,
                    worker=worker_id, attempts=attempts)
        return ClaimedJob(
            job_id=str(job_id), tenant_id=tenant_id, attempts=attempts,
            content=bytes(prow[0]), filename=prow[1], doc_hash=prow[2], schema_type=prow[3],
        )

    async def complete(self, job_id: str, tenant_id: str, *, needs_review: bool) -> None:
        """Mark a job complete, set the review flag, and drop the payload."""
        async with async_session_factory() as s:
            await set_tenant(s, tenant_id)
            await s.execute(
                text(
                    "UPDATE jobs SET status='complete', completed_at=NOW(), "
                    "needs_review=:nr, claimed_at=NULL WHERE id=:jid AND tenant_id=:tid"
                ),
                {"nr": needs_review, "jid": uuid.UUID(job_id), "tid": tenant_id},
            )
            await s.execute(
                text("DELETE FROM job_payloads WHERE job_id=:jid AND tenant_id=:tid"),
                {"jid": uuid.UUID(job_id), "tid": tenant_id},
            )
            await s.commit()

    async def retry_later(self, job_id: str, tenant_id: str, error: str, delay_seconds: int) -> None:
        """Requeue a job after a transient failure, with a backoff delay."""
        async with async_session_factory() as s:
            await set_tenant(s, tenant_id)
            await s.execute(
                text(
                    "UPDATE jobs SET status='queued', "
                    "available_at = NOW() + make_interval(secs => :d), "
                    "last_error=:err, claimed_at=NULL WHERE id=:jid AND tenant_id=:tid"
                ),
                {"d": delay_seconds, "err": error[:1000], "jid": uuid.UUID(job_id), "tid": tenant_id},
            )
            await s.commit()
        logger.info("queue.retry_scheduled", job_id=job_id, delay_seconds=delay_seconds)

    async def fail(self, job_id: str, tenant_id: str, error: str) -> None:
        """Mark a job permanently failed and drop the payload."""
        async with async_session_factory() as s:
            await set_tenant(s, tenant_id)
            await s.execute(
                text(
                    "UPDATE jobs SET status='failed', completed_at=NOW(), "
                    "last_error=:err, claimed_at=NULL WHERE id=:jid AND tenant_id=:tid"
                ),
                {"err": error[:1000], "jid": uuid.UUID(job_id), "tid": tenant_id},
            )
            await s.execute(
                text("DELETE FROM job_payloads WHERE job_id=:jid AND tenant_id=:tid"),
                {"jid": uuid.UUID(job_id), "tid": tenant_id},
            )
            await s.commit()
        logger.warning("queue.failed", job_id=job_id, error=error[:200])
