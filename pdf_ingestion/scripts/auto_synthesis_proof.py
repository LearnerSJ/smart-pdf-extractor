"""Prove the VLM auto-synthesis round-trip with a REAL Bedrock VLM.

Simulates a never-before-seen layout by running with an EMPTY template store
(seed=False). The document has a detected theme (payments) but no template, so:

  Pass 1: no template -> VLM discovery + extract -> synthesise template -> save
  Pass 2: template hit -> deterministic extraction, ZERO VLM

Run (needs valid AWS creds):
  AWS_PROFILE=smartstream .venv/bin/python scripts/auto_synthesis_proof.py ../giro_transactions.pdf
"""

from __future__ import annotations

import asyncio
import sys

from api.config import get_settings
from api.models.tenant import TenantContext
from pipeline.discovery.schema_cache import SchemaCache
from pipeline.schemas.router import route_and_extract_async
from pipeline.schemas.template_store import TemplateStore
from pipeline.schemas.themes import detect_theme
from pipeline.vlm.bedrock_client import BedrockVLMClient
from pipeline.vlm.token_budget import TokenBudget
from scripts.giro_template_proof import build_assembled_document
from tests.mocks import MockRedactor


def _count_vlm(result: dict) -> bool:
    return any(getattr(f, "vlm_used", False) for f in result.get("fields", {}).values())


async def main() -> int:
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "../giro_transactions.pdf"
    settings = get_settings()
    doc = build_assembled_document(pdf_path)

    tenant = TenantContext(
        id="demo-tenant", name="demo", api_key_hash="x", vlm_enabled=True
    )
    vlm = BedrockVLMClient(
        region=settings.aws_region,
        model_id=settings.bedrock_model_id,
        vlm_enabled=True,
    )
    redactor = MockRedactor()
    store = TemplateStore(seed=False)  # EMPTY — nothing learned yet

    theme = detect_theme(doc)
    print(f"theme detected: {theme}")
    print(f"templates in store before: {len(await store.find_in_theme('demo-tenant', theme or ''))}")

    common = dict(
        tenant=tenant, vlm_client=vlm, redactor=redactor,
        schema_cache=SchemaCache(), template_store=store,
    )

    # ── Pass 1: unknown layout → VLM discovery → synthesise + save ──
    print("\n── PASS 1 (expect VLM discovery + template synthesis) ──")
    st1, r1 = await route_and_extract_async(
        doc, token_budget=TokenBudget(max_tokens=settings.vlm_max_tokens_per_job,
                                      budget_exceeded_action="flag"), **common)
    print(f"  schema_type: {st1}")
    print(f"  fields: {list(r1.get('fields', {}).keys())}")
    print(f"  VLM used: {_count_vlm(r1)}")

    learned = await store.find_in_theme("demo-tenant", theme or "")
    print(f"  templates in store after: {len(learned)}")
    if learned:
        t = learned[0]
        print(f"  LEARNED template: {t.fingerprint_key}  source={t.source}")
        print(f"    field anchors: {[(a.field_name, a.normaliser) for a in t.field_anchors]}")
        print(f"    table anchors: {[(ta.table_type, len(ta.header_signature)) for ta in t.table_anchors]}")

    # ── Pass 2: same layout → template hit, zero VLM ──
    print("\n── PASS 2 (expect template hit, ZERO VLM) ──")
    st2, r2 = await route_and_extract_async(
        doc, token_budget=TokenBudget(max_tokens=settings.vlm_max_tokens_per_job,
                                      budget_exceeded_action="flag"), **common)
    print(f"  schema_type: {st2}")
    print(f"  fields: {{k: v.value for ...}} -> {{ {', '.join(f'{k}={v.value!r}' for k, v in r2.get('fields', {}).items())} }}")
    print(f"  VLM used: {_count_vlm(r2)}")

    ok = st2.startswith("template:") and not _count_vlm(r2) and len(learned) > 0
    print(f"\nRESULT: {'AUTO-SYNTHESIS PROVEN — learned once via VLM, reused with zero VLM' if ok else 'INCOMPLETE'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
