"""Durable job + result persistence (Postgres).

Dual-write companion to the in-memory _JOBS/_RESULTS caches in api.routes.extract:
the cache stays the fast read path, this repo is the durable, tenant-scoped
backing. On startup the cache is warmed from here, so jobs/results survive a
restart. Every session sets the app.current_tenant GUC so Postgres RLS (migration
0006) enforces tenant isolation when the app connects as a non-superuser role.
"""

from __future__ import annotations

import json
import uuid

import structlog
from sqlalchemy import text

from db.session import async_session_factory

logger = structlog.get_logger()


async def _set_tenant(session, tenant_id: str) -> None:
    """Bind the tenant for this transaction so RLS policies apply."""
    await session.execute(
        text("SELECT set_config('app.current_tenant', :tid, true)"),
        {"tid": tenant_id},
    )


class JobRepo:
    """Postgres-backed job + result store, tenant-scoped."""

    async def ensure_tenant(self, tenant_id: str, name: str, api_key_hash: str, vlm_enabled: bool) -> None:
        async with async_session_factory() as s:
            await _set_tenant(s, tenant_id)
            await s.execute(
                text(
                    """
                    INSERT INTO tenants (id, name, api_key_hash, vlm_enabled)
                    VALUES (:id, :name, :akh, :vlm)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"id": tenant_id, "name": name, "akh": api_key_hash, "vlm": vlm_enabled},
            )
            await s.commit()

    async def create_job(
        self, *, job_id: str, tenant_id: str, trace_id: str, filename: str,
        doc_hash: str, schema_type: str | None, status: str = "processing",
    ) -> None:
        async with async_session_factory() as s:
            await _set_tenant(s, tenant_id)
            await s.execute(
                text(
                    """
                    INSERT INTO jobs (id, tenant_id, trace_id, filename, doc_hash,
                                      schema_type, status)
                    VALUES (:id, :tid, :trace, :fn, :dh, :st, :status)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"id": uuid.UUID(job_id), "tid": tenant_id, "trace": trace_id,
                 "fn": filename, "dh": doc_hash, "st": schema_type, "status": status},
            )
            await s.commit()

    async def set_status(self, job_id: str, tenant_id: str, status: str) -> None:
        async with async_session_factory() as s:
            await _set_tenant(s, tenant_id)
            await s.execute(
                text(
                    "UPDATE jobs SET status = :st, completed_at = NOW() "
                    "WHERE id = :id AND tenant_id = :tid"
                ),
                {"st": status, "id": uuid.UUID(job_id), "tid": tenant_id},
            )
            await s.commit()

    async def save_result(self, job_id: str, tenant_id: str, output: dict) -> None:
        async with async_session_factory() as s:
            await _set_tenant(s, tenant_id)
            await s.execute(
                text(
                    """
                    INSERT INTO results (id, job_id, tenant_id, output)
                    VALUES (:id, :jid, :tid, CAST(:out AS JSONB))
                    """
                ),
                {"id": uuid.uuid4(), "jid": uuid.UUID(job_id), "tid": tenant_id,
                 "out": json.dumps(output)},
            )
            await s.commit()

    async def load_all(self) -> tuple[dict, dict]:
        """Load every job + latest result into _JOBS / _RESULTS shaped dicts (cache warm)."""
        jobs: dict[str, dict] = {}
        results: dict[str, dict] = {}
        async with async_session_factory() as s:
            jrows = (await s.execute(
                text("SELECT id, tenant_id, trace_id, filename, doc_hash, schema_type, "
                     "status, created_at, completed_at FROM jobs")
            )).mappings().all()
            for r in jrows:
                jid = str(r["id"])
                jobs[jid] = {
                    "job_id": jid, "tenant_id": r["tenant_id"], "trace_id": r["trace_id"],
                    "filename": r["filename"], "doc_hash": r["doc_hash"],
                    "schema_type": r["schema_type"], "status": r["status"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
                }
            rrows = (await s.execute(
                text("SELECT DISTINCT ON (job_id) job_id, tenant_id, output "
                     "FROM results ORDER BY job_id, created_at DESC")
            )).mappings().all()
            for r in rrows:
                jid = str(r["job_id"])
                results[jid] = {"job_id": jid, "tenant_id": r["tenant_id"], "output": r["output"]}
        return jobs, results
