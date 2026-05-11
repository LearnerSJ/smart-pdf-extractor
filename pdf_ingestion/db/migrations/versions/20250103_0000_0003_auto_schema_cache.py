"""Auto-schema discovery cache table.

Revision ID: 0003
Revises: 0002
Create Date: 2025-01-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "discovered_schemas",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("fingerprint_key", sa.String(512), nullable=False),
        sa.Column("institution", sa.String(256), nullable=False),
        sa.Column("document_type_label", sa.String(256), nullable=False),
        sa.Column("schema_json", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("usage_count", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.UniqueConstraint("tenant_id", "fingerprint_key", name="uq_tenant_fingerprint"),
    )

    op.create_index(
        "idx_discovered_schemas_tenant",
        "discovered_schemas",
        ["tenant_id"],
    )
    op.create_index(
        "idx_discovered_schemas_fingerprint",
        "discovered_schemas",
        ["tenant_id", "fingerprint_key"],
    )


def downgrade() -> None:
    op.drop_index("idx_discovered_schemas_fingerprint", table_name="discovered_schemas")
    op.drop_index("idx_discovered_schemas_tenant", table_name="discovered_schemas")
    op.drop_table("discovered_schemas")
