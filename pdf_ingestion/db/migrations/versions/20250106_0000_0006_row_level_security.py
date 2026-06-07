"""Row-Level Security — hard tenant isolation at the database.

Enables (and FORCEs) RLS on tenant-scoped tables with a policy that restricts
every row to the tenant bound on the connection via the app.current_tenant GUC
(set per transaction by the app's repos). Template/discovery tables also expose
global ('*') rows shared to all tenants.

Enforcement applies to non-superuser roles (e.g. pdf_app). Superusers bypass RLS,
so connecting as 'postgres' is unaffected — switch the runtime DATABASE_URL to
pdf_app to activate enforcement.

Revision ID: 0006
Revises: 0005
Create Date: 2025-01-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables whose rows belong strictly to one tenant.
TENANT_TABLES = ["jobs", "results", "feedback", "batches", "vlm_usage", "delivery_logs"]
# Tables that additionally hold global ('*') rows shared to every tenant.
TENANT_OR_GLOBAL_TABLES = ["discovered_schemas", "schema_templates"]

_TENANT_PRED = "tenant_id = current_setting('app.current_tenant', true)"
_GLOBAL_PRED = (
    "tenant_id = current_setting('app.current_tenant', true) OR tenant_id = '*'"
)


def _enable(table: str, using_pred: str, check_pred: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({using_pred}) WITH CHECK ({check_pred})"
    )


def upgrade() -> None:
    # Strict tenant tables: read and write only own rows.
    for t in TENANT_TABLES:
        _enable(t, _TENANT_PRED, _TENANT_PRED)
    # Template/discovery: read own + global ('*'), but write only own rows.
    for t in TENANT_OR_GLOBAL_TABLES:
        _enable(t, _GLOBAL_PRED, _TENANT_PRED)


def downgrade() -> None:
    for t in TENANT_TABLES + TENANT_OR_GLOBAL_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
