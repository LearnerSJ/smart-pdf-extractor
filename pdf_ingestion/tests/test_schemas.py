"""Tests for schema extractors, router, validator, and packager."""

from __future__ import annotations

import pytest

from api.errors import ErrorCode
from api.models.response import Abstention, Field, Provenance, Table
from pipeline.models import AssembledDocument, Token
from pipeline.packager import package_result
from pipeline.schemas.bank_statement import BankStatementExtractor
from pipeline.schemas.base import normalise_iban, parse_amount, parse_date
from pipeline.schemas.custody_statement import CustodyStatementExtractor
from pipeline.schemas.router import detect_schema, get_extractor, route_and_extract
from pipeline.schemas.swift_confirm import SwiftConfirmExtractor
from pipeline.validator import (
    ValidationReport,
    _is_valid_bic,
    _is_valid_iban,
    _is_valid_isin,
    run_validators,
    validate_arithmetic_totals,
    validate_bic,
    validate_currency_codes,
    validate_date_range,
    validate_iban,
    validate_isin,
    validate_provenance_integrity,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_doc_with_text(text_lines: list[str], tables: list[dict] | None = None) -> AssembledDocument:
    """Create an AssembledDocument with text blocks from lines."""
    blocks = []
    tokens = []
    y = 10.0
    for line in text_lines:
        x = 10.0
        block = {
            "text": line,
            "bbox": [x, y, x + len(line) * 6, y + 12],
            "provenance": {
                "page": 1,
                "bbox": [x, y, x + len(line) * 6, y + 12],
                "source": "native",
                "extraction_rule": "test",
            },
        }
        blocks.append(block)

        # Also add tokens for each word
        for word in line.split():
            token = Token(
                text=word,
                bbox=(x, y, x + len(word) * 6, y + 12),
                confidence=1.0,
            )
            tokens.append(token)
            x += len(word) * 6 + 6

        y += 15.0

    return AssembledDocument(
        blocks=blocks,
        tables=tables or [],
        token_stream=tokens,
        provenance={"total_pages": 1, "page_numbers": [1]},
    )


def _make_final_output(**kwargs):
    """Create a FinalOutput for testing validators."""
    from api.models.response import ConfidenceSummary, FinalOutput

    defaults = {
        "doc_id": "sha256:abc123",
        "schema_type": "bank_statement",
        "status": "complete",
        "fields": {},
        "tables": [],
        "abstentions": [],
        "confidence_summary": ConfidenceSummary(
            mean_confidence=0.95,
            min_confidence=0.90,
            fields_extracted=0,
            fields_abstained=0,
            vlm_used_count=0,
        ),
        "pipeline_version": "0.1.0",
    }
    defaults.update(kwargs)
    return FinalOutput(**defaults)


def _make_field(value, page=1, source="native"):
    """Create a Field with valid provenance."""
    return Field(
        value=value,
        original_string=str(value),
        confidence=0.95,
        vlm_used=False,
        redaction_applied=False,
        provenance=Provenance(
            page=page,
            bbox=[10.0, 20.0, 100.0, 32.0],
            source=source,
            extraction_rule="test_pattern",
        ),
    )


# ─── Normalisation Function Tests ────────────────────────────────────────────


class TestParseAmount:
    def test_simple_integer(self):
        assert parse_amount("1234") == 1234.0

    def test_with_commas(self):
        assert parse_amount("1,234,567.89") == 1234567.89

    def test_with_spaces(self):
        assert parse_amount("1 234 567.89") == 1234567.89

    def test_with_currency_symbol(self):
        assert parse_amount("€1,234.56") == 1234.56
        assert parse_amount("$1,234.56") == 1234.56
        assert parse_amount("£1,234.56") == 1234.56

    def test_negative_parentheses(self):
        assert parse_amount("(1,234.56)") == -1234.56

    def test_negative_minus(self):
        assert parse_amount("-1,234.56") == -1234.56

    def test_empty_after_strip(self):
        assert parse_amount("$") == 0.0


class TestParseDate:
    def test_iso_format(self):
        assert parse_date("2024-01-15") == "2024-01-15"

    def test_dmy_slash(self):
        assert parse_date("15/01/2024") == "2024-01-15"

    def test_dmy_dash(self):
        assert parse_date("15-01-2024") == "2024-01-15"

    def test_dmy_dot(self):
        assert parse_date("15.01.2024") == "2024-01-15"

    def test_dd_mon_yyyy(self):
        assert parse_date("15 Jan 2024") == "2024-01-15"

    def test_mon_dd_yyyy(self):
        assert parse_date("Jan 15, 2024") == "2024-01-15"

    def test_unrecognised_returns_as_is(self):
        assert parse_date("not a date") == "not a date"


class TestNormaliseIban:
    def test_strips_spaces(self):
        assert normalise_iban("GB29 NWBK 6016 1331 9268 19") == "GB29NWBK60161331926819"

    def test_uppercase(self):
        assert normalise_iban("gb29nwbk60161331926819") == "GB29NWBK60161331926819"


# ─── Bank Statement Extractor Tests ──────────────────────────────────────────


class TestBankStatementExtractor:
    def test_extracts_iban(self):
        doc = _make_doc_with_text([
            "Bank Statement",
            "IBAN: GB29NWBK60161331926819",
            "Statement Date: 15/01/2024",
            "Opening Balance: £1,000.00",
            "Closing Balance: £1,500.00",
        ])
        extractor = BankStatementExtractor()
        result = extractor.extract(doc)

        assert "account_number" in result["fields"]
        assert result["fields"]["account_number"].value == "GB29NWBK60161331926819"

    def test_extracts_statement_date(self):
        doc = _make_doc_with_text([
            "Statement Date: 15/01/2024",
            "Closing Balance: £1,500.00",
        ])
        extractor = BankStatementExtractor()
        result = extractor.extract(doc)

        assert "statement_date" in result["fields"]
        assert result["fields"]["statement_date"].value == "2024-01-15"

    def test_extracts_closing_balance(self):
        doc = _make_doc_with_text([
            "Closing Balance: 1,500.00",
        ])
        extractor = BankStatementExtractor()
        result = extractor.extract(doc)

        assert "closing_balance" in result["fields"]
        assert result["fields"]["closing_balance"].value == 1500.0

    def test_abstains_when_field_not_found(self):
        doc = _make_doc_with_text(["This is just random text with no fields"])
        extractor = BankStatementExtractor()
        result = extractor.extract(doc)

        # Should have abstentions for required fields
        assert len(result["abstentions"]) > 0
        reasons = [a.reason for a in result["abstentions"]]
        assert ErrorCode.EXTRACTION_PATTERN_NOT_FOUND in reasons

    def test_provenance_on_extracted_fields(self):
        doc = _make_doc_with_text([
            "IBAN: GB29NWBK60161331926819",
            "Statement Date: 2024-01-15",
            "Closing Balance: 1500.00",
        ])
        extractor = BankStatementExtractor()
        result = extractor.extract(doc)

        for field_name, field_obj in result["fields"].items():
            assert field_obj.provenance is not None
            assert field_obj.provenance.page >= 1
            assert len(field_obj.provenance.bbox) == 4
            assert field_obj.provenance.source == "native"

    def test_extracts_transactions_table(self):
        doc = _make_doc_with_text(
            ["Closing Balance: 1500.00"],
            tables=[{
                "table_id": "page1_table0",
                "page_number": 1,
                "headers": ["Date", "Description", "Debit", "Credit", "Balance"],
                "rows": [
                    ["01/01/2024", "Payment", "100.00", "", "900.00"],
                    ["02/01/2024", "Deposit", "", "200.00", "1100.00"],
                ],
                "bbox": [10, 100, 500, 300],
                "source": "pdfplumber",
            }],
        )
        extractor = BankStatementExtractor()
        result = extractor.extract(doc)

        assert len(result["tables"]) == 1
        assert result["tables"][0].type == "transactions"
        assert len(result["tables"][0].rows) == 2


# ─── Custody Statement Extractor Tests ───────────────────────────────────────


class TestCustodyStatementExtractor:
    def test_extracts_portfolio_id(self):
        doc = _make_doc_with_text([
            "Custody Statement",
            "Portfolio ID: PORT-12345",
            "Valuation Date: 31/12/2023",
            "Total Portfolio Value: €500,000.00",
        ])
        extractor = CustodyStatementExtractor()
        result = extractor.extract(doc)

        assert "portfolio_id" in result["fields"]
        assert result["fields"]["portfolio_id"].value == "PORT-12345"

    def test_extracts_valuation_date(self):
        doc = _make_doc_with_text([
            "Valuation Date: 31/12/2023",
            "Total Value: 500000.00",
        ])
        extractor = CustodyStatementExtractor()
        result = extractor.extract(doc)

        assert "valuation_date" in result["fields"]
        assert result["fields"]["valuation_date"].value == "2023-12-31"

    def test_extracts_positions_table(self):
        doc = _make_doc_with_text(
            ["Total Value: 500000.00"],
            tables=[{
                "table_id": "page1_table0",
                "page_number": 1,
                "headers": ["ISIN", "Name", "Quantity", "Price", "Value"],
                "rows": [
                    ["US0378331005", "Apple Inc", "100", "150.00", "15000.00"],
                ],
                "bbox": [10, 100, 500, 300],
                "source": "pdfplumber",
            }],
        )
        extractor = CustodyStatementExtractor()
        result = extractor.extract(doc)

        assert len(result["tables"]) == 1
        assert result["tables"][0].type == "positions"


# ─── SWIFT Confirm Extractor Tests ───────────────────────────────────────────


class TestSwiftConfirmExtractor:
    def test_extracts_trade_date(self):
        doc = _make_doc_with_text([
            "{1:F01BANKUS33AXXX0000000000}",
            "{4:",
            ":98A::TRAD//20240115",
            ":98A::SETT//20240117",
            ":35B:ISIN US0378331005",
            ":36B::SETT//UNIT/1000",
            ":90A::DEAL//PRCT/150.50",
            ":95P::SELL//DEUTDEFFXXX",
        ])
        extractor = SwiftConfirmExtractor()
        result = extractor.extract(doc)

        assert "trade_date" in result["fields"]
        assert result["fields"]["trade_date"].value == "2024-01-15"

    def test_extracts_isin(self):
        doc = _make_doc_with_text([
            "ISIN: US0378331005",
            "Trade Date: 15/01/2024",
            "Settlement Date: 17/01/2024",
            "Quantity: 1000",
            "Price: 150.50",
            "Counterparty BIC: DEUTDEFFXXX",
        ])
        extractor = SwiftConfirmExtractor()
        result = extractor.extract(doc)

        assert "isin" in result["fields"]
        assert result["fields"]["isin"].value == "US0378331005"

    def test_extracts_counterparty_bic(self):
        doc = _make_doc_with_text([
            "Trade Date: 15/01/2024",
            "Settlement Date: 17/01/2024",
            "ISIN: US0378331005",
            "Quantity: 1000",
            "Price: 150.50",
            "Counterparty BIC: DEUTDEFFXXX",
        ])
        extractor = SwiftConfirmExtractor()
        result = extractor.extract(doc)

        assert "counterparty_bic" in result["fields"]
        assert result["fields"]["counterparty_bic"].value == "DEUTDEFFXXX"


# ─── Schema Router Tests ─────────────────────────────────────────────────────


class TestSchemaRouter:
    def test_detects_bank_statement(self):
        doc = _make_doc_with_text([
            "Bank Statement",
            "Account Number: 12345678",
            "Opening Balance: 1000.00",
            "Closing Balance: 1500.00",
            "Transaction Date Description Debit Credit Balance",
        ])
        schema_type = detect_schema(doc)
        assert schema_type == "bank_statement"

    def test_detects_custody_statement(self):
        doc = _make_doc_with_text([
            "Portfolio Valuation Report",
            "Custody Statement",
            "Holdings and Positions",
            "ISIN Securities Market Value",
            "Portfolio Total Net Asset Value",
        ])
        schema_type = detect_schema(doc)
        assert schema_type == "custody_statement"

    def test_detects_swift_confirm(self):
        doc = _make_doc_with_text([
            "{1:F01BANKUS33AXXX}",
            "{4:",
            ":20:TRADE-REF-001",
            ":98A::TRAD//20240115",
            ":35B:ISIN US0378331005",
            ":36B::SETT//UNIT/1000",
        ])
        schema_type = detect_schema(doc)
        assert schema_type == "swift_confirm"

    def test_unknown_schema(self):
        doc = _make_doc_with_text(["Hello world this is random text"])
        schema_type = detect_schema(doc)
        assert schema_type == "unknown"

    def test_get_extractor_returns_correct_type(self):
        assert isinstance(get_extractor("bank_statement"), BankStatementExtractor)
        assert isinstance(get_extractor("custody_statement"), CustodyStatementExtractor)
        assert isinstance(get_extractor("swift_confirm"), SwiftConfirmExtractor)
        assert get_extractor("unknown") is None

    def test_route_and_extract_unknown_produces_abstention(self):
        doc = _make_doc_with_text(["Random text"])
        schema_type, result = route_and_extract(doc)
        assert schema_type == "unknown"
        assert len(result["abstentions"]) == 1
        assert result["abstentions"][0].reason == ErrorCode.EXTRACTION_SCHEMA_UNKNOWN


# ─── Validator Tests ─────────────────────────────────────────────────────────


class TestValidateIban:
    def test_valid_iban_passes(self):
        # GB29 NWBK 6016 1331 9268 19 is a valid IBAN
        output = _make_final_output(
            fields={"account_number": _make_field("GB29NWBK60161331926819")}
        )
        failures = validate_iban(output, 1)
        assert len(failures) == 0

    def test_invalid_iban_fails(self):
        output = _make_final_output(
            fields={"account_number": _make_field("GB00NWBK60161331926819")}
        )
        failures = validate_iban(output, 1)
        assert len(failures) == 1
        assert failures[0].error_code == ErrorCode.VALIDATION_INVALID_IBAN

    def test_non_iban_field_skipped(self):
        output = _make_final_output(
            fields={"closing_balance": _make_field(1500.0)}
        )
        failures = validate_iban(output, 1)
        assert len(failures) == 0


class TestValidateIsin:
    def test_valid_isin_passes(self):
        # US0378331005 is Apple's valid ISIN
        output = _make_final_output(
            fields={"isin": _make_field("US0378331005")}
        )
        failures = validate_isin(output, 1)
        assert len(failures) == 0

    def test_invalid_isin_fails(self):
        output = _make_final_output(
            fields={"isin": _make_field("US0378331009")}
        )
        failures = validate_isin(output, 1)
        assert len(failures) == 1
        assert failures[0].error_code == ErrorCode.VALIDATION_INVALID_ISIN


class TestValidateBic:
    def test_valid_bic_8_chars(self):
        output = _make_final_output(
            fields={"bic": _make_field("DEUTDEFF")}
        )
        failures = validate_bic(output, 1)
        assert len(failures) == 0

    def test_valid_bic_11_chars(self):
        output = _make_final_output(
            fields={"bic": _make_field("DEUTDEFFXXX")}
        )
        failures = validate_bic(output, 1)
        assert len(failures) == 0

    def test_invalid_bic_fails(self):
        # Bank code must be letters
        output = _make_final_output(
            fields={"bic": _make_field("1234DEFF")}
        )
        failures = validate_bic(output, 1)
        assert len(failures) == 1
        assert failures[0].error_code == ErrorCode.VALIDATION_INVALID_BIC


class TestValidateDateRange:
    def test_valid_date_passes(self):
        output = _make_final_output(
            fields={"statement_date": _make_field("2024-01-15")}
        )
        failures = validate_date_range(output, 1)
        assert len(failures) == 0

    def test_future_date_fails(self):
        output = _make_final_output(
            fields={"statement_date": _make_field("2099-01-15")}
        )
        failures = validate_date_range(output, 1)
        assert len(failures) == 1
        assert failures[0].error_code == ErrorCode.VALIDATION_DATE_OUT_OF_RANGE

    def test_very_old_date_fails(self):
        output = _make_final_output(
            fields={"statement_date": _make_field("2000-01-15")}
        )
        failures = validate_date_range(output, 1)
        assert len(failures) == 1
        assert failures[0].error_code == ErrorCode.VALIDATION_DATE_OUT_OF_RANGE


class TestValidateCurrencyCodes:
    def test_valid_currency_passes(self):
        output = _make_final_output(
            fields={"currency": _make_field("EUR")}
        )
        failures = validate_currency_codes(output, 1)
        assert len(failures) == 0

    def test_invalid_currency_fails(self):
        output = _make_final_output(
            fields={"currency": _make_field("XYZ")}
        )
        failures = validate_currency_codes(output, 1)
        assert len(failures) == 1
        assert failures[0].error_code == ErrorCode.VALIDATION_INVALID_CURRENCY


class TestValidateProvenanceIntegrity:
    def test_valid_provenance_passes(self):
        output = _make_final_output(
            fields={"test_field": _make_field("value", page=1, source="native")}
        )
        failures = validate_provenance_integrity(output, 5)
        assert len(failures) == 0

    def test_invalid_page_number_fails(self):
        field = _make_field("value")
        field.provenance.page = 0
        output = _make_final_output(fields={"test_field": field})
        failures = validate_provenance_integrity(output, 5)
        assert len(failures) == 1
        assert failures[0].error_code == ErrorCode.VALIDATION_PROVENANCE_BROKEN

    def test_page_exceeds_total_fails(self):
        field = _make_field("value", page=10)
        output = _make_final_output(fields={"test_field": field})
        failures = validate_provenance_integrity(output, 5)
        assert len(failures) == 1

    def test_negative_bbox_fails(self):
        field = _make_field("value")
        field.provenance.bbox = [-1.0, 20.0, 100.0, 32.0]
        output = _make_final_output(fields={"test_field": field})
        failures = validate_provenance_integrity(output, 5)
        assert len(failures) == 1

    def test_invalid_source_fails(self):
        field = _make_field("value")
        field.provenance.source = "invalid"
        output = _make_final_output(fields={"test_field": field})
        failures = validate_provenance_integrity(output, 5)
        assert len(failures) == 1


class TestValidateArithmeticTotals:
    def test_consistent_arithmetic_passes(self):
        from api.models.response import TableRow, Table, TriangulationInfo

        output = _make_final_output(
            schema_type="bank_statement",
            fields={
                "opening_balance": _make_field(1000.0),
                "closing_balance": _make_field(1200.0),
            },
            tables=[
                Table(
                    table_id="tx_0",
                    type="transactions",
                    page_range=[1],
                    headers=["Date", "Description", "Debit", "Credit", "Balance"],
                    triangulation=TriangulationInfo(
                        score=0.0, verdict="agreement", winner="pdfplumber", methods=["pdfplumber"]
                    ),
                    rows=[
                        TableRow(cells=["01/01", "Payment", "100.00", "", "900.00"], row_index=0),
                        TableRow(cells=["02/01", "Deposit", "", "300.00", "1200.00"], row_index=1),
                    ],
                )
            ],
        )
        failures = validate_arithmetic_totals(output, 1)
        assert len(failures) == 0

    def test_inconsistent_arithmetic_fails(self):
        from api.models.response import TableRow, Table, TriangulationInfo

        output = _make_final_output(
            schema_type="bank_statement",
            fields={
                "opening_balance": _make_field(1000.0),
                "closing_balance": _make_field(2000.0),  # Wrong!
            },
            tables=[
                Table(
                    table_id="tx_0",
                    type="transactions",
                    page_range=[1],
                    headers=["Date", "Description", "Debit", "Credit", "Balance"],
                    triangulation=TriangulationInfo(
                        score=0.0, verdict="agreement", winner="pdfplumber", methods=["pdfplumber"]
                    ),
                    rows=[
                        TableRow(cells=["01/01", "Payment", "100.00", "", "900.00"], row_index=0),
                        TableRow(cells=["02/01", "Deposit", "", "300.00", "1200.00"], row_index=1),
                    ],
                )
            ],
        )
        failures = validate_arithmetic_totals(output, 1)
        assert len(failures) == 1
        assert failures[0].error_code == ErrorCode.VALIDATION_ARITHMETIC_MISMATCH

    def test_non_bank_statement_skipped(self):
        output = _make_final_output(schema_type="custody_statement")
        failures = validate_arithmetic_totals(output, 1)
        assert len(failures) == 0


class TestRunValidators:
    def test_all_validators_run(self):
        output = _make_final_output(
            fields={"test_field": _make_field("value", page=1, source="native")}
        )
        report = run_validators(output, total_pages=5)
        assert isinstance(report, ValidationReport)
        assert report.passed is True

    def test_collects_all_failures(self):
        field = _make_field("value")
        field.provenance.page = 0  # Invalid
        field.provenance.source = "invalid"  # Invalid
        output = _make_final_output(fields={"test_field": field})
        report = run_validators(output, total_pages=5)
        assert report.passed is False
        assert len(report.failures) >= 2


# ─── IBAN/ISIN/BIC Validation Helpers ────────────────────────────────────────


class TestIbanValidation:
    def test_valid_gb_iban(self):
        assert _is_valid_iban("GB29NWBK60161331926819") is True

    def test_valid_de_iban(self):
        assert _is_valid_iban("DE89370400440532013000") is True

    def test_invalid_checksum(self):
        assert _is_valid_iban("GB00NWBK60161331926819") is False

    def test_too_short(self):
        assert _is_valid_iban("GB29") is False


class TestIsinValidation:
    def test_valid_apple_isin(self):
        assert _is_valid_isin("US0378331005") is True

    def test_invalid_check_digit(self):
        assert _is_valid_isin("US0378331009") is False

    def test_wrong_length(self):
        assert _is_valid_isin("US037833100") is False


class TestBicValidation:
    def test_valid_8_char(self):
        assert _is_valid_bic("DEUTDEFF") is True

    def test_valid_11_char(self):
        assert _is_valid_bic("DEUTDEFFXXX") is True

    def test_invalid_bank_code(self):
        assert _is_valid_bic("1234DEFF") is False

    def test_invalid_length(self):
        assert _is_valid_bic("DEUTDE") is False


# ─── Packager Tests ──────────────────────────────────────────────────────────


class TestPackager:
    def test_package_complete_result(self):
        fields = {
            "account_number": _make_field("GB29NWBK60161331926819"),
            "closing_balance": _make_field(1500.0),
        }
        validation = ValidationReport(passed=True, failures=[])

        output = package_result(
            doc_id="sha256:abc123",
            schema_type="bank_statement",
            fields=fields,
            tables=[],
            abstentions=[],
            validation=validation,
        )

        assert output.doc_id == "sha256:abc123"
        assert output.schema_type == "bank_statement"
        assert output.status == "complete"
        assert output.confidence_summary.fields_extracted == 2
        assert output.confidence_summary.fields_abstained == 0
        assert output.pipeline_version == "0.1.0"

    def test_package_partial_result(self):
        fields = {"closing_balance": _make_field(1500.0)}
        abstentions = [
            Abstention(
                field="account_number",
                reason=ErrorCode.EXTRACTION_PATTERN_NOT_FOUND,
                detail="Not found",
                vlm_attempted=False,
            )
        ]
        validation = ValidationReport(passed=True, failures=[])

        output = package_result(
            doc_id="sha256:abc123",
            schema_type="bank_statement",
            fields=fields,
            tables=[],
            abstentions=abstentions,
            validation=validation,
        )

        assert output.status == "partial"
        assert output.confidence_summary.fields_abstained == 1

    def test_package_failed_result(self):
        validation = ValidationReport(passed=False, failures=[])

        output = package_result(
            doc_id="sha256:abc123",
            schema_type="bank_statement",
            fields={},
            tables=[],
            abstentions=[],
            validation=validation,
        )

        assert output.status == "failed"

    def test_confidence_summary_computation(self):
        fields = {
            "f1": _make_field("v1"),
            "f2": _make_field("v2"),
        }
        # Set different confidences
        fields["f1"].confidence = 0.90
        fields["f2"].confidence = 0.80
        fields["f2"].vlm_used = True

        validation = ValidationReport(passed=True, failures=[])

        output = package_result(
            doc_id="sha256:abc123",
            schema_type="bank_statement",
            fields=fields,
            tables=[],
            abstentions=[],
            validation=validation,
        )

        assert output.confidence_summary.mean_confidence == 0.85
        assert output.confidence_summary.min_confidence == 0.80
        assert output.confidence_summary.vlm_used_count == 1
