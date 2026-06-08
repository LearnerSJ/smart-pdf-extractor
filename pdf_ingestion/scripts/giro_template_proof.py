"""Prototype proof: deterministic GIRO extraction with zero VLM / zero OCR.

Builds an AssembledDocument from giro_transactions.pdf using pdfplumber only
(the digital path), then runs TemplateExtractor with a hand-authored GIRO
SchemaTemplate. Proves the spec's step-4 deterministic reuse.

Run:  .venv/bin/python scripts/giro_template_proof.py ../giro_transactions.pdf
"""

from __future__ import annotations

import sys

import pdfplumber

from pipeline.models import AssembledDocument, Token
from pipeline.schemas.template_extractor import (
    SchemaTemplate,
    TemplateExtractor,
    stitch_table_rows,
)
from pipeline.schemas.template_store import DBS_GIRO_TEMPLATE

# Reuse the checked-in DBS GIRO template from the store (single source of truth).
GIRO_TEMPLATE: SchemaTemplate = DBS_GIRO_TEMPLATE


def build_assembled_document(pdf_path: str) -> AssembledDocument:
    """Digital-path assembly: pdfplumber words -> blocks, tables -> tables."""
    blocks: list[dict] = []
    tables: list[dict] = []
    tokens: list[Token] = []
    table_counter = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            for w in page.extract_words():
                bbox = (float(w["x0"]), float(w["top"]),
                        float(w["x1"]), float(w["bottom"]))
                blocks.append({
                    "text": w["text"],
                    "bbox": list(bbox),
                    "provenance": {"page": page_num},
                })
                # Word-level token stream so VLM verification can ground values.
                tokens.append(Token(text=w["text"], bbox=bbox, confidence=1.0))
            for t in page.extract_tables():
                if not t:
                    continue
                headers = [(c or "").strip() for c in t[0]]
                rows = [[(c or "").strip() for c in r] for r in t[1:]]
                tables.append({
                    "table_id": f"t{table_counter}",
                    "headers": headers,
                    "rows": rows,
                    "page_number": page_num,
                    "page_range": [page_num],
                    "bbox": [0.0, 0.0, float(page.width), float(page.height)],
                })
                table_counter += 1

    return AssembledDocument(blocks=blocks, tables=tables, token_stream=tokens)


def validate(doc, fields: dict, tables: list, template: SchemaTemplate) -> list[str]:
    """Section-5 gate: required presence, currency type, table integrity, sum."""
    issues: list[str] = []

    for a in template.field_anchors:
        if a.required and a.field_name not in fields:
            issues.append(f"missing required field: {a.field_name}")

    cur = fields.get("currency")
    if cur and (not isinstance(cur.value, str) or len(cur.value) != 3):
        issues.append(f"currency not ISO-3: {cur.value!r}")

    total_rows = 0
    total_amount = 0.0
    for ta in template.table_anchors:
        rows = stitch_table_rows(doc, ta)  # all pages, not just first
        if not rows:
            issues.append(f"missing table: {ta.table_type}")
            continue
        for idx, cells in enumerate(rows):
            total_rows += 1
            if len(cells) < ta.min_columns:
                issues.append(f"row {idx} has {len(cells)} cols (< {ta.min_columns})")
            if ta.amount_column is not None and len(cells) > ta.amount_column:
                raw = cells[ta.amount_column]
                try:
                    total_amount += float(str(raw).replace(",", ""))
                except ValueError:
                    issues.append(f"row {idx} amount unparseable: {raw!r}")
    if total_rows == 0:
        issues.append("zero transaction rows")

    validate.total_rows = total_rows   # type: ignore[attr-defined]
    validate.total_amount = total_amount  # type: ignore[attr-defined]
    return issues


def main() -> int:
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "../giro_transactions.pdf"
    doc = build_assembled_document(pdf_path)
    print(f"assembled: {len(doc.blocks)} blocks, {len(doc.tables)} tables")

    out = TemplateExtractor(GIRO_TEMPLATE).extract(doc)
    fields, tables, abstentions = out["fields"], out["tables"], out["abstentions"]

    print("\n── FIELDS (deterministic) ──")
    for name, f in fields.items():
        print(f"  {name:14s} = {f.value!r}   vlm_used={f.vlm_used}  p{f.provenance.page}")

    print("\n── TABLES ──")
    for t in tables:
        print(f"  {t.type}: {len(t.rows)} rows, {len(t.headers)} cols")

    issues = validate(doc, fields, tables, GIRO_TEMPLATE)
    print("\n── VALIDATION GATE ──")
    print(f"  rows={validate.total_rows}  sum(amount)={validate.total_amount:.2f}")
    if abstentions:
        print(f"  abstentions: {[a.field or a.table_id for a in abstentions]}")
    print("  PASS" if not issues else f"  FAIL: {issues}")

    vlm_used = any(f.vlm_used for f in fields.values())
    print("\n── COST ──")
    print(f"  VLM calls: 0   OCR pages: 0   any vlm_used flag: {vlm_used}")
    ok = not issues and not vlm_used and not abstentions
    print(f"\nRESULT: {'PROOF PASSED — zero-VLM deterministic extraction' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
