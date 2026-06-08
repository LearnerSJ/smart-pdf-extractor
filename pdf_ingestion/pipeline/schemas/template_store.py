"""Template store — persistence for learned + hand-authored SchemaTemplates.

Keyed by (tenant_id, fingerprint_key). In-memory implementation now; the same
interface backs a PostgreSQL table in production (spec §6). Pre-loaded with
hand-authored templates (e.g. DBS GIRO under the payments theme) that are
immediately usable — no discovery or approval needed.

Templates are slotted under a theme via SchemaTemplate.theme; lookups are by
fingerprint so a theme can hold many institution layouts.
"""

from __future__ import annotations

import structlog

from pipeline.schemas.template_extractor import (
    SchemaTemplate,
    TemplateFieldAnchor,
    TemplateTableAnchor,
)

logger = structlog.get_logger()


# ─── Hand-authored seed templates ─────────────────────────────────────────────

DBS_GIRO_TEMPLATE = SchemaTemplate(
    theme="payments",
    document_type_label="giro_payment",
    institution="DBS",
    field_anchors=[
        TemplateFieldAnchor("institution", r"GIRO Payment\s*\(", r"[^)]+", "text"),
        TemplateFieldAnchor("client_name", r"Account:\s*", r"[^|]+?(?=\s*\|)", "text"),
        TemplateFieldAnchor("currency", r"Currency:\s*", r"[A-Z]{3}", "currency"),
    ],
    table_anchors=[
        TemplateTableAnchor(
            table_type="giro_transactions",
            header_signature=[
                "Item No.", "Bank Code", "Branch", "Account", "Account Name",
                "Amount", "Particulars", "Reference", "Status", "Reason",
            ],
            min_columns=10,
            amount_column=5,
        )
    ],
    source="hand_authored",
)

SEED_TEMPLATES: list[SchemaTemplate] = [DBS_GIRO_TEMPLATE]


class TemplateStore:
    """In-memory template store with a Postgres-ready interface.

    Methods are async so the Postgres-backed implementation can drop in without
    changing callers.
    """

    def __init__(self, seed: bool = True) -> None:
        # {(tenant_id, fingerprint_key): SchemaTemplate}
        self._store: dict[tuple[str, str], SchemaTemplate] = {}
        # {(tenant_id, fingerprint_key)} this tenant has quarantined (drift signal).
        self._quarantined: set[tuple[str, str]] = set()
        if seed:
            for tpl in SEED_TEMPLATES:
                self._store[("*", tpl.fingerprint_key)] = tpl

    async def get(self, tenant_id: str, fingerprint_key: str) -> SchemaTemplate | None:
        """Return a template by fingerprint. Tenant-specific first, then global ('*')."""
        tpl = self._store.get((tenant_id, fingerprint_key)) or self._store.get(("*", fingerprint_key))
        if tpl:
            logger.info("template_store.hit", fingerprint=fingerprint_key, source=tpl.source)
        return tpl

    async def find_in_theme(self, tenant_id: str, theme: str) -> list[SchemaTemplate]:
        """All templates under a theme (tenant + global), minus quarantined ones."""
        out: list[SchemaTemplate] = []
        for (tid, key), tpl in self._store.items():
            if tpl.theme == theme and tid in (tenant_id, "*") and (tenant_id, key) not in self._quarantined:
                out.append(tpl)
        return out

    async def quarantine(self, tenant_id: str, fingerprint_key: str, reason: str) -> None:
        """Shadow a fingerprint for this tenant so its next same-layout doc re-learns."""
        self._quarantined.add((tenant_id, fingerprint_key))
        logger.info("template.quarantined", fingerprint=fingerprint_key,
                    tenant_id=tenant_id, reason=reason)

    async def save(self, tenant_id: str, template: SchemaTemplate) -> None:
        """Store/overwrite a template for a tenant. A fresh save lifts any quarantine."""
        existing = self._store.get((tenant_id, template.fingerprint_key))
        if existing:
            template.version = existing.version + 1
        self._store[(tenant_id, template.fingerprint_key)] = template
        self._quarantined.discard((tenant_id, template.fingerprint_key))
        logger.info(
            "template_store.saved",
            fingerprint=template.fingerprint_key,
            theme=template.theme,
            source=template.source,
            version=template.version,
        )


# Process-wide default store (in-memory). Production injects a Postgres-backed one.
_DEFAULT_STORE: TemplateStore | None = None


def get_default_store() -> TemplateStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = TemplateStore(seed=True)
    return _DEFAULT_STORE
