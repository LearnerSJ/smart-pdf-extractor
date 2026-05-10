"""Custody statement schema extractor.

Extracts fields and tables specific to custody/portfolio statements:
- portfolio_id
- valuation_date
- total_value
- positions table (ISIN, Name, Quantity, Price, Value)
"""

from __future__ import annotations

from api.models.response import Abstention, Field, Table
from pipeline.models import AssembledDocument
from pipeline.schemas.base import (
    BaseSchemaExtractor,
    parse_amount,
    parse_date,
)


# ─── Pattern Definitions ─────────────────────────────────────────────────────

# Portfolio ID patterns
PORTFOLIO_ID_PATTERNS: list[str] = [
    r"(?:Portfolio\s*(?:ID|No|Number|Ref|Reference))[:\s]*([A-Z0-9\-]{4,20})",
    r"(?:Account\s*(?:ID|No|Number|Ref))[:\s]*([A-Z0-9\-]{4,20})",
    r"(?:Depot\s*(?:No|Number|ID))[:\s]*([A-Z0-9\-]{4,20})",
    r"(?:Client\s*(?:Ref|Reference|ID))[:\s]*([A-Z0-9\-]{4,20})",
]

# Valuation date patterns
VALUATION_DATE_PATTERNS: list[str] = [
    r"(?:Valuation\s*Date|Date\s*of\s*Valuation|As\s*(?:at|of)\s*Date)[:\s]*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})",
    r"(?:Valuation\s*Date|Date\s*of\s*Valuation|As\s*(?:at|of)\s*Date)[:\s]*(\d{1,2}\s+\w+\s+\d{4})",
    r"(?:Valuation\s*Date|Date\s*of\s*Valuation|As\s*(?:at|of)\s*Date)[:\s]*(\d{4}-\d{2}-\d{2})",
    r"(?:Position\s*Date|Report\s*Date)[:\s]*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})",
    r"(?:Position\s*Date|Report\s*Date)[:\s]*(\d{4}-\d{2}-\d{2})",
]

# Total value patterns
TOTAL_VALUE_PATTERNS: list[str] = [
    r"(?:Total\s*(?:Portfolio\s*)?Value|Total\s*Market\s*Value|Net\s*Asset\s*Value)[:\s]*([€$£¥]?\s*[\d,]+\.?\d*)",
    r"(?:Total\s*(?:Portfolio\s*)?Value|Total\s*Market\s*Value|Net\s*Asset\s*Value)[:\s]*([A-Z]{3}\s*[\d,]+\.?\d*)",
    r"(?:Grand\s*Total|Portfolio\s*Total)[:\s]*([€$£¥]?\s*[\d,]+\.?\d*)",
]

# Expected positions table headers
POSITIONS_TABLE_HEADERS: list[str] = ["ISIN", "Name", "Quantity", "Price", "Value"]


class CustodyStatementExtractor(BaseSchemaExtractor):
    """Extractor for custody/portfolio statement documents.

    Extracts:
    - portfolio_id
    - valuation_date
    - total_value
    - positions table (ISIN, Name, Quantity, Price, Value)
    """

    def extract(self, doc: AssembledDocument) -> dict:
        """Extract all custody statement fields and tables.

        Returns dict with 'fields', 'tables', 'abstentions' keys.
        """
        fields: dict[str, Field] = {}
        abstentions: list[Abstention] = []
        tables: list[Table] = []

        # ─── Field Extraction ─────────────────────────────────────────────

        field_specs: list[tuple[str, list[str], object, bool]] = [
            ("portfolio_id", PORTFOLIO_ID_PATTERNS, None, True),
            ("valuation_date", VALUATION_DATE_PATTERNS, parse_date, True),
            ("total_value", TOTAL_VALUE_PATTERNS, parse_amount, True),
        ]

        for label, patterns, normaliser, required in field_specs:
            result = self.find_field(doc, patterns, label, normaliser, required)
            if isinstance(result, Abstention):
                abstentions.append(result)
            else:
                fields[label] = result

        # ─── Table Extraction ─────────────────────────────────────────────

        positions_table = self.extract_table_by_header(
            doc,
            expected_headers=POSITIONS_TABLE_HEADERS,
            table_type="positions",
        )

        if isinstance(positions_table, Abstention):
            abstentions.append(positions_table)
        else:
            tables.append(positions_table)

        return {
            "fields": fields,
            "tables": tables,
            "abstentions": abstentions,
        }
