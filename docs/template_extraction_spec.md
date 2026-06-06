# Deterministic Template Extraction — Design Spec

**Goal:** high accuracy, low latency, low VLM cost.
**Principle:** confidence-gated cascade — cheapest extractor first, VLM only on doubt.
**Core change:** discovered schemas become *deterministic templates* (re-usable without VLM), not VLM-replay definitions.
**Organisation:** two tiers — broad **themes** (business function) on top, specific **schemas/templates** (per institution/layout) slotted underneath.

---

## 0. Two-tier taxonomy

```
THEME            (coarse — keyword detected, no VLM)
  └─ SCHEMA / TEMPLATE   (fine — fingerprint: theme::institution::layout)
```

Theme = the document family (Payments, Custody, …). Each theme carries its own
**expected fields** and **validation rules**. Schemas/templates are slotted under
exactly one theme. A newly-discovered layout is filed under the theme that
matched, so the library grows per theme.

Starting theme set (extend as new families arrive):

| Theme id | Holds | Example schemas under it |
|---|---|---|
| `cash_bank` | account activity, balances | bank statement, nostro/vostro, cash balance |
| `custody` | holdings, positions | custody statement, holdings/position report |
| `payments` | money-movement instructions | GIRO, MT103, payment/remittance advice |
| `settlements` | trade lifecycle | trade/broker confirmation, contract note, settlement instruction |
| `corporate_actions` | entitlements | dividend/coupon notice, proxy, rights advice |
| `fees_tax` | charges, tax | fee statement, invoice, tax voucher, withholding |

Built-in schemas map onto themes: `bank_statement→cash_bank`,
`custody_statement→custody`, `swift_confirm→settlements`.

Fingerprint becomes `theme :: institution :: document_type_label`.

---

## 1. Target flow

```
classify pages (coverage)                    ← no VLM, no OCR for digital
detect THEME + built-in schema (keyword)     ← no VLM
  ├─ known built-in schema   → regex extractor          (bank/custody/swift)
  ├─ template hit (in theme) → TEMPLATE extractor       ← NEW, no VLM
  └─ no match (miss)         → VLM discovery + extract → SAVE template under theme
        │
        ▼  (every path)
  validation gate — generic + THEME-specific rules
        │
        ▼  if confidence < threshold OR required field missing
  VLM fallback — only the failed fields            ← exception path
```

Maps to the requested 4 steps:

| Requested | Mechanism |
|---|---|
| 1. Identify schema, no VLM | `classify_page` + `detect_theme`/`detect_schema` (keyword) |
| 2. Schema exists → regex | built-in regex extractors **and** saved templates |
| 3. Check regex, bad → VLM | validation gate (generic + theme rules) → per-field VLM fallback |
| 4. New schema → save, regex if possible else VLM | VLM discovery captures **anchors** → template filed under theme; reuse deterministic |

---

## 2. Why today's design can't do step 4 deterministically

`DiscoveredSchema` (`pipeline/models.py:178`) stores per field only:
- `description` (prose)
- `location_hint` (`"header"`/`"footer"`/`"first_page"`)

No regex, no label anchor, no column index, no bbox. So on a cache hit, `DynamicExtractor` (`pipeline/discovery/dynamic_extractor.py`) **must** re-ask the VLM to read the doc. The cache only saves the *discovery* pass, never the *extraction* calls.

The cache is also **in-memory** (`schema_cache.py:35`) and **approval-gated** — so even the partial saving evaporates on restart.

---

## 3. New data model — `SchemaTemplate`

Captured during the first (VLM) extraction, enriched with concrete anchors so a deterministic extractor can replay it.

```python
@dataclass
class TemplateFieldAnchor:
    field_name: str                 # snake_case
    label_pattern: str              # regex anchoring the label, e.g. r"Account[:\s]+"
    value_pattern: str              # regex capturing the value (group 1)
    normaliser: str                 # name: "amount" | "date" | "iban" | "text" | "currency"
    page_scope: str                 # "first" | "last" | "any"
    required: bool

@dataclass
class TemplateTableAnchor:
    table_type: str
    header_signature: list[str]     # exact headers seen (drives header match)
    min_columns: int
    column_normalisers: dict[int, str]   # col index -> normaliser
    amount_column: int | None       # for running-balance/sum checks

@dataclass
class SchemaTemplate:
    fingerprint_key: str            # reuse SchemaFingerprint.key  inst::doc_type
    document_type_label: str
    institution: str
    field_anchors: list[TemplateFieldAnchor]
    table_anchors: list[TemplateTableAnchor]
    source: str                     # "vlm_discovered" | "hand_authored"
    confidence_seen: float          # extraction confidence on the doc it was derived from
    version: int
```

