"""Bank statement schema extractor.

Extracts fields and tables specific to bank statements:
- account_number (IBAN + domestic patterns)
- statement_date
- closing_balance
- opening_balance
- transactions table
"""

from __future__ import annotations

from api.models.response import Abstention, Field, Table
from pipeline.models import AssembledDocument
from pipeline.schemas.base import (
    BaseSchemaExtractor,
    normalise_iban,
    parse_amount,
    parse_date,
)


# ─── Pattern Definitions ─────────────────────────────────────────────────────

# Account number patterns: IBAN first, then domestic formats
ACCOUNT_NUMBER_PATTERNS: list[str] = [
    # IBAN: 2 letter country code + 2 check digits + up to 30 alphanumeric
    r"(?:IBAN[:\s]*)?([A-Z]{2}\d{2}[\s]?[\dA-Z]{4}[\s]?[\dA-Z]{4}[\s]?[\dA-Z]{4}[\s]?[\dA-Z]{4}[\s]?[\dA-Z]{0,14})",
    # Account number with label
    r"(?:Account\s*(?:No|Number|#)[:\s]*)([\d\s\-]{8,20})",
    # Sort code + account number (UK)
    r"(\d{2}-\d{2}-\d{2}\s+\d{8})",
    # Generic numeric account (8-20 digits)
    r"(?:A/C|Acct)[:\s]*([\d\-]{8,20})",
]

# Statement date patterns
STATEMENT_DATE_PATTERNS: list[str] = [
    r"(?:Statement\s*Date|Date\s*of\s*Statement|As\s*(?:at|of))[:\s]*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})",
    r"(?:Statement\s*Date|Date\s*of\s*Statement|As\s*(?:at|of))[:\s]*(\d{1,2}\s+\w+\s+\d{4})",
    r"(?:Statement\s*Date|Date\s*of\s*Statement|As\s*(?:at|of))[:\s]*(\d{4}-\d{2}-\d{2})",
    r"(?:Period\s*(?:End|To))[:\s]*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})",
]

# Closing balance patterns
CLOSING_BALANCE_PATTERNS: list[str] = [
    r"(?:Closing\s*Balance|Balance\s*(?:Carried\s*Forward|C/F|at\s*End))[:\s]*([€$£¥]?\s*[\d,]+\.?\d*)",
    r"(?:Closing\s*Balance|Balance\s*(?:Carried\s*Forward|C/F|at\s*End))[:\s]*\(?([\d,]+\.?\d*)\)?",
    r"(?:End\s*Balance|Final\s*Balance)[:\s]*([€$£¥]?\s*[\d,]+\.?\d*)",
]

# Opening balance patterns
OPENING_BALANCE_PATTERNS: list[str] = [
    r"(?:Opening\s*Balance|Balance\s*(?:Brought\s*Forward|B/F|at\s*Start))[:\s]*([€$£¥]?\s*[\d,]+\.?\d*)",
    r"(?:Opening\s*Balance|Balance\s*(?:Brought\s*Forward|B/F|at\s*Start))[:\s]*\(?([\d,]+\.?\d*)\)?",
    r"(?:Start\s*Balance|Initial\s*Balance|Previous\s*Balance)[:\s]*([€$£¥]?\s*[\d,]+\.?\d*)",
]

# Expected transaction table headers
TRANSACTION_TABLE_HEADERS: list[str] = ["Date", "Description", "Debit", "Credit", "Balance"]


class BankStatementExtractor(BaseSchemaExtractor):
    """Extractor for bank statement documents.

    Extracts:
    - account_number (IBAN preferred, domestic fallback)
    - statement_date
    - closing_balance
    - opening_balance
    - transactions table
    """

    def extract(self, doc: AssembledDocument) -> dict:
        """Extract all bank statement fields and tables.

        Returns dict with 'fields', 'tables', 'abstentions' keys.
        """
        fields: dict[str, Field] = {}
        abstentions: list[Abstention] = []
        tables: list[Table] = []

        # ─── Field Extraction ─────────────────────────────────────────────

        field_specs: list[tuple[str, list[str], object, bool]] = [
            ("account_number", ACCOUNT_NUMBER_PATTERNS, normalise_iban, True),
            ("statement_date", STATEMENT_DATE_PATTERNS, parse_date, True),
            ("closing_balance", CLOSING_BALANCE_PATTERNS, parse_amount, True),
            ("opening_balance", OPENING_BALANCE_PATTERNS, parse_amount, False),
        ]

        for label, patterns, normaliser, required in field_specs:
            result = self.find_field(doc, patterns, label, normaliser, required)
            if isinstance(result, Abstention):
                abstentions.append(result)
            else:
                fields[label] = result

        # ─── Table Extraction ─────────────────────────────────────────────

        tx_table = self.extract_table_by_header(
            doc,
            expected_headers=TRANSACTION_TABLE_HEADERS,
            table_type="transactions",
        )

        if isinstance(tx_table, Abstention):
            abstentions.append(tx_table)
        else:
            tables.append(tx_table)

        return {
            "fields": fields,
            "tables": tables,
            "abstentions": abstentions,
        }
