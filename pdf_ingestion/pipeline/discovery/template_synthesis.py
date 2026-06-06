"""Synthesise a deterministic SchemaTemplate from a VLM discovery result.

This is the "step 4" learning step: after the VLM discovers a schema and
extracts a document once, capture concrete extraction anchors so the next
document of the same layout extracts deterministically — no VLM.

Honesty: synthesised field anchors are *candidates* derived from one document.
They can overfit. The validation gate re-checks every reuse and escalates to VLM
on failure (spec §3, §5), so a wrong anchor self-heals rather than shipping bad
data. Table header signatures, by contrast, come straight from pdfplumber and
are reliable.
"""

from __future__ import annotations

import re

from pipeline.models import DiscoveredSchema
from pipeline.schemas.template_extractor import (
    SchemaTemplate,
    TemplateFieldAnchor,
    TemplateTableAnchor,
)


def _label_pattern_from_field_name(field_name: str) -> str:
    """Heuristic label regex from a snake_case field name.

    account_number -> r"Account\s*(?:Number|No|#)?[:\s]+"
    statement_date -> r"Statement\s*Date[:\s]+"
    """
    words = [w for w in field_name.split("_") if w]
    parts = [re.escape(w) for w in words]
    base = r"\s*".join(p.capitalize() for p in parts)
    return base + r"[:\s]+"


def _infer_value_pattern_and_normaliser(sample: str) -> tuple[str, str]:
    """Infer a value regex + normaliser from an extracted sample value."""
    s = (sample or "").strip()
    if re.fullmatch(r"[A-Z]{2}\d{2}[\dA-Z ]{6,}", s):
        return r"[A-Z]{2}\d{2}[\dA-Z ]{6,}", "iban"
    if re.fullmatch(r"[\(\-]?[\d.,]+\)?", s) and any(c.isdigit() for c in s):
        return r"\(?[\d.,]+\)?", "amount"
    if re.search(r"\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}", s) or re.search(
        r"\d{1,2}\s+[A-Za-z]{3,}\s+\d{4}", s
    ):
        return r"[\d]{1,4}[/\-.\s][\w]{1,9}[/\-.\s][\d]{2,4}", "date"
    if re.fullmatch(r"[A-Z]{3}", s):
        return r"[A-Z]{3}", "currency"
    # default: rest of the line
    return r"[^\n|]+", "text"


def synthesise_template(
    theme: str,
    discovered: DiscoveredSchema,
    extraction_result: dict,
) -> SchemaTemplate:
    """Build a SchemaTemplate from a discovery + its extraction result.

    Args:
        theme: theme id the document matched (for filing the template).
        discovered: the VLM-discovered schema definition.
        extraction_result: dict with 'fields' {name: Field} and 'tables' [Table].
    """
    fields = extraction_result.get("fields", {}) or {}
    tables = extraction_result.get("tables", []) or []

    field_anchors: list[TemplateFieldAnchor] = []
    for fdef in discovered.metadata_fields:
        name = fdef.field_name
        extracted = fields.get(name)
        sample = getattr(extracted, "original_string", "") if extracted else ""
        value_pattern, normaliser = _infer_value_pattern_and_normaliser(sample)
        field_anchors.append(
            TemplateFieldAnchor(
                field_name=name,
                label_pattern=_label_pattern_from_field_name(name),
                value_pattern=value_pattern,
                normaliser=normaliser,
                required=bool(extracted),  # only require what we actually found
            )
        )

    table_anchors: list[TemplateTableAnchor] = []
    for tbl in tables:
        headers = list(getattr(tbl, "headers", []) or [])
        if not headers:
            continue
        amount_col = next(
            (i for i, h in enumerate(headers) if "amount" in str(h).lower()
             or "value" in str(h).lower()),
            None,
        )
        table_anchors.append(
            TemplateTableAnchor(
                table_type=str(getattr(tbl, "type", "table")),
                header_signature=[str(h) for h in headers],
                min_columns=max(1, len(headers)),
                amount_column=amount_col,
            )
        )

    return SchemaTemplate(
        theme=theme,
        document_type_label=discovered.document_type_label,
        institution=discovered.institution,
        field_anchors=field_anchors,
        table_anchors=table_anchors,
        source="vlm_discovered",
    )
