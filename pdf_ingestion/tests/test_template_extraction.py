"""Tests for the two-tier theme + deterministic template extraction subsystem."""

from __future__ import annotations

import pytest

from pipeline.models import AssembledDocument
from pipeline.schemas.router import route_and_extract_async
from pipeline.schemas.template_extractor import (
    SchemaTemplate,
    TemplateExtractor,
    TemplateFieldAnchor,
    TemplateTableAnchor,
    make_fingerprint_key,
)
from pipeline.schemas.template_store import TemplateStore
from pipeline.schemas.themes import (
    THEMES,
    detect_theme,
    theme_expected_field_gaps,
    theme_for_schema,
)


GIRO_HEADERS = ["Item No.", "Bank Code", "Branch", "Account", "Account Name",
                "Amount", "Particulars", "Reference", "Status", "Reason"]


def _giro_doc(n_rows: int = 40) -> AssembledDocument:
    """GIRO-like assembled document, realistic word count.

    Rows are emitted as text blocks (as the real assembler does) so keyword
    density matches reality: detect_schema -> unknown, detect_theme -> payments.
    """
    blocks = [
        {"text": "GIRO Payment (DBS)", "bbox": [0, 0, 200, 10], "provenance": {"page": 1}},
        {"text": "Account: AVIVA LTD-NON PAR 2 | Currency: SGD",
         "bbox": [0, 12, 300, 22], "provenance": {"page": 1}},
    ]
    rows = []
    for i in range(1, n_rows + 1):
        cells = [str(i), "7171", "100", f"3834477{i}", f"Customer {i}",
                 f"{100 + i}.18", "AVIVA", f"130000{i}", "COMPLETED", ""]
        rows.append(cells)
        blocks.append({
            "text": " ".join(c for c in cells if c),
            "bbox": [0, 30 + i * 10, 400, 40 + i * 10],
            "provenance": {"page": 1},
        })
    tables = [{
        "table_id": "t0",
        "headers": GIRO_HEADERS,
        "rows": rows,
        "page_number": 1,
        "page_range": [1],
        "bbox": [0, 0, 595, 842],
    }]
    return AssembledDocument(blocks=blocks, tables=tables)


# ─── Themes ───────────────────────────────────────────────────────────────────


def test_detect_theme_payments():
    assert detect_theme(_giro_doc()) == "payments"


def test_theme_for_builtin_schema():
    assert theme_for_schema("bank_statement") == "cash_bank"
    assert theme_for_schema("swift_confirm") == "settlements"
    assert theme_for_schema("nonexistent") is None


def test_theme_expected_field_gaps():
    gaps = theme_expected_field_gaps("payments", ["institution"])
    assert "client_name" in gaps and "currency" in gaps
    assert "institution" not in gaps
    assert theme_expected_field_gaps("unknown_theme", []) == []


def test_all_themes_have_keywords_and_label():
    for t in THEMES.values():
        assert t.label and t.keywords


# ─── Template model + extractor ────────────────────────────────────────────────


def test_fingerprint_key_format():
    assert make_fingerprint_key("payments", "DBS Bank", "GIRO Payment") == "payments::dbs_bank::giro_payment"


def test_template_extractor_deterministic():
    tpl = SchemaTemplate(
        theme="payments",
        document_type_label="giro_payment",
        institution="DBS",
        field_anchors=[
            TemplateFieldAnchor("institution", r"GIRO Payment\s*\(", r"[^)]+", "text"),
            TemplateFieldAnchor("currency", r"Currency:\s*", r"[A-Z]{3}", "currency"),
        ],
        table_anchors=[TemplateTableAnchor(
            "giro_transactions", GIRO_HEADERS, min_columns=10, amount_column=5,
        )],
    )
    result = TemplateExtractor(tpl).extract(_giro_doc())
    assert result["fields"]["institution"].value == "DBS"
    assert result["fields"]["currency"].value == "SGD"
    assert not any(f.vlm_used for f in result["fields"].values())
    assert len(result["tables"]) == 1


# ─── Store ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_seeded_giro_lookup():
    store = TemplateStore(seed=True)
    tpls = await store.find_in_theme("any-tenant", "payments")
    assert any(t.institution == "DBS" for t in tpls)


@pytest.mark.asyncio
async def test_store_save_versions():
    store = TemplateStore(seed=False)
    tpl = SchemaTemplate(theme="payments", document_type_label="x", institution="ACME")
    await store.save("t1", tpl)
    again = SchemaTemplate(theme="payments", document_type_label="x", institution="ACME")
    await store.save("t1", again)
    got = await store.get("t1", tpl.fingerprint_key)
    assert got.version == 2


# ─── Router integration: template tier hit, zero VLM ───────────────────────────


@pytest.mark.asyncio
async def test_router_hits_template_tier_no_vlm():
    schema_type, result = await route_and_extract_async(_giro_doc())
    assert schema_type == "template:payments::dbs::giro_payment"
    assert result["fields"]["institution"].value == "DBS"
    assert not any(f.vlm_used for f in result["fields"].values())
    assert not result["abstentions"]
