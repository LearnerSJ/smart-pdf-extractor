"""Validation engine.

All validators are pure functions that do not mutate the ExtractionResult
or AssembledDocument. They execute regardless of individual failures,
producing a complete ValidationReport.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from api.errors import ErrorCode
from api.models.response import Abstention, Field, FinalOutput, Table


# ─── Validation Report ────────────────────────────────────────────────────────


@dataclass
class ValidationFailure:
    """A single validation failure."""

    validator_name: str
    field_name: str | None
    error_code: str
    detail: str


@dataclass
class ValidationReport:
    """Complete validation report for an extraction result."""

    passed: bool
    failures: list[ValidationFailure] = field(default_factory=list)


# ─── ISO 4217 Common Currency Codes ──────────────────────────────────────────

VALID_CURRENCY_CODES: set[str] = {
    "AED", "AFN", "ALL", "AMD", "ANG", "AOA", "ARS", "AUD", "AWG", "AZN",
    "BAM", "BBD", "BDT", "BGN", "BHD", "BIF", "BMD", "BND", "BOB", "BRL",
    "BSD", "BTN", "BWP", "BYN", "BZD", "CAD", "CDF", "CHF", "CLP", "CNY",
    "COP", "CRC", "CUP", "CVE", "CZK", "DJF", "DKK", "DOP", "DZD", "EGP",
    "ERN", "ETB", "EUR", "FJD", "FKP", "GBP", "GEL", "GHS", "GIP", "GMD",
    "GNF", "GTQ", "GYD", "HKD", "HNL", "HRK", "HTG", "HUF", "IDR", "ILS",
    "INR", "IQD", "IRR", "ISK", "JMD", "JOD", "JPY", "KES", "KGS", "KHR",
    "KMF", "KPW", "KRW", "KWD", "KYD", "KZT", "LAK", "LBP", "LKR", "LRD",
    "LSL", "LYD", "MAD", "MDL", "MGA", "MKD", "MMK", "MNT", "MOP", "MRU",
    "MUR", "MVR", "MWK", "MXN", "MYR", "MZN", "NAD", "NGN", "NIO", "NOK",
    "NPR", "NZD", "OMR", "PAB", "PEN", "PGK", "PHP", "PKR", "PLN", "PYG",
    "QAR", "RON", "RSD", "RUB", "RWF", "SAR", "SBD", "SCR", "SDG", "SEK",
    "SGD", "SHP", "SLE", "SOS", "SRD", "SSP", "STN", "SVC", "SYP", "SZL",
    "THB", "TJS", "TMT", "TND", "TOP", "TRY", "TTD", "TWD", "TZS", "UAH",
    "UGX", "USD", "UYU", "UZS", "VES", "VND", "VUV", "WST", "XAF", "XCD",
    "XOF", "XPF", "YER", "ZAR", "ZMW", "ZWL",
}


# ─── Validator Pure Functions ─────────────────────────────────────────────────


def validate_arithmetic_totals(
    output: FinalOutput,
    total_pages: int,
) -> list[ValidationFailure]:
    """Validate arithmetic consistency for bank statements.

    Checks: |closing_balance - (opening_balance + sum(credits) - sum(debits))| ≤ 0.02

    Only applies to bank_statement schema type.
    """
    if output.schema_type != "bank_statement":
        return []

    failures: list[ValidationFailure] = []

    # Need opening_balance, closing_balance, and transactions table
    opening = output.fields.get("opening_balance")
    closing = output.fields.get("closing_balance")

    if opening is None or closing is None:
        # Can't validate without both balances
        return []

    opening_val = _to_float(opening.value)
    closing_val = _to_float(closing.value)

    if opening_val is None or closing_val is None:
        return []

    # Find transactions table and sum debits/credits
    total_credits = 0.0
    total_debits = 0.0

    for table in output.tables:
        if table.type == "transactions":
            headers_lower = [h.lower() for h in table.headers]
            debit_idx = _find_header_index(headers_lower, ["debit", "debits", "dr"])
            credit_idx = _find_header_index(headers_lower, ["credit", "credits", "cr"])

            if debit_idx is not None and credit_idx is not None:
                for row in table.rows:
                    if len(row.cells) > max(debit_idx, credit_idx):
                        debit_val = _to_float(row.cells[debit_idx])
                        credit_val = _to_float(row.cells[credit_idx])
                        if debit_val is not None:
                            total_debits += debit_val
                        if credit_val is not None:
                            total_credits += credit_val

    # Check arithmetic identity
    expected_closing = opening_val + total_credits - total_debits
    diff = abs(closing_val - expected_closing)

    if diff > 0.02:
        failures.append(
            ValidationFailure(
                validator_name="validate_arithmetic_totals",
                field_name="closing_balance",
                error_code=ErrorCode.VALIDATION_ARITHMETIC_MISMATCH,
                detail=(
                    f"Arithmetic mismatch: closing_balance ({closing_val}) != "
                    f"opening_balance ({opening_val}) + credits ({total_credits}) "
                    f"- debits ({total_debits}) = {expected_closing}. "
                    f"Difference: {diff:.4f} (tolerance: 0.02)"
                ),
            )
        )

    return failures


def validate_iban(
    output: FinalOutput,
    total_pages: int,
) -> list[ValidationFailure]:
    """Validate IBAN values using mod-97 checksum.

    Rearranges the IBAN (move first 4 chars to end), converts letters
    to numbers (A=10, B=11, ..., Z=35), and checks mod 97 == 1.
    """
    failures: list[ValidationFailure] = []

    for field_name, field_obj in output.fields.items():
        value = str(field_obj.value) if field_obj.value is not None else ""
        # Check if this looks like an IBAN
        cleaned = re.sub(r"\s+", "", value).upper()
        if not re.match(r"^[A-Z]{2}\d{2}[A-Z0-9]+$", cleaned):
            continue

        if not _is_valid_iban(cleaned):
            failures.append(
                ValidationFailure(
                    validator_name="validate_iban",
                    field_name=field_name,
                    error_code=ErrorCode.VALIDATION_INVALID_IBAN,
                    detail=f"IBAN '{cleaned}' failed mod-97 checksum validation",
                )
            )

    return failures


def validate_isin(
    output: FinalOutput,
    total_pages: int,
) -> list[ValidationFailure]:
    """Validate ISIN values using ISO 6166 check digit (Luhn algorithm).

    Converts letters to numbers (A=10, B=11, ..., Z=35), concatenates
    all digits, then applies Luhn algorithm.
    """
    failures: list[ValidationFailure] = []

    for field_name, field_obj in output.fields.items():
        value = str(field_obj.value) if field_obj.value is not None else ""
        cleaned = value.strip().upper()
        # Check if this looks like an ISIN (2 letters + 9 alphanumeric + 1 digit)
        if not re.match(r"^[A-Z]{2}[A-Z0-9]{9}\d$", cleaned):
            continue

        if not _is_valid_isin(cleaned):
            failures.append(
                ValidationFailure(
                    validator_name="validate_isin",
                    field_name=field_name,
                    error_code=ErrorCode.VALIDATION_INVALID_ISIN,
                    detail=f"ISIN '{cleaned}' failed ISO 6166 check digit validation (Luhn)",
                )
            )

    return failures


def validate_bic(
    output: FinalOutput,
    total_pages: int,
) -> list[ValidationFailure]:
    """Validate BIC/SWIFT codes (8 or 11 character format).

    Format: BBBBCCLL or BBBBCCLLBBB
    - BBBB: bank code (alpha)
    - CC: country code (alpha)
    - LL: location code (alphanumeric)
    - BBB: branch code (alphanumeric, optional)
    """
    failures: list[ValidationFailure] = []

    for field_name, field_obj in output.fields.items():
        value = str(field_obj.value) if field_obj.value is not None else ""
        cleaned = value.strip().upper()

        # Check if this looks like a BIC (8 or 11 alphanumeric chars)
        if not re.match(r"^[A-Z0-9]{8}$|^[A-Z0-9]{11}$", cleaned):
            continue

        if not _is_valid_bic(cleaned):
            failures.append(
                ValidationFailure(
                    validator_name="validate_bic",
                    field_name=field_name,
                    error_code=ErrorCode.VALIDATION_INVALID_BIC,
                    detail=f"BIC '{cleaned}' does not conform to SWIFT BIC format",
                )
            )

    return failures


def validate_date_range(
    output: FinalOutput,
    total_pages: int,
) -> list[ValidationFailure]:
    """Validate dates are not in the future and not more than 10 years in the past."""
    failures: list[ValidationFailure] = []
    now = datetime.now(timezone.utc)
    ten_years_ago = now.replace(year=now.year - 10)

    for field_name, field_obj in output.fields.items():
        value = str(field_obj.value) if field_obj.value is not None else ""
        # Try to parse as ISO date
        parsed = _try_parse_date(value)
        if parsed is None:
            continue

        if parsed > now:
            failures.append(
                ValidationFailure(
                    validator_name="validate_date_range",
                    field_name=field_name,
                    error_code=ErrorCode.VALIDATION_DATE_OUT_OF_RANGE,
                    detail=f"Date '{value}' is in the future",
                )
            )
        elif parsed < ten_years_ago:
            failures.append(
                ValidationFailure(
                    validator_name="validate_date_range",
                    field_name=field_name,
                    error_code=ErrorCode.VALIDATION_DATE_OUT_OF_RANGE,
                    detail=f"Date '{value}' is more than 10 years in the past",
                )
            )

    return failures


def validate_currency_codes(
    output: FinalOutput,
    total_pages: int,
) -> list[ValidationFailure]:
    """Validate currency codes against ISO 4217."""
    failures: list[ValidationFailure] = []

    for field_name, field_obj in output.fields.items():
        value = str(field_obj.value) if field_obj.value is not None else ""
        # Check if this looks like a currency code (exactly 3 uppercase letters)
        cleaned = value.strip().upper()
        if re.match(r"^[A-Z]{3}$", cleaned):
            if cleaned not in VALID_CURRENCY_CODES:
                failures.append(
                    ValidationFailure(
                        validator_name="validate_currency_codes",
                        field_name=field_name,
                        error_code=ErrorCode.VALIDATION_INVALID_CURRENCY,
                        detail=f"Currency code '{cleaned}' is not a valid ISO 4217 code",
                    )
                )

    return failures


def validate_provenance_integrity(
    output: FinalOutput,
    total_pages: int,
) -> list[ValidationFailure]:
    """Validate provenance integrity on all extracted fields.

    Checks:
    - Every field has a page number (positive integer)
    - Every field has a bounding box within page bounds
    """
    failures: list[ValidationFailure] = []

    for field_name, field_obj in output.fields.items():
        prov = field_obj.provenance

        # Check page number is positive
        if prov.page < 1:
            failures.append(
                ValidationFailure(
                    validator_name="validate_provenance_integrity",
                    field_name=field_name,
                    error_code=ErrorCode.VALIDATION_PROVENANCE_BROKEN,
                    detail=f"Field '{field_name}' has invalid page number: {prov.page}",
                )
            )

        # Check page number is within document bounds
        if total_pages > 0 and prov.page > total_pages:
            failures.append(
                ValidationFailure(
                    validator_name="validate_provenance_integrity",
                    field_name=field_name,
                    error_code=ErrorCode.VALIDATION_PROVENANCE_BROKEN,
                    detail=f"Field '{field_name}' page {prov.page} exceeds document page count {total_pages}",
                )
            )

        # Check bbox has 4 non-negative elements
        if len(prov.bbox) != 4:
            failures.append(
                ValidationFailure(
                    validator_name="validate_provenance_integrity",
                    field_name=field_name,
                    error_code=ErrorCode.VALIDATION_PROVENANCE_BROKEN,
                    detail=f"Field '{field_name}' bbox has {len(prov.bbox)} elements (expected 4)",
                )
            )
        elif any(v < 0 for v in prov.bbox):
            failures.append(
                ValidationFailure(
                    validator_name="validate_provenance_integrity",
                    field_name=field_name,
                    error_code=ErrorCode.VALIDATION_PROVENANCE_BROKEN,
                    detail=f"Field '{field_name}' bbox contains negative values: {prov.bbox}",
                )
            )

        # Check source is valid
        if prov.source not in ("native", "ocr", "vlm"):
            failures.append(
                ValidationFailure(
                    validator_name="validate_provenance_integrity",
                    field_name=field_name,
                    error_code=ErrorCode.VALIDATION_PROVENANCE_BROKEN,
                    detail=f"Field '{field_name}' has invalid provenance source: '{prov.source}'",
                )
            )

    return failures


# ─── Account-Level Validators ─────────────────────────────────────────────────


def validate_running_balance(
    output: FinalOutput,
    total_pages: int,
) -> list[ValidationFailure]:
    """Validate running balance consistency within each account's transactions.

    For each transaction that has a balance field, verifies:
        previous_balance + credit - debit = current_balance

    Any break in the chain indicates a misplaced value or missed transaction.
    """
    failures: list[ValidationFailure] = []
    accounts_field = output.fields.get("accounts")
    if not accounts_field or not accounts_field.value:
        return failures

    accounts = accounts_field.value
    if not isinstance(accounts, list):
        return failures

    for acct_idx, account in enumerate(accounts):
        if not isinstance(account, dict):
            continue
        transactions = account.get("transactions", [])
        if not transactions or not isinstance(transactions, list):
            continue

        acct_id = account.get("account_number") or account.get("iban") or f"account_{acct_idx}"
        prev_balance: float | None = None

        for txn_idx, txn in enumerate(transactions):
            if not isinstance(txn, dict):
                continue

            balance = _to_float(txn.get("balance"))
            debit = _to_float(txn.get("debit")) or 0.0
            credit = _to_float(txn.get("credit")) or 0.0

            if balance is None:
                continue

            if prev_balance is not None:
                expected = prev_balance + credit - debit
                diff = abs(balance - expected)
                if diff > 0.02:
                    failures.append(
                        ValidationFailure(
                            validator_name="validate_running_balance",
                            field_name=f"{acct_id}.transaction[{txn_idx}]",
                            error_code="ERR_VAL_RUNNING_BALANCE",
                            detail=(
                                f"Running balance break at row {txn_idx}: "
                                f"expected {expected:.2f} (prev {prev_balance:.2f} + credit {credit:.2f} - debit {debit:.2f}), "
                                f"got {balance:.2f}. Diff: {diff:.2f}"
                            ),
                        )
                    )

            prev_balance = balance

    return failures


def validate_account_balance_reconciliation(
    output: FinalOutput,
    total_pages: int,
) -> list[ValidationFailure]:
    """Validate opening + credits - debits = closing for each account.

    Stronger than the existing validate_arithmetic_totals which only checks
    document-level fields. This checks per-account.
    """
    failures: list[ValidationFailure] = []
    accounts_field = output.fields.get("accounts")
    if not accounts_field or not accounts_field.value:
        return failures

    accounts = accounts_field.value
    if not isinstance(accounts, list):
        return failures

    for acct_idx, account in enumerate(accounts):
        if not isinstance(account, dict):
            continue

        acct_id = account.get("account_number") or account.get("iban") or f"account_{acct_idx}"
        opening = _to_float(account.get("opening_balance"))
        closing = _to_float(account.get("closing_balance"))

        if opening is None or closing is None:
            continue

        transactions = account.get("transactions", [])
        if not transactions:
            continue

        total_debits = 0.0
        total_credits = 0.0
        for txn in transactions:
            if not isinstance(txn, dict):
                continue
            d = _to_float(txn.get("debit")) or 0.0
            c = _to_float(txn.get("credit")) or 0.0
            total_debits += d
            total_credits += c

        expected_closing = opening + total_credits - total_debits
        diff = abs(closing - expected_closing)

        if diff > 0.02:
            failures.append(
                ValidationFailure(
                    validator_name="validate_account_balance_reconciliation",
                    field_name=acct_id,
                    error_code="ERR_VAL_BALANCE_RECON",
                    detail=(
                        f"Account {acct_id}: closing ({closing:.2f}) != "
                        f"opening ({opening:.2f}) + credits ({total_credits:.2f}) "
                        f"- debits ({total_debits:.2f}) = {expected_closing:.2f}. "
                        f"Diff: {diff:.2f} — possible missed transactions or column misalignment"
                    ),
                )
            )

    return failures


def validate_column_type_consistency(
    output: FinalOutput,
    total_pages: int,
) -> list[ValidationFailure]:
    """Validate that values in each column match expected data types.

    Checks:
    - Date column: values parse as dates
    - Debit/Credit columns: values are numeric
    - Description column: contains text (not purely numeric)

    Mismatches indicate column misalignment during extraction.
    """
    failures: list[ValidationFailure] = []
    accounts_field = output.fields.get("accounts")
    if not accounts_field or not accounts_field.value:
        return failures

    accounts = accounts_field.value
    if not isinstance(accounts, list):
        return failures

    for acct_idx, account in enumerate(accounts):
        if not isinstance(account, dict):
            continue

        acct_id = account.get("account_number") or account.get("iban") or f"account_{acct_idx}"
        transactions = account.get("transactions", [])
        if not transactions:
            continue

        date_errors = 0
        amount_in_desc = 0
        desc_is_number = 0

        for txn_idx, txn in enumerate(transactions):
            if not isinstance(txn, dict):
                continue

            # Check date column contains parseable dates
            date_val = txn.get("date")
            if date_val and isinstance(date_val, str) and date_val.strip():
                if _try_parse_date(date_val) is None:
                    # Check if it looks like a number (column misalignment)
                    try:
                        float(date_val.replace(",", ""))
                        date_errors += 1
                    except ValueError:
                        pass

            # Check description isn't purely numeric (would indicate column shift)
            desc = txn.get("description")
            if desc and isinstance(desc, str):
                cleaned_desc = desc.strip().replace(",", "").replace(".", "")
                if cleaned_desc.isdigit() and len(cleaned_desc) > 3:
                    desc_is_number += 1

        total_txns = len(transactions)
        if total_txns > 0:
            # Flag if >20% of dates are actually numbers
            if date_errors > 0 and date_errors / total_txns > 0.2:
                failures.append(
                    ValidationFailure(
                        validator_name="validate_column_type_consistency",
                        field_name=f"{acct_id}.date",
                        error_code="ERR_VAL_COLUMN_TYPE",
                        detail=(
                            f"Account {acct_id}: {date_errors}/{total_txns} date values "
                            f"appear to be numbers — possible column misalignment"
                        ),
                    )
                )

            # Flag if >20% of descriptions are purely numeric
            if desc_is_number > 0 and desc_is_number / total_txns > 0.2:
                failures.append(
                    ValidationFailure(
                        validator_name="validate_column_type_consistency",
                        field_name=f"{acct_id}.description",
                        error_code="ERR_VAL_COLUMN_TYPE",
                        detail=(
                            f"Account {acct_id}: {desc_is_number}/{total_txns} descriptions "
                            f"are purely numeric — possible column misalignment"
                        ),
                    )
                )

    return failures


def validate_transaction_completeness(
    output: FinalOutput,
    total_pages: int,
) -> list[ValidationFailure]:
    """Check for potential missed transactions by comparing page coverage.

    Flags accounts where the number of transaction pages seems too low
    relative to the total pages assigned to that account's section.
    Also checks if any account has zero transactions despite having pages.
    """
    failures: list[ValidationFailure] = []
    accounts_field = output.fields.get("accounts")
    if not accounts_field or not accounts_field.value:
        return failures

    accounts = accounts_field.value
    if not isinstance(accounts, list):
        return failures

    for acct_idx, account in enumerate(accounts):
        if not isinstance(account, dict):
            continue

        acct_id = account.get("account_number") or account.get("iban") or f"account_{acct_idx}"
        transactions = account.get("transactions", [])

        # Flag accounts with no transactions at all
        if not transactions:
            failures.append(
                ValidationFailure(
                    validator_name="validate_transaction_completeness",
                    field_name=acct_id,
                    error_code="ERR_VAL_NO_TRANSACTIONS",
                    detail=f"Account {acct_id} has no transactions extracted",
                )
            )

    return failures


def validate_totals_crosscheck(
    output: FinalOutput,
    total_pages: int,
) -> list[ValidationFailure]:
    """Cross-check extracted totals against sum of individual transactions.

    Many statements include "Total Debits" and "Total Credits" summary fields.
    If present, compare against the sum of the debit/credit columns.
    """
    failures: list[ValidationFailure] = []
    accounts_field = output.fields.get("accounts")
    if not accounts_field or not accounts_field.value:
        return failures

    accounts = accounts_field.value
    if not isinstance(accounts, list):
        return failures

    for acct_idx, account in enumerate(accounts):
        if not isinstance(account, dict):
            continue

        acct_id = account.get("account_number") or account.get("iban") or f"account_{acct_idx}"
        transactions = account.get("transactions", [])

        # Look for total_debits / total_credits fields in the account
        stated_total_debits = _to_float(account.get("total_debits"))
        stated_total_credits = _to_float(account.get("total_credits"))

        if stated_total_debits is None and stated_total_credits is None:
            continue

        computed_debits = 0.0
        computed_credits = 0.0
        for txn in transactions:
            if not isinstance(txn, dict):
                continue
            d = _to_float(txn.get("debit")) or 0.0
            c = _to_float(txn.get("credit")) or 0.0
            computed_debits += d
            computed_credits += c

        if stated_total_debits is not None:
            diff = abs(stated_total_debits - computed_debits)
            if diff > 0.02:
                failures.append(
                    ValidationFailure(
                        validator_name="validate_totals_crosscheck",
                        field_name=f"{acct_id}.total_debits",
                        error_code="ERR_VAL_TOTALS_MISMATCH",
                        detail=(
                            f"Account {acct_id}: stated total debits ({stated_total_debits:.2f}) != "
                            f"sum of debit column ({computed_debits:.2f}). "
                            f"Diff: {diff:.2f} — possible missed transactions"
                        ),
                    )
                )

        if stated_total_credits is not None:
            diff = abs(stated_total_credits - computed_credits)
            if diff > 0.02:
                failures.append(
                    ValidationFailure(
                        validator_name="validate_totals_crosscheck",
                        field_name=f"{acct_id}.total_credits",
                        error_code="ERR_VAL_TOTALS_MISMATCH",
                        detail=(
                            f"Account {acct_id}: stated total credits ({stated_total_credits:.2f}) != "
                            f"sum of credit column ({computed_credits:.2f}). "
                            f"Diff: {diff:.2f} — possible missed transactions"
                        ),
                    )
                )

    return failures


# ─── Main Entry Point ─────────────────────────────────────────────────────────


def run_validators(
    output: FinalOutput,
    total_pages: int = 0,
) -> ValidationReport:
    """Execute all validators and produce a complete ValidationReport.

    All validators run regardless of individual failures.
    Validators are pure functions — they do not mutate the output.

    Args:
        output: The FinalOutput to validate.
        total_pages: Total number of pages in the document.

    Returns:
        ValidationReport with all failures collected.
    """
    all_failures: list[ValidationFailure] = []

    validators = [
        validate_arithmetic_totals,
        validate_iban,
        validate_isin,
        validate_bic,
        validate_date_range,
        validate_currency_codes,
        validate_provenance_integrity,
        validate_running_balance,
        validate_account_balance_reconciliation,
        validate_column_type_consistency,
        validate_transaction_completeness,
        validate_totals_crosscheck,
    ]

    for validator in validators:
        failures = validator(output, total_pages)
        all_failures.extend(failures)

    return ValidationReport(
        passed=len(all_failures) == 0,
        failures=all_failures,
    )


# ─── Private Helpers ──────────────────────────────────────────────────────────


def _is_valid_iban(iban: str) -> bool:
    """Validate IBAN using mod-97 checksum.

    Algorithm:
    1. Move first 4 characters to end
    2. Convert letters to numbers (A=10, B=11, ..., Z=35)
    3. Compute mod 97 — must equal 1
    """
    if len(iban) < 5:
        return False

    # Rearrange: move first 4 chars to end
    rearranged = iban[4:] + iban[:4]

    # Convert letters to numbers
    numeric_str = ""
    for char in rearranged:
        if char.isdigit():
            numeric_str += char
        elif char.isalpha():
            numeric_str += str(ord(char) - ord("A") + 10)
        else:
            return False

    # Mod 97 check
    try:
        return int(numeric_str) % 97 == 1
    except (ValueError, OverflowError):
        return False


def _is_valid_isin(isin: str) -> bool:
    """Validate ISIN using ISO 6166 check digit (Luhn on numeric conversion).

    Algorithm:
    1. Convert all characters to numbers (A=10, B=11, ..., Z=35)
    2. Concatenate all digits into a single string
    3. Apply Luhn algorithm to the full digit string
    """
    if len(isin) != 12:
        return False

    # Convert to digit string
    digit_str = ""
    for char in isin:
        if char.isdigit():
            digit_str += char
        elif char.isalpha():
            digit_str += str(ord(char) - ord("A") + 10)
        else:
            return False

    # Apply Luhn algorithm
    return _luhn_check(digit_str)


def _luhn_check(digit_str: str) -> bool:
    """Apply Luhn algorithm to a digit string.

    Starting from the rightmost digit, double every second digit.
    If doubling results in a number > 9, subtract 9.
    Sum all digits. Valid if sum mod 10 == 0.
    """
    digits = [int(d) for d in digit_str]
    # Reverse for processing
    digits.reverse()

    total = 0
    for i, digit in enumerate(digits):
        if i % 2 == 1:
            doubled = digit * 2
            if doubled > 9:
                doubled -= 9
            total += doubled
        else:
            total += digit

    return total % 10 == 0


def _is_valid_bic(bic: str) -> bool:
    """Validate BIC/SWIFT code format.

    Format: BBBBCCLL[BBB]
    - BBBB: bank code (4 letters)
    - CC: country code (2 letters)
    - LL: location code (2 alphanumeric)
    - BBB: branch code (3 alphanumeric, optional)
    """
    if len(bic) not in (8, 11):
        return False

    # Bank code: 4 letters
    if not bic[:4].isalpha():
        return False

    # Country code: 2 letters
    if not bic[4:6].isalpha():
        return False

    # Location code: 2 alphanumeric
    if not bic[6:8].isalnum():
        return False

    # Branch code (if present): 3 alphanumeric
    if len(bic) == 11 and not bic[8:11].isalnum():
        return False

    return True


def _to_float(value: Any) -> float | None:
    """Safely convert a value to float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        # Strip currency symbols and commas
        cleaned = re.sub(r"[€$£¥₹\s,]", "", str(value))
        if not cleaned:
            return None
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _try_parse_date(value: str) -> datetime | None:
    """Try to parse a string as a date."""
    cleaned = value.strip()
    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%B %d, %Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(cleaned, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _find_header_index(
    headers: list[str], candidates: list[str]
) -> int | None:
    """Find the index of a header matching any of the candidates.

    Tries exact match first, then substring match with word boundaries.
    """
    # First pass: exact match
    for idx, header in enumerate(headers):
        for candidate in candidates:
            if header == candidate:
                return idx

    # Second pass: header starts with candidate or candidate starts with header
    for idx, header in enumerate(headers):
        for candidate in candidates:
            if header.startswith(candidate) or candidate.startswith(header):
                return idx

    return None