How anchors are produced from a VLM discovery+extraction:
- For each field the VLM returned, take its `original_string` and the preceding label text on the same line → synthesise `label_pattern` + `value_pattern` (start permissive, e.g. value = run of non-space / currency / date token).
- For tables, the header row is already known deterministically from pdfplumber — store it verbatim as `header_signature`.

This is the honest answer to "use regex if possible": we don't auto-generate clever regex from one sample and trust it blindly — we generate a *candidate* template and let the **validation gate** (section 5) decide each time whether it held.

---

## 4. `TemplateExtractor`

A `BaseSchemaExtractor` subclass driven by a `SchemaTemplate` instead of hardcoded constants. Reuses the existing `find_field` (regex over text segments) and `extract_table_by_header` machinery verbatim — so it inherits provenance, bbox, abstention behaviour for free.

```python
class TemplateExtractor(BaseSchemaExtractor):
    def __init__(self, template: SchemaTemplate): self.t = template
    def extract(self, doc):
        fields, tables, abstentions = {}, [], []
        for a in self.t.field_anchors:
            patterns = [a.label_pattern + r"(" + a.value_pattern + r")"]
            r = self.find_field(doc, patterns, a.field_name,
                                NORMALISERS[a.normaliser], a.required)
            (abstentions if isinstance(r, Abstention) else fields).__setitem__(...)
        for ta in self.t.table_anchors:
            tbl = self.extract_table_by_header(doc, ta.header_signature, ta.table_type)
            ...
        return {"fields": fields, "tables": tables, "abstentions": abstentions}
```

`NORMALISERS` = registry mapping the string names to the existing `parse_amount` / `parse_date` / `normalise_iban` / identity functions in `base.py`.

Cost on a template hit: **0 VLM calls, 0 OCR** (for digital docs). Latency = regex over text segments (ms).

---

## 5. Validation gate (the leverage point)

This is what makes deterministic reuse safe. Run after *any* extractor, before deciding on VLM:

- **Required-field presence** — any required anchor abstained → fail.
- **Type sanity** — amounts parse to float, dates to ISO, currency in ISO-4217.
- **Table integrity** — every data row has `>= min_columns`; amount column parses.
- **Arithmetic** (where applicable) — running balance, sum(amounts) vs stated total. GIRO: sum of `Amount` column is a checkable total.
- **Completeness** — row count > 0; no all-empty trailing column.

Output: per-field + per-table confidence. Below threshold → escalate **only those fields** to VLM. A template that drifts (new layout) fails the gate and self-heals via the VLM exception path — wrong data never ships silently. This directly protects the accuracy goal that naive auto-regex would endanger.

---

## 6. Persistence

- Move `SchemaCache` from in-memory dict to the existing PostgreSQL table (migration already defined in `db/`). Store `SchemaTemplate` as JSON column keyed by `(tenant_id, fingerprint_key)`.
- Templates survive restart → step 4 actually pays off across sessions.
- Keep the pending→approved gate for `vlm_discovered` templates (governance); allow `hand_authored` templates to be pre-approved (e.g. a checked-in GIRO template).

---

## 7. Integration points

| File | Change |
|---|---|
| `pipeline/models.py` | add `TemplateFieldAnchor`, `TemplateTableAnchor`, `SchemaTemplate` |
| `pipeline/schemas/template_extractor.py` | **new** — `TemplateExtractor` |
| `pipeline/schemas/router.py` | on `unknown`, before VLM: look up template by fingerprint → `TemplateExtractor`; on VLM discovery success, synthesise + store template |
| `pipeline/discovery/schema_cache.py` | store/return `SchemaTemplate`; back with Postgres |
| `pipeline/validator.py` | strengthen gate (section 5); return per-field confidence |
| `pipeline/classifier.py` | fix `DIGITAL_THRESHOLD` (0.80 → ~0.01) so digital docs skip OCR — orthogonal latency fix |

---

## 8. Honest trade-offs

- **Auto-synthesised anchors are candidates, not truth.** First-doc anchors can overfit. Mitigation: the validation gate re-checks every time; failures fall to VLM and can re-derive the template (`version++`).
- **Fingerprint accuracy matters.** Wrong fingerprint → wrong template → gate should catch it, but a near-miss could waste a regex pass. Keep fingerprint = institution + doc-type label.
- **Hand-authored beats auto for known-recurring types.** For a doc you see daily (GIRO), a checked-in template is the most accurate + cheapest option — the prototype demonstrates this.
- **VLM never disappears.** It becomes the discovery + exception path, not the steady-state cost.

---

## 9. Prototype scope (next)

Hand-author a GIRO `SchemaTemplate`, run `TemplateExtractor` on `giro_transactions.pdf`, show:
- institution=DBS, client=AVIVA LTD-NON PAR 2, currency=SGD extracted deterministically
- transactions table (10 cols) extracted via header signature
- **0 VLM calls, 0 OCR**, sum-of-amounts validation passing
