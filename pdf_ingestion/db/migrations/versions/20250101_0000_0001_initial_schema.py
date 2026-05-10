"""Initial schema — tenants, batches, jobs, results, feedback, vlm_usage, delivery_logs.

Revision ID: 0001
Revises: None
Create Date: 2025-01-01 00:00:00.000000+00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tenants
    op.create_table(
        "tenants",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("api_key_hash", sa.Text(), nullable=False),
        sa.Column("vlm_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_suspended", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("redaction_config", postgresql.JSONB(), nullable=True),
        sa.Column("delivery_config", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Batches
    op.create_table(
        "batches",
        sa.Column("batch_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(50), nullable=False, server_default="pending"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_status", sa.String(50), nullable=True),
        sa.PrimaryKeyConstraint("batch_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )

    # Jobs
    op.create_table(
        "jobs",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("batch_id", sa.Text(), nullable=True),
        sa.Column("schema_type", sa.String(100), nullable=True),
        sa.Column(
            "status", sa.String(50), nullable=False, server_default="submitted"
        ),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("doc_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.batch_id"]),
    )
    op.create_index("idx_jobs_batch", "jobs", ["batch_id"])
    op.create_index("idx_jobs_tenant", "jobs", ["tenant_id"])

    # Results
    op.create_table(
        "results",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "job_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("output", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
    )

    # Feedback
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "job_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("field_name", sa.Text(), nullable=False),
        sa.Column("table_id", sa.Text(), nullable=True),
        sa.Column("extracted_value", sa.Text(), nullable=True),
        sa.Column("correct_value", sa.Text(), nullable=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("triangulation_score", sa.Float(), nullable=True),
        sa.Column("vlm_was_used", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
    )
    op.create_index("idx_feedback_tenant", "feedback", ["tenant_id"])
    op.create_index("idx_feedback_job", "feedback", ["job_id"])
    op.create_index("idx_feedback_field", "feedback", ["field_name"])

    # VLM Usage
    op.create_table(
        "vlm_usage",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "job_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("field_name", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
    )

    # Delivery Logs
    op.create_table(
        "delivery_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.Text(), nullable=True),
        sa.Column(
            "job_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("callback_url", sa.Text(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.batch_id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
    )


def downgrade() -> None:
    op.drop_table("delivery_logs")
    op.drop_table("vlm_usage")
    op.drop_index("idx_feedback_field", table_name="feedback")
    op.drop_index("idx_feedback_job", table_name="feedback")
    op.drop_index("idx_feedback_tenant", table_name="feedback")
    op.drop_table("feedback")
    op.drop_table("results")
    op.drop_index("idx_jobs_tenant", table_name="jobs")
    op.drop_index("idx_jobs_batch", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("batches")
    op.drop_table("tenants")
