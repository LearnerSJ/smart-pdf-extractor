"""Admin dashboard tables — dashboard_users, role_assignments, alert_rules,
alert_history, structured_logs, token_revocations.

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-02 00:00:00.000000+00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Dashboard Users
    op.create_table(
        "dashboard_users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    # Role Assignments
    op.create_table(
        "role_assignments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["dashboard_users.id"]),
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_role_user_tenant"),
    )

    # Alert Rules
    op.create_table(
        "alert_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("rule_type", sa.String(30), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("notification_channel", sa.String(20), nullable=False),
        sa.Column("notification_target", sa.Text(), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "state", sa.String(20), nullable=False, server_default="idle"
        ),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["created_by"], ["dashboard_users.id"]),
    )

    # Alert History
    op.create_table(
        "alert_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "rule_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "notification_sent",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "acknowledged_by", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["rule_id"], ["alert_rules.id"]),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["dashboard_users.id"]),
    )

    # Structured Logs
    op.create_table(
        "structured_logs",
        sa.Column(
            "id", sa.BigInteger(), autoincrement=True, nullable=False
        ),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("event_name", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("fields", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_logs_trace_id", "structured_logs", ["trace_id"]
    )
    op.create_index(
        "idx_logs_tenant_time", "structured_logs", ["tenant_id", "timestamp"]
    )
    op.create_index(
        "idx_logs_severity_time", "structured_logs", ["severity", "timestamp"]
    )
    op.create_index(
        "idx_logs_job_id", "structured_logs", ["job_id"]
    )

    # Token Revocations
    op.create_table(
        "token_revocations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("jti", sa.Text(), nullable=False),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti"),
    )


def downgrade() -> None:
    op.drop_table("token_revocations")
    op.drop_index("idx_logs_job_id", table_name="structured_logs")
    op.drop_index("idx_logs_severity_time", table_name="structured_logs")
    op.drop_index("idx_logs_tenant_time", table_name="structured_logs")
    op.drop_index("idx_logs_trace_id", table_name="structured_logs")
    op.drop_table("structured_logs")
    op.drop_table("alert_history")
    op.drop_table("alert_rules")
    op.drop_table("role_assignments")
    op.drop_table("dashboard_users")
