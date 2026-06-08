"""Prove the durable job queue mechanics against the real Postgres (as pdf_app).

Exercises the queue WITHOUT the heavy extraction pipeline, in isolated phases:
  A. two workers claim concurrently -> no double-claim (FOR UPDATE SKIP LOCKED)
  B. retry_later -> the job becomes claimable again, attempts increments
  C. crash recovery -> a stale 'processing' job is reclaimed (stale_seconds=0)

The queue is drained first so the proof is independent of any leftover jobs.

Run:  PYTHONPATH=. .venv/bin/python scripts/queue_proof.py
"""

from __future__ import annotations

import asyncio
import uuid

from db.job_queue import JobQueue
from db.job_repo import JobRepo

TENANT = "queue-proof-tenant"


async def _seed(repo: JobRepo, queue: JobQueue, tag: str) -> str:
    job_id = str(uuid.uuid4())
    await repo.create_job(
        job_id=job_id, tenant_id=TENANT, trace_id=tag,
        filename=f"{tag}.pdf", doc_hash=tag, schema_type=None,
    )
    await queue.enqueue(
        job_id=job_id, tenant_id=TENANT, content=b"%PDF-1.4 x",
        filename=f"{tag}.pdf", doc_hash=tag, schema_type=None,
    )
    return job_id


async def _drain(queue: JobQueue) -> None:
    """Fail every currently-claimable job so the queue starts empty."""
    while True:
        c = await queue.claim("drainer", stale_seconds=0)
        if c is None:
            break
        await queue.fail(c.job_id, c.tenant_id, "drained")


async def main() -> int:
    repo, queue = JobRepo(), JobQueue()
    await repo.ensure_tenant(TENANT, "queue proof", "x", False)
    await _drain(queue)

    # ── A. concurrent claim, no double-claim ──
    a1 = await _seed(repo, queue, "A1")
    a2 = await _seed(repo, queue, "A2")
    c1, c2 = await asyncio.gather(queue.claim("wA"), queue.claim("wB"))
    got = {c.job_id for c in (c1, c2) if c}
    no_double = got == {a1, a2}
    print(f"A concurrent claim -> {sorted(got)}  no_double={no_double}")
    await queue.complete(c1.job_id, TENANT, needs_review=True)
    await queue.complete(c2.job_id, TENANT, needs_review=False)

    # ── B. retry makes the job claimable again, attempts increments ──
    b = await _seed(repo, queue, "B")
    cb = await queue.claim("wB1")
    await queue.retry_later(cb.job_id, TENANT, "transient", delay_seconds=0)
    cb2 = await queue.claim("wB2")
    retry_ok = cb2 is not None and cb2.job_id == b and cb2.attempts == cb.attempts + 1
    print(f"B retry -> reclaimed={cb2 and cb2.job_id == b} attempts {cb.attempts}->{cb2.attempts if cb2 else '?'}  ok={retry_ok}")
    await queue.complete(b, TENANT, needs_review=False)

    # ── C. crash recovery: stale 'processing' job is reclaimed ──
    rid = await _seed(repo, queue, "C")
    first = await queue.claim("wDead")              # leaves it 'processing'
    reclaim = await queue.claim("wLive", stale_seconds=0)  # stale -> reclaim
    recov_ok = first and reclaim and first.job_id == reclaim.job_id == rid and reclaim.attempts == 2
    print(f"C crash recovery -> reclaimed_same={recov_ok} attempts={reclaim.attempts if reclaim else '?'}")
    await queue.complete(rid, TENANT, needs_review=False)

    ok = no_double and retry_ok and recov_ok
    print(f"\nRESULT: {'DURABLE QUEUE PROVEN' if ok else 'INCOMPLETE'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
