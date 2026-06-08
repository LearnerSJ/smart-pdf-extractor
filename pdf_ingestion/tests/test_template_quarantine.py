"""Tests for the feedback -> quarantine -> re-learn loop (in-memory store)."""

from __future__ import annotations

import pytest

from pipeline.schemas.template_extractor import SchemaTemplate, TemplateFieldAnchor
from pipeline.schemas.template_store import TemplateStore


def _tpl() -> SchemaTemplate:
    return SchemaTemplate(
        theme="payments",
        document_type_label="acme_invoice",
        institution="ACME",
        field_anchors=[TemplateFieldAnchor("currency", r"Currency:\s*", r"[A-Z]{3}", "currency")],
        source="vlm_discovered",
    )


@pytest.mark.asyncio
async def test_quarantine_hides_template_then_relearn_restores() -> None:
    store = TemplateStore(seed=False)
    tpl = _tpl()
    await store.save("tenant-a", tpl)

    # Visible before quarantine.
    assert [t.fingerprint_key for t in await store.find_in_theme("tenant-a", "payments")] == [tpl.fingerprint_key]

    # Correction quarantines it -> tenant's lookup skips it -> forces re-learn.
    await store.quarantine("tenant-a", tpl.fingerprint_key, reason="correction:currency")
    assert await store.find_in_theme("tenant-a", "payments") == []

    # Re-learning (save) lifts the quarantine -> trusted again.
    await store.save("tenant-a", _tpl())
    assert [t.fingerprint_key for t in await store.find_in_theme("tenant-a", "payments")] == [tpl.fingerprint_key]


@pytest.mark.asyncio
async def test_quarantine_is_per_tenant() -> None:
    """A global ('*') template quarantined by one tenant stays usable for another."""
    store = TemplateStore(seed=False)
    tpl = _tpl()
    await store.save("*", tpl)  # global template

    await store.quarantine("tenant-a", tpl.fingerprint_key, reason="correction:currency")

    # tenant-a no longer sees it; tenant-b still does.
    assert await store.find_in_theme("tenant-a", "payments") == []
    assert [t.fingerprint_key for t in await store.find_in_theme("tenant-b", "payments")] == [tpl.fingerprint_key]
