"""SWIFT trade confirmation schema extractor.

Extracts fields specific to SWIFT MT5xx trade confirmations:
- trade_date
- settlement_date
- isin
- quantity
- price
- counterparty_bic
"""

from __future__ import annotations

from api.models.response import Abstention, Field
from pipeline.models import AssembledDocument
from pipeline.schemas.base import (
    BaseSchemaExtractor,
    parse_amount,
    parse_date,
)


# ─── Pattern Definitions ─────────────────────────────────────────────────────

# Trade date patterns (SWIFT field :98a:)
TRADE_DATE_PATTERNS: list[str] = [
    # SWIFT tag format :98A::TRAD//YYYYMMDD
    r":98[A-C]::TRAD//(\d{8})",
    r"(?:Trade\s*Date|Deal\s*Date|Transaction\s*Date)[:\s]*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})",
    r"(?:Trade\s*Date|Deal\s*Date|Transaction\s*Date)[:\s]*(\d{4}-\d{2}-\d{2})",
    r"(?:Trade\s*Date|Deal\s*Date|Transaction\s*Date)[:\s]*(\d{1,2}\s+\w+\s+\d{4})",
]

# Settlement date patterns (SWIFT field :98a:SETT)
SETTLEMENT_DATE_PATTERNS: list[str] = [
    # SWIFT tag format :98A::SETT//YYYYMMDD
    r":98[A-C]::SETT//(\d{8})",
    r"(?:Settlement\s*Date|Value\s*Date|Settle\s*Date)[:\s]*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})",
    r"(?:Settlement\s*Date|Value\s*Date|Settle\s*Date)[:\s]*(\d{4}-\d{2}-\d{2})",
    r"(?:Settlement\s*Date|Value\s*Date|Settle\s*Date)[:\s]*(\d{1,2}\s+\w+\s+\d{4})",
]

# ISIN patterns (SWIFT field :35B:)
ISIN_PATTERNS: list[str] = [
    # Standard ISIN: 2 letter country + 9 alphanumeric + 1 check digit
    r"(?:ISIN[:\s]*)?([A-Z]{2}[A-Z0-9]{9}\d)",
    r":35B:.*?([A-Z]{2}[A-Z0-9]{9}\d)",
]

# Quantity patterns (SWIFT field :36B:)
QUANTITY_PATTERNS: list[str] = [
    # SWIFT tag format :36B::SETT//UNIT/quantity
    r":36B::(?:SETT|CONF)//UNIT/([\d,]+\.?\d*)",
    r"(?:Quantity|Nominal|Units|Shares)[:\s]*([\d,]+\.?\d*)",
    r"(?:Qty|Amount\s*of\s*Securities)[:\s]*([\d,]+\.?\d*)",
]

# Price patterns (SWIFT field :90a:)
PRICE_PATTERNS: list[str] = [
    # SWIFT tag format :90A::DEAL//PRCT/price or :90B::DEAL//ACTU/CCY/price
    r":90[AB]::DEAL//(?:PRCT|ACTU)/(?:[A-Z]{3})?([\d,]+\.?\d*)",
    r"(?:Price|Unit\s*Price|Deal\s*Price)[:\s]*([€$£¥]?\s*[\d,]+\.?\d*)",
    r"(?:Price\s*per\s*(?:Unit|Share))[:\s]*([€$£¥]?\s*[\d,]+\.?\d*)",
]

# Counterparty BIC patterns (SWIFT field :95a:)
COUNTERPARTY_BIC_PATTERNS: list[str] = [
    # SWIFT tag format :95P::SELL//BIC or :95P::BUYR//BIC
    r":95[A-Z]::(?:SELL|BUYR|DEAG|REAG)//([A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)",
    r"(?:Counterparty|Broker|Dealer)\s*(?:BIC|SWIFT)[:\s]*([A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)",
    r"(?:BIC|SWIFT\s*Code)[:\s]*([A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)",
]


def _parse_swift_date(raw: str) -> str:
    """Parse SWIFT date format YYYYMMDD to ISO 8601."""
    cleaned = raw.strip()
    if len(cleaned) == 8 and cleaned.isdigit():
        return f"{cleaned[:4]}-{cleaned[4:6]}-{cleaned[6:8]}"
    return parse_date(cleaned)


class SwiftConfirmExtractor(BaseSchemaExtractor):
    """Extractor for SWIFT/broker trade confirmation documents.

    Extracts:
    - trade_date
    - settlement_date
    - isin
    - quantity
    - price
    - counterparty_bic
    """

    def extract(self, doc: AssembledDocument) -> dict:
        """Extract all SWIFT confirmation fields.

        Returns dict with 'fields', 'tables', 'abstentions' keys.
        """
        fields: dict[str, Field] = {}
        abstentions: list[Abstention] = []

        # ─── Field Extraction ─────────────────────────────────────────────

        field_specs: list[tuple[str, list[str], object, bool]] = [
            ("trade_date", TRADE_DATE_PATTERNS, _parse_swift_date, True),
            ("settlement_date", SETTLEMENT_DATE_PATTERNS, _parse_swift_date, True),
            ("isin", ISIN_PATTERNS, None, True),
            ("quantity", QUANTITY_PATTERNS, parse_amount, True),
            ("price", PRICE_PATTERNS, parse_amount, True),
            ("counterparty_bic", COUNTERPARTY_BIC_PATTERNS, None, True),
        ]

        for label, patterns, normaliser, required in field_specs:
            result = self.find_field(doc, patterns, label, normaliser, required)
            if isinstance(result, Abstention):
                abstentions.append(result)
            else:
                fields[label] = result

        return {
            "fields": fields,
            "tables": [],
            "abstentions": abstentions,
        }
