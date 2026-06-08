"""Postgres-backed template store.

Persists SchemaTemplate to the schema_templates table (migration 0005), keyed by
(tenant_id, fingerprint_key). Implements the same async interface as the
in-memory TemplateStore so it drops into the router/pipeline unchanged. tenant_id
"*" holds global (hand-authored) templates shared to every tenant.

Survives restarts — the whole point of the persistence work.
"""

from __future__ import annotations

import json

import structlog
from sqlalchemy import text

from db.job_repo import _set_tenant
from db.session import async_session_factory
from pipeline.schemas.template_extractor import SchemaTemplate
from pipeline.schemas.template_store import SEED_TEMPLATES

logger = structlog.get_logger()


class PostgresTemplateStore:
    """Durable template store backed by the schema_templates table."""

    async def get(self, tenant_id: str, fingerprint_key: str) -> SchemaTemplate | None:
        """Return a template by fingerprint — tenant-specific preferred, then global."""
        sql = text(
            """
            SELECT template_json FROM schema_templates
            WHERE fingerprint_key = :fk AND tenant_id IN (:tid, '*')
            ORDER BY (tenant_id = :tid) DESC
            LIMIT 1
            """
        )
        async with async_session_factory() as session:
            await _set_tenant(session, tenant_id)
            row = (await session.execute(sql, {"fk": fingerprint_key, "tid": tenant_id})).first()
        if not row:
            return None
        logger.info("template_store.hit", fingerprint=fingerprint_key, backend="postgres")
        return SchemaTemplate.from_dict(_as_dict(row[0]))

    async def find_in_theme(self, tenant_id: str, theme: str) -> list[SchemaTemplate]:
        """All templates under a theme (tenant-specific + global), minus any this
        tenant has quarantined — so a corrected/drifted layout re-learns."""
        sql = text(
            """
            SELECT template_json FROM schema_templates t
            WHERE t.theme = :theme AND t.tenant_id IN (:tid, '*')
              AND t.fingerprint_key NOT IN (
                  SELECT fingerprint_key FROM template_quarantine WHERE tenant_id = :tid
              )
            """
        )
        async with async_session_factory() as session:
            await _set_tenant(session, tenant_id)
            rows = (await session.execute(sql, {"theme": theme, "tid": tenant_id})).all()
        return [SchemaTemplate.from_dict(_as_dict(r[0])) for r in rows]

    async def quarantine(self, tenant_id: str, fingerprint_key: str, reason: str) -> None:
        """Shadow a fingerprint for this tenant so its next same-layout doc re-learns."""
        async with async_session_factory() as session:
            await _set_tenant(session, tenant_id)
            await session.execute(
                text(
                    """
                    INSERT INTO template_quarantine (tenant_id, fingerprint_key, reason)
                    VALUES (:tid, :fk, :reason)
                    ON CONFLICT (tenant_id, fingerprint_key)
                    DO UPDATE SET reason = EXCLUDED.reason, created_at = NOW()
                    """
                ),
                {"tid": tenant_id, "fk": fingerprint_key, "reason": reason[:1000]},
            )
            await session.commit()
        logger.info("template.quarantined", fingerprint=fingerprint_key,
                    tenant_id=tenant_id, reason=reason[:200], backend="postgres")

    async def save(self, tenant_id: str, template: SchemaTemplate) -> None:
        """Upsert a template for a tenant, bumping version on overwrite."""
        async with async_session_factory() as session:
            await _set_tenant(session, tenant_id)
            existing = (
                await session.execute(
                    text(
                        "SELECT version FROM schema_templates "
                        "WHERE tenant_id = :tid AND fingerprint_key = :fk"
                    ),
                    {"tid": tenant_id, "fk": template.fingerprint_key},
                )
            ).first()
            if existing:
                template.version = existing[0] + 1

            await session.execute(
                text(
                    """
                    INSERT INTO schema_templates
                        (tenant_id, fingerprint_key, theme, institution,
                         document_type_label, template_json, source, version)
                    VALUES
                        (:tid, :fk, :theme, :inst, :label,
                         CAST(:tj AS JSONB), :source, :version)
                    ON CONFLICT (tenant_id, fingerprint_key) DO UPDATE SET
                        theme = EXCLUDED.theme,
                        institution = EXCLUDED.institution,
                        document_type_label = EXCLUDED.document_type_label,
                        template_json = EXCLUDED.template_json,
                        source = EXCLUDED.source,
                        version = EXCLUDED.version,
                        updated_at = NOW()
                    """
                ),
                {
                    "tid": tenant_id,
                    "fk": template.fingerprint_key,
                    "theme": template.theme,
                    "inst": template.institution,
                    "label": template.document_type_label,
                    "tj": json.dumps(template.to_dict()),
                    "source": template.source,
                    "version": template.version,
                },
            )
            # A freshly learned/saved template is trusted again — lift any quarantine.
            await session.execute(
                text(
                    "DELETE FROM template_quarantine "
                    "WHERE tenant_id = :tid AND fingerprint_key = :fk"
                ),
                {"tid": tenant_id, "fk": template.fingerprint_key},
            )
            await session.commit()
        logger.info(
            "template_store.saved",
            fingerprint=template.fingerprint_key,
            theme=template.theme,
            source=template.source,
            version=template.version,
            backend="postgres",
        )

    async def ensure_seeded(self) -> None:
        """Insert hand-authored global templates (tenant '*') if absent. Idempotent."""
        for tpl in SEED_TEMPLATES:
            existing = await self.get("*", tpl.fingerprint_key)
            if existing is None:
                await self.save("*", tpl)


def _as_dict(value) -> dict:
    """JSONB may come back as a dict (asyncpg) or a JSON string — normalise."""
    if isinstance(value, str):
        return json.loads(value)
    return value
