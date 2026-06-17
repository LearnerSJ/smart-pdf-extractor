"""Shared DB request-context helpers.

`set_tenant` binds the current tenant on a session so Postgres Row-Level
Security policies (migration 0006) apply. It lives here — not as a private
helper on one repo — because every tenant-scoped repo and store needs it
(jobs, feedback, queue, template store).
"""

from __future__ import annotations

from sqlalchemy import text


async def set_tenant(session, tenant_id: str) -> None:
    """Bind the tenant for this transaction so RLS policies apply."""
    await session.execute(
        text("SELECT set_config('app.current_tenant', :tid, true)"),
        {"tid": tenant_id},
    )
