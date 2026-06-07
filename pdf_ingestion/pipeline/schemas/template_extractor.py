"""Template-driven deterministic extractor.

Replays a saved SchemaTemplate (label/value anchors + table header signatures)
using the existing BaseSchemaExtractor regex + header-match machinery. Zero VLM,
zero OCR — the deterministic reuse path for previously-seen schemas.

See docs/template_extraction_spec.md. The dataclasses live here for the
prototype; the spec moves them to pipeline/models.py.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from api.models.response import Abstention, Field, Table
from pipeline.models import AssembledDocument
from pipeline.schemas.base import (
    BaseSchemaExtractor,
    normalise_iban,
    parse_amount,
    parse_date,
)


def _header_signature_match(expected: list[str], actual: list[str]) -> float:
    """Fraction of expected headers found in actual (substring-insensitive)."""
    if not expected:
        return 0.0
    exp = [h.lower().strip() for h in expected]
    act = [str(h).lower().strip() for h in actual]
    hits = sum(1 for e in exp if any(e == a or e in a or a in e for a in act))
    return hits / len(exp)


def stitch_table_rows(doc: AssembledDocument, anchor: "TemplateTableAnchor") -> list[list[str]]:
    """Concatenate rows from every table matching the header signature.

    The base extract_table_by_header returns a single best-match table; multi-page
    documents need stitching (spec §7: belongs in the assembler). Done here so the
    template path captures all pages deterministically.
    """
    rows: list[list[str]] = []
    for t in doc.tables:
        headers = t.get("headers", [])
        if headers and _header_signature_match(anchor.header_signature, headers) >= 0.6:
            rows.extend(t.get("rows", []))
    return rows


# ─── Normaliser registry ──────────────────────────────────────────────────────

NORMALISERS = {
    "amount": parse_amount,
    "date": parse_date,
    "iban": normalise_iban,
    "currency": lambda s: s.strip().upper(),
    "text": lambda s: s.strip(),
}


# ─── Template data model ──────────────────────────────────────────────────────


@dataclass
class TemplateFieldAnchor:
    field_name: str
    label_pattern: str  # regex anchoring the label, e.g. r"Account:\s*"
    value_pattern: str  # regex capturing the value (wrapped in group 1 at runtime)
    normaliser: str = "text"
    required: bool = True


@dataclass
class TemplateTableAnchor:
    table_type: str
    header_signature: list[str]
    min_columns: int = 1
    amount_column: int | None = None


def make_fingerprint_key(theme: str, institution: str, document_type_label: str) -> str:
    """Composite key for the template store: theme::institution::layout."""
    inst = institution.lower().strip().replace(" ", "_")
    doc = document_type_label.lower().strip().replace(" ", "_")
    return f"{theme}::{inst}::{doc}"


@dataclass
class SchemaTemplate:
    theme: str
    document_type_label: str
    institution: str
    field_anchors: list[TemplateFieldAnchor] = field(default_factory=list)
    table_anchors: list[TemplateTableAnchor] = field(default_factory=list)
    source: str = "hand_authored"
    version: int = 1
    fingerprint_key: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint_key:
            self.fingerprint_key = make_fingerprint_key(
                self.theme, self.institution, self.document_type_label
            )

    def to_dict(self) -> dict:
        """Serialise to a plain dict (for JSONB persistence)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SchemaTemplate":
        """Rebuild a SchemaTemplate (and its anchors) from a stored dict."""
        return cls(
            theme=data["theme"],
            document_type_label=data["document_type_label"],
            institution=data["institution"],
            field_anchors=[TemplateFieldAnchor(**a) for a in data.get("field_anchors", [])],
            table_anchors=[TemplateTableAnchor(**t) for t in data.get("table_anchors", [])],
            source=data.get("source", "hand_authored"),
            version=data.get("version", 1),
            fingerprint_key=data.get("fingerprint_key", ""),
        )


# ─── Extractor ────────────────────────────────────────────────────────────────


class TemplateExtractor(BaseSchemaExtractor):
    """Deterministic extractor driven by a SchemaTemplate."""

    def __init__(self, template: SchemaTemplate) -> None:
        self.t = template

    def extract(self, doc: AssembledDocument) -> dict:
        fields: dict[str, Field] = {}
        abstentions: list[Abstention] = []
        tables: list[Table] = []

        for a in self.t.field_anchors:
            patterns = [a.label_pattern + r"(" + a.value_pattern + r")"]
            normaliser = NORMALISERS.get(a.normaliser, NORMALISERS["text"])
            result = self.find_field(doc, patterns, a.field_name, normaliser, a.required)
            if isinstance(result, Abstention):
                abstentions.append(result)
            else:
                fields[a.field_name] = result

        for ta in self.t.table_anchors:
            tbl = self.extract_table_by_header(doc, ta.header_signature, ta.table_type)
            if isinstance(tbl, Abstention):
                abstentions.append(tbl)
            else:
                tables.append(tbl)

        return {"fields": fields, "tables": tables, "abstentions": abstentions}
