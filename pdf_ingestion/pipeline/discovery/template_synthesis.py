"""Self-verifying template synthesis from a VLM discovery result.

After the VLM discovers + extracts an unseen layout once, build a deterministic
SchemaTemplate from the ACTUAL document (real label text next to each extracted
value — evidence, not a guess from the field name), then VERIFY it: re-run the
candidate template on the same document and keep only the anchors that reproduce
the VLM's own values. Garbage anchors fail this check and are dropped.

Result: the system learns templates with no human input, and only saves ones that
provably work — so the next identical layout extracts deterministically (zero VLM)
and correctly. Drift on future docs is caught by the validation gate, which
re-triggers learning.
"""

from __future__ import annotations

import re

from pipeline.models import AssembledDocument, DiscoveredSchema
from pipeline.schemas.base import BaseSchemaExtractor
from pipeline.schemas.template_extractor import (
    SchemaTemplate,
    TemplateExtractor,
    TemplateFieldAnchor,
    TemplateTableAnchor,
    stitch_table_rows,
)


class _Segmenter(BaseSchemaExtractor):
    """Concrete shim to reuse BaseSchemaExtractor._build_text_segments."""

    def extract(self, doc):  # pragma: no cover - not used
        return {"fields": {}, "tables": [], "abstentions": []}


def _norm(v) -> str:
    return str(v).strip().casefold()


def _infer_value_patterns(sample: str) -> list[tuple[str, str]]:
    """Candidate (value_regex, normaliser) pairs to try, most specific first."""
    s = (sample or "").strip()
    out: list[tuple[str, str]] = []
    if re.fullmatch(r"[A-Z]{2}\d{2}[\dA-Z ]{6,}", s):
        out.append((r"[A-Z]{2}\d{2}[\dA-Z ]{6,}", "iban"))
    if re.fullmatch(r"[\(\-]?[\d.,]+\)?", s) and any(c.isdigit() for c in s):
        out.append((r"\(?[\d.,]+\)?", "amount"))
    if re.search(r"\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}", s) or re.search(
        r"\d{1,2}\s+[A-Za-z]{3,}\s+\d{4}", s
    ):
        out.append((r"[\d]{1,4}[/\-.\s][\w]{1,9}[/\-.\s][\d]{2,4}", "date"))
    if re.fullmatch(r"[A-Z]{3}", s):
        out.append((r"[A-Z]{3}", "currency"))
    # Generic fallbacks: up to a delimiter, then rest-of-line.
    out.append((r"[^|\n]+?(?=\s*\||\s*$)", "text"))
    out.append((r".+", "text"))
    return out


def _label_for_value(segments: list[dict], value: str) -> str | None:
    """Find the text immediately preceding `value` on its line in the document."""
    v = value.strip()
    if not v:
        return None
    for seg in segments:
        text = str(seg.get("text", ""))
        idx = text.find(v)
        if idx > 0:
            before = text[:idx].strip()
            words = before.split()
            # Keep the last few words as the label anchor (most specific part).
            return " ".join(words[-4:]) if words else ""
        if idx == 0:
            return ""  # value at line start — anchor at start of line
    return None


def _label_pattern(label: str) -> str:
    if not label:
        return r"^\s*"
    # Escape, allow flexible whitespace, tolerate a trailing separator.
    esc = r"\s*".join(re.escape(w) for w in label.split())
    return esc + r"\s*[:\-]?\s*"


def synthesise_template(
    theme: str,
    discovered: DiscoveredSchema,
    extraction_result: dict,
    doc: AssembledDocument,
) -> SchemaTemplate | None:
    """Build and self-verify a template. Returns None if nothing reproduces."""
    vlm_fields = extraction_result.get("fields", {}) or {}
    vlm_tables = extraction_result.get("tables", []) or []
    segments = _Segmenter()._build_text_segments(doc)

    verified_anchors: list[TemplateFieldAnchor] = []
    for fdef in discovered.metadata_fields:
        name = fdef.field_name
        extracted = vlm_fields.get(name)
        target = getattr(extracted, "original_string", "") if extracted else ""
        if not target:
            continue
        label = _label_for_value(segments, target)
        if label is None:
            continue  # value not located in text — can't anchor deterministically
        label_pat = _label_pattern(label)

        # Try candidate value patterns; keep the first that REPRODUCES the value.
        for value_pat, normaliser in _infer_value_patterns(target):
            candidate = TemplateFieldAnchor(
                field_name=name,
                label_pattern=label_pat,
                value_pattern=value_pat,
                normaliser=normaliser,
                required=True,
            )
            probe = SchemaTemplate(
                theme=theme,
                document_type_label=discovered.document_type_label,
                institution=discovered.institution,
                field_anchors=[candidate],
            )
            result = TemplateExtractor(probe).extract(doc)
            got = result["fields"].get(name)
            if got is not None and _norm(got.original_string) == _norm(target):
                verified_anchors.append(candidate)
                break  # this field is solved

    # Tables: header signature is reliable; verify it actually stitches rows.
    verified_tables: list[TemplateTableAnchor] = []
    for tbl in vlm_tables:
        headers = [str(h) for h in (getattr(tbl, "headers", []) or [])]
        if not headers:
            continue
        amount_col = next(
            (i for i, h in enumerate(headers)
             if "amount" in h.lower() or "value" in h.lower()),
            None,
        )
        anchor = TemplateTableAnchor(
            table_type=str(getattr(tbl, "type", "table")),
            header_signature=headers,
            min_columns=max(1, len(headers)),
            amount_column=amount_col,
        )
        if stitch_table_rows(doc, anchor):  # reproduces ≥1 row on this doc
            verified_tables.append(anchor)

    if not verified_anchors and not verified_tables:
        return None  # learned nothing trustworthy — keep using VLM

    return SchemaTemplate(
        theme=theme,
        document_type_label=discovered.document_type_label,
        institution=discovered.institution,
        field_anchors=verified_anchors,
        table_anchors=verified_tables,
        source="vlm_discovered",
    )
