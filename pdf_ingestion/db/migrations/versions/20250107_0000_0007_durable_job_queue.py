"""Durable job queue — Postgres-backed, crash-recoverable, no external broker.

Turns the jobs table into a work queue and persists the input PDF so a job
survives a process crash and can be reclaimed by another worker:

- jobs gains queue columns: attempts, claimed_at, claimed_by, available_at,
  last_error, needs_review.
- job_payloads stores the input bytes (BYTEA) durably, tenant-scoped under RLS.
- claim_next_job(worker, stale_seconds) is a SECURITY DEFINER function: a worker
  is a SYSTEM actor that must claim across tenants, but the app connects as the
  non-superuser pdf_app role with RLS forced. Encapsulating the FOR UPDATE SKIP
  LOCKED claim in a definer-owned function gives the worker a controlled,
  auditable cross-tenant claim path WITHOUT granting it blanket RLS bypass. The
  same query reclaims stale 'processing' rows (crash recovery) in one step.

Revision ID: 0007
Revises: 0006
Create Date: 2025-01-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CLAIM_FN = """
CREATE OR REPLACE FUNCTION claim_next_job(p_worker text, p_stale_seconds integer DEFAULT 900)
RETURNS TABLE(job_id uuid, tenant_id text, attempts integer)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    UPDATE jobs
       SET status = 'processing',
           claimed_at = NOW(),
           claimed_by = p_worker,
           attempts = attempts + 1
     WHERE id = (
         SELECT id FROM jobs
          WHERE (status = 'queued' AND available_at <= NOW())
             OR (status = 'processing'
                 AND claimed_at < NOW() - make_interval(secs => p_stale_seconds))
          ORDER BY available_at
          FOR UPDATE SKIP LOCKED
          LIMIT 1
     )
    RETURNING jobs.id, jobs.tenant_id, jobs.attempts;
$$;
"""


def upgrade() -> None:
    op.add_column("jobs", sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("jobs", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("claimed_by", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")))
    op.add_column("jobs", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    # Claim hot-path index: queued/stale rows ordered by availability.
    op.create_index("idx_jobs_queue_claim", "jobs", ["status", "available_at"])

    op.create_table(
        "job_payloads",
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("doc_hash", sa.Text(), nullable=False),
        sa.Column("schema_type", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )

    # RLS: payloads are strictly tenant-scoped (same policy shape as jobs).
    op.execute("ALTER TABLE job_payloads ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE job_payloads FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON job_payloads "
        "USING (tenant_id = current_setting('app.current_tenant', true)) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant', true))"
    )

    op.execute(CLAIM_FN)

    # Grant the runtime role access to the new objects (guarded — the role only
    # exists in environments where RLS enforcement is activated).
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pdf_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON job_payloads TO pdf_app;
                GRANT EXECUTE ON FUNCTION claim_next_job(text, integer) TO pdf_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS claim_next_job(text, integer)")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON job_payloads")
    op.drop_table("job_payloads")
    op.drop_index("idx_jobs_queue_claim", table_name="jobs")
    for col in ("needs_review", "last_error", "available_at", "claimed_by", "claimed_at", "attempts"):
        op.drop_column("jobs", col)
