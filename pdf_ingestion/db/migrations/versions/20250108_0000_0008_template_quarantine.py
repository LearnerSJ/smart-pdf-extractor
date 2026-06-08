"""Template quarantine — close the feedback -> re-learn loop.

When a user corrects a field that a template extracted, that template's layout has
drifted (or was never right). We record a per-tenant quarantine on its fingerprint
so the tenant's next same-layout document SKIPS the template, falls to VLM
discovery, and re-synthesises a fresh, self-verified template. Re-learning clears
the quarantine.

Per-tenant on purpose: one tenant's correction must not disable a GLOBAL ('*')
seed template for every other tenant — the quarantine shadows the fingerprint for
that tenant only, and the re-learn produces a tenant-specific replacement.

Revision ID: 0008
Revises: 0007
Create Date: 2025-01-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "template_quarantine",
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("fingerprint_key", sa.String(512), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("tenant_id", "fingerprint_key", name="pk_template_quarantine"),
    )

    op.execute("ALTER TABLE template_quarantine ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE template_quarantine FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON template_quarantine "
        "USING (tenant_id = current_setting('app.current_tenant', true)) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant', true))"
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pdf_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON template_quarantine TO pdf_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON template_quarantine")
    op.drop_table("template_quarantine")
