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

    async def get_tenant(self, tenant_id: str) -> dict | None:
        """Load a tenant row (for workers reconstructing a TenantContext)."""
        async with async_session_factory() as s:
            await _set_tenant(s, tenant_id)
            row = (
                await s.execute(
                    text("SELECT id, name, api_key_hash, vlm_enabled FROM tenants WHERE id=:id"),
                    {"id": tenant_id},
                )
            ).mappings().first()
        return dict(row) if row else None

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

    async def abstention_stats(
        self, window_minutes: int, tenant_id: str | None = None
    ) -> tuple[int, int]:
        """(completed_jobs, flagged_jobs) in the window — the drift signal.

        Tenant-scoped under RLS; for a global rule (tenant_id is None) iterate
        tenants and sum, since a tenant-less query sees zero rows under RLS.
        """
        per_tenant = text(
            """
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE needs_review) AS flagged
              FROM jobs
             WHERE tenant_id = :tid
               AND status IN ('complete', 'completed')
               AND completed_at >= NOW() - make_interval(mins => :w)
            """
        )
        async with async_session_factory() as s:
            tenant_ids = (
                [tenant_id]
                if tenant_id
                else [r[0] for r in (await s.execute(text("SELECT id FROM tenants"))).all()]
            )
            total = flagged = 0
            for tid in tenant_ids:
                await _set_tenant(s, tid)
                row = (await s.execute(per_tenant, {"tid": tid, "w": window_minutes})).first()
                if row:
                    total += int(row[0] or 0)
                    flagged += int(row[1] or 0)
        return total, flagged

    async def get_result_schema_type(self, job_id: str, tenant_id: str) -> str | None:
        """The schema_type recorded in a job's latest result (e.g. 'template:...')."""
        async with async_session_factory() as s:
            await _set_tenant(s, tenant_id)
            row = (
                await s.execute(
                    text(
                        "SELECT output->>'schema_type' FROM results "
                        "WHERE job_id = :jid AND tenant_id = :tid "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"jid": uuid.UUID(job_id), "tid": tenant_id},
                )
            ).first()
        return row[0] if row else None

    async def list_needs_review(self, tenant_id: str, limit: int = 100) -> list[dict]:
        """Jobs flagged for human review (had abstentions), newest first.

        Joins the latest result so the caller sees WHAT abstained without a
        second round-trip. Tenant-scoped — RLS confines it to the caller's rows.
        """
        sql = text(
            """
            SELECT j.id, j.filename, j.schema_type, j.completed_at, j.attempts,
                   r.output
              FROM jobs j
              LEFT JOIN LATERAL (
                  SELECT output FROM results
                   WHERE job_id = j.id AND tenant_id = :tid
                   ORDER BY created_at DESC LIMIT 1
              ) r ON true
             WHERE j.tenant_id = :tid AND j.needs_review = true
             ORDER BY j.completed_at DESC NULLS LAST
             LIMIT :lim
            """
        )
        async with async_session_factory() as s:
            await _set_tenant(s, tenant_id)
            rows = (await s.execute(sql, {"tid": tenant_id, "lim": limit})).mappings().all()
        out: list[dict] = []
        for r in rows:
            output = r["output"] or {}
            if isinstance(output, str):
                output = json.loads(output)
            abstentions = output.get("abstentions", []) if isinstance(output, dict) else []
            out.append({
                "job_id": str(r["id"]),
                "filename": r["filename"],
                "schema_type": r["schema_type"],
                "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
                "attempts": r["attempts"],
                "abstention_count": len(abstentions),
                "abstentions": abstentions,
            })
        return out

    async def acknowledge_review(self, job_id: str, tenant_id: str) -> bool:
        """Clear the review flag once a human has handled a job. Returns True if updated."""
        async with async_session_factory() as s:
            await _set_tenant(s, tenant_id)
            res = await s.execute(
                text(
                    "UPDATE jobs SET needs_review = false "
                    "WHERE id = :jid AND tenant_id = :tid AND needs_review = true"
                ),
                {"jid": uuid.UUID(job_id), "tid": tenant_id},
            )
            await s.commit()
            return res.rowcount > 0

    async def load_all(self) -> tuple[dict, dict]:
        """Load every job + latest result into _JOBS / _RESULTS shaped dicts (cache warm).

        RLS-aware: jobs/results are tenant-scoped, so a tenant must be bound per
        query or the policy returns zero rows. Iterate every tenant (the tenants
        table is not RLS-protected) and union their visible rows.
        """
        jobs: dict[str, dict] = {}
        results: dict[str, dict] = {}
        async with async_session_factory() as s:
            tenant_ids = [
                r[0] for r in (await s.execute(text("SELECT id FROM tenants"))).all()
            ]
            for tid in tenant_ids:
                await _set_tenant(s, tid)
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
