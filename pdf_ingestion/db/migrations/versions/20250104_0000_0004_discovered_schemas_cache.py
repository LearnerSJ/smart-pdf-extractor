"""Schema cache table for discovered schemas.

This migration creates the discovered_schemas table to cache schema
information per tenant to avoid redundant VLM calls during auto-schema
discovery.

Revision ID: 0004
Revises: 0003
Create Date: 2025-01-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Migration 0003 created an earlier "discovered_schemas" shape; this migration
    # is the canonical version. Drop the superseded table (and its dependent
    # indexes) before recreating. Safe: the cache had no ORM model / persisted data.
    op.execute("DROP TABLE IF EXISTS discovered_schemas CASCADE")
    op.create_table(
        "discovered_schemas",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("institution", sa.String(256), nullable=False),
        sa.Column("document_type_label", sa.String(256), nullable=False),
        sa.Column("schema_fingerprint", sa.String(512), nullable=False),
        sa.Column("field_definitions", JSONB, nullable=False),
        sa.Column("table_definitions", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "schema_fingerprint",
            name="uq_tenant_schema_fingerprint",
        ),
    )

    # Index on tenant_id for fast lookups
    op.create_index(
        "idx_discovered_schemas_tenant_id",
        "discovered_schemas",
        ["tenant_id"],
    )

    # Index on schema_fingerprint for fast lookups
    op.create_index(
        "idx_discovered_schemas_fingerprint",
        "discovered_schemas",
        ["schema_fingerprint"],
    )

    # Composite index for common query pattern (tenant + fingerprint)
    op.create_index(
        "idx_discovered_schemas_tenant_fingerprint",
        "discovered_schemas",
        ["tenant_id", "schema_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_discovered_schemas_tenant_fingerprint",
        table_name="discovered_schemas",
    )
    op.drop_index(
        "idx_discovered_schemas_fingerprint",
        table_name="discovered_schemas",
    )
    op.drop_index(
        "idx_discovered_schemas_tenant_id",
        table_name="discovered_schemas",
    )
    op.drop_table("discovered_schemas")