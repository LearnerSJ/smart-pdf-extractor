"""Prove the learn-lock collapses a thundering herd with a REAL Bedrock VLM.

Fires N identical never-seen documents CONCURRENTLY at an empty template store.
Without the lock, all N would run VLM discovery. With it, exactly ONE discovers
and learns; the rest double-check the store on lock acquire and reuse the
freshly-learned template (zero VLM).

Run:  AWS_PROFILE=smartstream PYTHONPATH=. .venv/bin/python scripts/learn_lock_herd_proof.py ../giro_transactions.pdf
"""

from __future__ import annotations

import asyncio
import sys

from api.config import get_settings
from api.models.tenant import TenantContext
from pipeline.discovery.schema_cache import SchemaCache
from pipeline.schemas.router import route_and_extract_async
from pipeline.schemas.template_store import TemplateStore
from pipeline.vlm.bedrock_client import BedrockVLMClient
from pipeline.vlm.token_budget import TokenBudget
from scripts.giro_template_proof import build_assembled_document
from tests.mocks import MockRedactor

N = 3


class CountingVLM(BedrockVLMClient):
    """Wraps the real client and counts schema-discovery (VLM) invocations."""

    discoveries = 0

    def extract_field(self, *args, **kwargs):  # type: ignore[override]
        if kwargs.get("field_name") == "schema_analysis":
            CountingVLM.discoveries += 1
        return super().extract_field(*args, **kwargs)


async def main() -> int:
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "../giro_transactions.pdf"
    settings = get_settings()
    doc = build_assembled_document(pdf_path)
    tenant = TenantContext(id="herd-tenant", name="herd", api_key_hash="x", vlm_enabled=True)
    vlm = CountingVLM(region=settings.aws_region, model_id=settings.bedrock_model_id, vlm_enabled=True)
    redactor = MockRedactor()
    store = TemplateStore(seed=False)  # EMPTY — first doc must learn

    async def run_one(i: int):
        st, r = await route_and_extract_async(
            doc,
            tenant=tenant,
            vlm_client=vlm,
            redactor=redactor,
            schema_cache=SchemaCache(),
            token_budget=TokenBudget(
                max_tokens=settings.vlm_max_tokens_per_job, budget_exceeded_action="flag"
            ),
            template_store=store,
        )
        return i, st

    print(f"firing {N} identical docs concurrently at an empty store...\n")
    results = await asyncio.gather(*(run_one(i) for i in range(N)))

    discovered = [st for _, st in results if st.startswith("discovered:")]
    templated = [st for _, st in results if st.startswith("template:")]
    for i, st in results:
        print(f"  doc {i}: {st}")
    print(f"\nVLM discoveries: {CountingVLM.discoveries}  (want 1)")
    print(f"discovered: {len(discovered)}  template-reused: {len(templated)}")

    ok = CountingVLM.discoveries == 1 and len(templated) == N - 1
    print(f"\nRESULT: {'HERD COLLAPSED — 1 VLM discovery, rest reused zero-VLM' if ok else 'INCOMPLETE'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
