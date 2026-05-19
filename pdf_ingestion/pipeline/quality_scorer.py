"""Quality scorer for text_table_parser output.

Evaluates extracted tables using five internal consistency checks and returns
a structured verdict. This is a pure function with no I/O or side effects.

Checks:
    1. cell_fragmentation      — too many cells with ≤3 characters
    2. header_fragmentation    — header tokens that are substrings of known keywords
    3. date_column_incoherence — date columns with unparseable values
    4. row_uniformity          — high variance in non-null cell count per row
    5. numeric_column_incoherence — numeric columns with unparseable values

Each check catches exceptions internally and returns passed=True, metric=0.0
on error (fail-safe: don't escalate on scorer errors).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pipeline.extractors.text_table_parser import TextTable

logger = structlog.get_logger()

# ─── Known financial column keywords ─────────────────────────────────────────

FINANCIAL_KEYWORDS: list[str] = [
    "SETTL",
    "TRADE",
    "DESC",
    "ISIN",
    "CUSIP",
    "AMOUNT",
    "DEBIT",
    "CREDIT",
    "BALANCE",
    "QTY",
    "PRICE",
    "DATE",
    "BUY",
    "SELL",
    "NET",
]

# ─── Date column trigger words ────────────────────────────────────────────────

DATE_COLUMN_TRIGGERS: list[str] = ["DATE", "SETTL", "TRADE"]

# ─── Numeric column trigger words ────────────────────────────────────────────

NUMERIC_COLUMN_TRIGGERS: list[str] = ["BUY", "SELL", "QTY", "AMOUNT", "NET"]

# ─── Accepted date format patterns ───────────────────────────────────────────

# YYYY-MM-DD
_DATE_PATTERN_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# DD/MM/YYYY
_DATE_PATTERN_DMY_SLASH = re.compile(r"^\d{2}/\d{2}/\d{4}$")
# MM/DD/YYYY
_DATE_PATTERN_MDY_SLASH = re.compile(r"^\d{2}/\d{2}/\d{4}$")
# DD-MMM-YYYY  (e.g. 27-Mar-2024)
_DATE_PATTERN_DMY_MON = re.compile(
    r"^\d{2}-(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{4}$",
    re.IGNORECASE,
)

# Currency/comma stripping for numeric parsing
_NUMERIC_STRIP_PATTERN = re.compile(r"[,\$£€¥₹\s]")


# ─── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    """Result of a single quality check."""

    name: str       # one of the five check names
    passed: bool
    metric: float   # the measured value (e.g. fragmentation ratio)
    threshold: float  # the threshold that was compared against


@dataclass
class QualityResult:
    """Aggregated result of all five quality checks."""

    verdict: str                    # "pass" | "fail"
    failed_checks: list[str]        # names of failed checks
    checks: list[CheckResult] = field(default_factory=list)  # always 5 entries


# ─── Helper: date parsing ─────────────────────────────────────────────────────


def _is_valid_date(value: str) -> bool:
    """Return True if *value* matches any of the four accepted date formats."""
    v = value.strip()
    if not v:
        return False

    # YYYY-MM-DD
    if _DATE_PATTERN_ISO.match(v):
        try:
            datetime.strptime(v, "%Y-%m-%d")
            return True
        except ValueError:
            pass

    # DD-MMM-YYYY
    if _DATE_PATTERN_DMY_MON.match(v):
        try:
            datetime.strptime(v, "%d-%b-%Y")
            return True
        except ValueError:
            pass

    # DD/MM/YYYY or MM/DD/YYYY — both share the same regex; try both strptime formats
    if re.match(r"^\d{2}/\d{2}/\d{4}$", v):
        for fmt in ("%d/%m/%Y", "%m/%d/%Y"):
            try:
                datetime.strptime(v, fmt)
                return True
            except ValueError:
                pass

    return False


# ─── Helper: numeric parsing ──────────────────────────────────────────────────


def _is_valid_number(value: str) -> bool:
    """Return True if *value* can be parsed as a number after stripping commas
    and currency symbols."""
    cleaned = _NUMERIC_STRIP_PATTERN.sub("", value.strip())
    if not cleaned:
        return False
    # Allow optional leading minus/plus and optional decimal point
    try:
        float(cleaned.replace(",", ""))
        return True
    except ValueError:
        pass
    # Handle parenthesised negatives like (1,234.56)
    if cleaned.startswith("(") and cleaned.endswith(")"):
        try:
            float(cleaned[1:-1])
            return True
        except ValueError:
            pass
    return False


# ─── Individual checks ────────────────────────────────────────────────────────


def _check_cell_fragmentation(tables: list["TextTable"]) -> CheckResult:
    """Check 1: fraction of cells with ≤3 characters > 0.40 → fail."""
    threshold = 0.40
    try:
        total_cells = 0
        short_cells = 0
        for table in tables:
            for row in table.rows:
                for value in row.values():
                    if value is not None:
                        total_cells += 1
                        if len(str(value).strip()) <= 3:
                            short_cells += 1

        if total_cells == 0:
            return CheckResult(
                name="cell_fragmentation",
                passed=True,
                metric=0.0,
                threshold=threshold,
            )

        metric = short_cells / total_cells
        passed = metric <= threshold
        return CheckResult(
            name="cell_fragmentation",
            passed=passed,
            metric=metric,
            threshold=threshold,
        )
    except Exception:
        logger.warning("quality_scorer.check_error", check="cell_fragmentation")
        return CheckResult(
            name="cell_fragmentation", passed=True, metric=0.0, threshold=threshold
        )


def _check_header_fragmentation(tables: list["TextTable"]) -> CheckResult:
    """Check 2: any header token is a proper substring of a known keyword → fail."""
    threshold = 0.0  # boolean check; metric = 1.0 if fragmented, 0.0 if not
    try:
        for table in tables:
            for header in table.headers:
                # Split multi-word headers into individual tokens
                tokens = header.upper().split()
                for token in tokens:
                    if not token:
                        continue
                    for keyword in FINANCIAL_KEYWORDS:
                        # Token must be a proper substring: contained in keyword but shorter
                        if token != keyword and token in keyword:
                            return CheckResult(
                                name="header_fragmentation",
                                passed=False,
                                metric=1.0,
                                threshold=threshold,
                            )
        return CheckResult(
            name="header_fragmentation", passed=True, metric=0.0, threshold=threshold
        )
    except Exception:
        logger.warning("quality_scorer.check_error", check="header_fragmentation")
        return CheckResult(
            name="header_fragmentation", passed=True, metric=0.0, threshold=threshold
        )


def _check_date_column_incoherence(tables: list["TextTable"]) -> CheckResult:
    """Check 3: date columns with >50% unparseable values → fail."""
    threshold = 0.50
    try:
        total_non_null = 0
        total_invalid = 0
        found_date_column = False

        for table in tables:
            for header in table.headers:
                header_upper = header.upper()
                if not any(trigger in header_upper for trigger in DATE_COLUMN_TRIGGERS):
                    continue

                found_date_column = True
                # Collect non-null values for this column
                for row in table.rows:
                    value = row.get(header)
                    if value is None or str(value).strip() == "":
                        continue
                    total_non_null += 1
                    if not _is_valid_date(str(value)):
                        total_invalid += 1

        if not found_date_column or total_non_null == 0:
            return CheckResult(
                name="date_column_incoherence",
                passed=True,
                metric=0.0,
                threshold=threshold,
            )

        metric = total_invalid / total_non_null
        passed = metric <= threshold
        return CheckResult(
            name="date_column_incoherence",
            passed=passed,
            metric=metric,
            threshold=threshold,
        )
    except Exception:
        logger.warning("quality_scorer.check_error", check="date_column_incoherence")
        return CheckResult(
            name="date_column_incoherence", passed=True, metric=0.0, threshold=threshold
        )


def _check_row_uniformity(tables: list["TextTable"]) -> CheckResult:
    """Check 4: std dev of non-null cell count per row > 2.0 → fail."""
    threshold = 2.0
    try:
        row_counts: list[int] = []
        for table in tables:
            for row in table.rows:
                non_null = sum(
                    1 for v in row.values() if v is not None and str(v).strip() != ""
                )
                row_counts.append(non_null)

        if len(row_counts) < 2:
            return CheckResult(
                name="row_uniformity", passed=True, metric=0.0, threshold=threshold
            )

        mean = sum(row_counts) / len(row_counts)
        variance = sum((x - mean) ** 2 for x in row_counts) / len(row_counts)
        std_dev = math.sqrt(variance)

        passed = std_dev <= threshold
        return CheckResult(
            name="row_uniformity",
            passed=passed,
            metric=std_dev,
            threshold=threshold,
        )
    except Exception:
        logger.warning("quality_scorer.check_error", check="row_uniformity")
        return CheckResult(
            name="row_uniformity", passed=True, metric=0.0, threshold=threshold
        )


def _check_numeric_column_incoherence(tables: list["TextTable"]) -> CheckResult:
    """Check 5: numeric columns with >30% unparseable values → fail."""
    threshold = 0.30
    try:
        total_non_null = 0
        total_invalid = 0
        found_numeric_column = False

        for table in tables:
            for header in table.headers:
                header_upper = header.upper()
                if not any(trigger in header_upper for trigger in NUMERIC_COLUMN_TRIGGERS):
                    continue

                found_numeric_column = True
                for row in table.rows:
                    value = row.get(header)
                    if value is None or str(value).strip() == "":
                        continue
                    total_non_null += 1
                    if not _is_valid_number(str(value)):
                        total_invalid += 1

        if not found_numeric_column or total_non_null == 0:
            return CheckResult(
                name="numeric_column_incoherence",
                passed=True,
                metric=0.0,
                threshold=threshold,
            )

        metric = total_invalid / total_non_null
        passed = metric <= threshold
        return CheckResult(
            name="numeric_column_incoherence",
            passed=passed,
            metric=metric,
            threshold=threshold,
        )
    except Exception:
        logger.warning("quality_scorer.check_error", check="numeric_column_incoherence")
        return CheckResult(
            name="numeric_column_incoherence", passed=True, metric=0.0, threshold=threshold
        )


# ─── Public API ───────────────────────────────────────────────────────────────


def score_tables(tables: list["TextTable"]) -> QualityResult:
    """Evaluate five quality checks on a list of TextTable objects.

    Pure function — no I/O, no side effects.

    Bypass scoring (return early with a "pass" verdict) when:
    - The input list is empty, OR
    - All tables have zero rows.

    Individual checks catch exceptions internally and return passed=True,
    metric=0.0 on error (fail-safe: don't escalate on scorer errors).

    Args:
        tables: List of TextTable objects produced by text_table_parser.

    Returns:
        QualityResult with verdict ("pass" | "fail"), list of failed check
        names, and one CheckResult per check (always exactly five).
    """
    # Bypass: no tables or all tables empty
    if not tables or all(len(t.rows) == 0 for t in tables):
        checks = [
            CheckResult(name="cell_fragmentation", passed=True, metric=0.0, threshold=0.40),
            CheckResult(name="header_fragmentation", passed=True, metric=0.0, threshold=0.0),
            CheckResult(name="date_column_incoherence", passed=True, metric=0.0, threshold=0.50),
            CheckResult(name="row_uniformity", passed=True, metric=0.0, threshold=2.0),
            CheckResult(name="numeric_column_incoherence", passed=True, metric=0.0, threshold=0.30),
        ]
        return QualityResult(verdict="pass", failed_checks=[], checks=checks)

    checks: list[CheckResult] = [
        _check_cell_fragmentation(tables),
        _check_header_fragmentation(tables),
        _check_date_column_incoherence(tables),
        _check_row_uniformity(tables),
        _check_numeric_column_incoherence(tables),
    ]

    failed_checks = [c.name for c in checks if not c.passed]
    verdict = "fail" if failed_checks else "pass"

    return QualityResult(verdict=verdict, failed_checks=failed_checks, checks=checks)
