"""Schema templates table — deterministic, reusable extraction templates.

Persists SchemaTemplate (theme + institution + label/value anchors + table
header signatures) per tenant so previously-seen layouts extract without VLM.
Tenant-scoped; tenant_id "*" denotes a global (hand-authored) template shared
to all tenants.

Revision ID: 0005
Revises: 0004
Create Date: 2025-01-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "schema_templates",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Text to match tenants.id; "*" = global template.
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("fingerprint_key", sa.String(512), nullable=False),
        sa.Column("theme", sa.String(64), nullable=False),
        sa.Column("institution", sa.String(256), nullable=False),
        sa.Column("document_type_label", sa.String(256), nullable=False),
        # Full SchemaTemplate (anchors included) serialised as JSON.
        sa.Column("template_json", JSONB, nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="vlm_discovered"),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("tenant_id", "fingerprint_key", name="uq_template_tenant_fingerprint"),
    )
    op.create_index("idx_schema_templates_tenant_theme", "schema_templates", ["tenant_id", "theme"])


def downgrade() -> None:
    op.drop_index("idx_schema_templates_tenant_theme", table_name="schema_templates")
    op.drop_table("schema_templates")
