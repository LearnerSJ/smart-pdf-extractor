"""Feedback / correction persistence (Postgres).

Stores user corrections in the feedback table (migration 0001), tenant-scoped
under RLS (migration 0006). A correction is ground-truth: the value a human says
is right when extraction got it wrong or abstained. Persisted here, surfaced via
GET /v1/feedback, and available as a future re-learn signal for the template tier.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import text

from db.context import set_tenant
from db.session import async_session_factory

logger = structlog.get_logger()


class FeedbackRepo:
    """Tenant-scoped correction store backed by the feedback table."""

    async def create(
        self,
        *,
        job_id: str,
        tenant_id: str,
        field_name: str,
        correct_value: str,
        extracted_value: str | None = None,
        table_id: str | None = None,
        notes: str | None = None,
        source: str = "correction_api",
    ) -> int:
        """Insert a correction; returns the new feedback id."""
        async with async_session_factory() as s:
            await set_tenant(s, tenant_id)
            row = (
                await s.execute(
                    text(
                        """
                        INSERT INTO feedback
                            (job_id, tenant_id, field_name, table_id,
                             extracted_value, correct_value, source, notes)
                        VALUES
                            (:jid, :tid, :fn, :tbl, :ev, :cv, :src, :notes)
                        RETURNING id
                        """
                    ),
                    {
                        "jid": uuid.UUID(job_id), "tid": tenant_id, "fn": field_name,
                        "tbl": table_id, "ev": extracted_value, "cv": correct_value,
                        "src": source, "notes": notes,
                    },
                )
            ).first()
            await s.commit()
        fid = int(row[0]) if row else 0
        logger.info("feedback.persisted", feedback_id=fid, job_id=job_id,
                    tenant_id=tenant_id, field_name=field_name, source=source)
        return fid

    async def list_for_tenant(self, tenant_id: str, limit: int = 500) -> list[dict]:
        """Return corrections for a tenant, newest first, shaped for the UI."""
        async with async_session_factory() as s:
            await set_tenant(s, tenant_id)
            rows = (
                await s.execute(
                    text(
                        """
                        SELECT id, job_id, field_name, table_id,
                               extracted_value, correct_value, source, notes, created_at
                          FROM feedback
                         WHERE tenant_id = :tid
                         ORDER BY created_at DESC
                         LIMIT :lim
                        """
                    ),
                    {"tid": tenant_id, "lim": limit},
                )
            ).mappings().all()
        return [
            {
                "feedback_id": r["id"],
                "job_id": str(r["job_id"]),
                "field_name": r["field_name"],
                "table_id": r["table_id"],
                "original_value": r["extracted_value"],
                "corrected_value": r["correct_value"],
                "source": r["source"],
                "notes": r["notes"],
                "submitted_by": tenant_id,
                "submitted_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
