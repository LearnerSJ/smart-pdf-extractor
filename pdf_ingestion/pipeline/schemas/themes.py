"""Theme taxonomy — the coarse top tier of the two-tier schema model.

A *theme* is a document family (Payments, Custody, ...). Specific
schemas/templates are slotted under exactly one theme. Each theme carries:
  - detection keywords (keyword-density, no VLM)
  - expected field names (drives "what is missing")
  - validation rule ids that apply to its documents

Built-in schemas map onto themes; newly-discovered layouts are filed under the
theme that matched. See docs/template_extraction_spec.md §0.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeline.models import AssembledDocument


@dataclass(frozen=True)
class ThemeDefinition:
    theme_id: str
    label: str
    keywords: list[str] = field(default_factory=list)
    expected_fields: list[str] = field(default_factory=list)
    # ids of validators (from pipeline.validator) considered relevant to the theme
    validation_rules: list[str] = field(default_factory=list)
    # built-in regex schemas that belong to this theme
    builtin_schemas: list[str] = field(default_factory=list)


# ─── Starting theme set ───────────────────────────────────────────────────────

THEMES: dict[str, ThemeDefinition] = {
    "cash_bank": ThemeDefinition(
        theme_id="cash_bank",
        label="Cash & Bank Statements",
        keywords=[
            "statement", "account", "balance", "debit", "credit",
            "opening balance", "closing balance", "brought forward",
            "carried forward", "sort code", "iban", "nostro", "vostro",
        ],
        expected_fields=["account_number", "statement_date", "opening_balance", "closing_balance"],
        validation_rules=[
            "validate_running_balance",
            "validate_account_balance_reconciliation",
            "validate_iban",
        ],
        builtin_schemas=["bank_statement"],
    ),
    "custody": ThemeDefinition(
        theme_id="custody",
        label="Custody & Safekeeping",
        keywords=[
            "portfolio", "custody", "valuation", "holdings", "positions",
            "isin", "securities", "market value", "net asset", "depot",
            "quantity", "nominal", "safekeeping",
        ],
        expected_fields=["account_number", "statement_date", "market_value"],
        validation_rules=["validate_isin", "validate_column_type_consistency"],
        builtin_schemas=["custody_statement"],
    ),
    "payments": ThemeDefinition(
        theme_id="payments",
        label="Payments & Transfers",
        keywords=[
            "giro", "payment", "remittance", "transfer", "beneficiary",
            "bank code", "branch", "particulars", "mt103", "direct debit",
            "payment advice", "credit transfer",
        ],
        expected_fields=["institution", "client_name", "currency"],
        validation_rules=["validate_totals_crosscheck", "validate_arithmetic_totals"],
        builtin_schemas=[],
    ),
    "settlements": ThemeDefinition(
        theme_id="settlements",
        label="Settlements & Confirmations",
        keywords=[
            "swift", "mt5", "trade confirmation", "settlement", "counterparty",
            "bic", "contract note", "settlement instruction", "trade date",
            "settlement date", ":20:", ":35b:",
        ],
        expected_fields=["counterparty", "trade_date", "settlement_date"],
        validation_rules=["validate_bic", "validate_date_range"],
        builtin_schemas=["swift_confirm"],
    ),
    "corporate_actions": ThemeDefinition(
        theme_id="corporate_actions",
        label="Corporate Actions",
        keywords=[
            "dividend", "coupon", "corporate action", "entitlement", "proxy",
            "ex-date", "record date", "pay date", "rights", "redemption",
        ],
        expected_fields=["isin", "ex_date", "pay_date"],
        validation_rules=["validate_isin", "validate_date_range"],
        builtin_schemas=[],
    ),
    "fees_tax": ThemeDefinition(
        theme_id="fees_tax",
        label="Fees, Billing & Tax",
        keywords=[
            "invoice", "management fee", "fee statement", "tax voucher",
            "withholding", "vat", "billing", "charges", "net amount due",
        ],
        expected_fields=["invoice_number", "amount_due", "currency"],
        validation_rules=["validate_arithmetic_totals", "validate_currency_codes"],
        builtin_schemas=[],
    ),
}

# built-in schema → theme reverse map
SCHEMA_TO_THEME: dict[str, str] = {
    schema: t.theme_id for t in THEMES.values() for schema in t.builtin_schemas
}

MIN_THEME_DENSITY = 0.02  # fraction of words that must be theme keywords

# Theme signal lives in the document's identifying header/structure, which sits on
# the first pages. Sampling avoids keyword-density dilution on very large documents
# (a 467-page payments file otherwise scores ~0 and detects no theme).
THEME_SAMPLE_BLOCKS = 600


def detect_theme(doc: AssembledDocument) -> str | None:
    """Detect the document theme by keyword density. No VLM.

    Density is computed over a sample of the leading blocks (THEME_SAMPLE_BLOCKS)
    so large documents are not diluted to zero. Returns the theme_id with the
    highest density above MIN_THEME_DENSITY, or None if nothing matches.
    """
    parts: list[str] = [str(b.get("text", "")) for b in doc.blocks if b.get("text")]
    if not parts and doc.token_stream:
        parts = [t.text for t in doc.token_stream]
    parts = parts[:THEME_SAMPLE_BLOCKS]
    text = " ".join(parts).lower()
    word_count = max(len(text.split()), 1)
    if not text:
        return None

    best_id: str | None = None
    best_score = 0.0
    for theme in THEMES.values():
        matches = sum(min(text.count(k), 3) for k in theme.keywords if k in text)
        score = matches / (len(theme.keywords) * max(word_count / 100, 1))
        if score > best_score:
            best_score = score
            best_id = theme.theme_id

    return best_id if best_score >= MIN_THEME_DENSITY else None


def theme_for_schema(schema_type: str) -> str | None:
    """Map a built-in schema type to its theme id."""
    return SCHEMA_TO_THEME.get(schema_type)


def theme_expected_field_gaps(theme_id: str, present_field_names: list[str]) -> list[str]:
    """Theme-level validation rule: which of a theme's expected fields are missing.

    Used by the validation gate — missing required fields for the theme are a
    signal to escalate those fields to VLM (spec §5). Returns [] for an unknown
    theme (no expectations to enforce).
    """
    theme = THEMES.get(theme_id)
    if theme is None:
        return []
    present = set(present_field_names)
    return [f for f in theme.expected_fields if f not in present]


def relevant_validators(theme_id: str) -> list[str]:
    """Validator ids (from pipeline.validator) relevant to a theme."""
    theme = THEMES.get(theme_id)
    return list(theme.validation_rules) if theme else []
