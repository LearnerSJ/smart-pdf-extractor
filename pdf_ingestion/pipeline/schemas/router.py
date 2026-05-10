"""Schema router.

Detects document schema type based on structural signals and routes
to the appropriate extractor. Uses keyword density and structural
patterns — no LLM involved.
"""

from __future__ import annotations

import structlog

from api.errors import ErrorCode
from api.models.response import Abstention
from pipeline.models import AssembledDocument
from pipeline.schemas.bank_statement import BankStatementExtractor
from pipeline.schemas.base import BaseSchemaExtractor
from pipeline.schemas.custody_statement import CustodyStatementExtractor
from pipeline.schemas.swift_confirm import SwiftConfirmExtractor

logger = structlog.get_logger()

# ─── Structural Signal Keywords ───────────────────────────────────────────────

BANK_STATEMENT_KEYWORDS: list[str] = [
    "statement",
    "account",
    "balance",
    "debit",
    "credit",
    "transaction",
    "opening balance",
    "closing balance",
    "brought forward",
    "carried forward",
    "sort code",
    "iban",
]

CUSTODY_STATEMENT_KEYWORDS: list[str] = [
    "portfolio",
    "custody",
    "valuation",
    "holdings",
    "positions",
    "isin",
    "securities",
    "market value",
    "net asset",
    "depot",
    "quantity",
    "nominal",
]

SWIFT_CONFIRM_KEYWORDS: list[str] = [
    "swift",
    "mt5",
    "trade confirmation",
    "settlement",
    "counterparty",
    "bic",
    ":20:",
    ":98a:",
    ":35b:",
    ":36b:",
    ":90a:",
    ":95p:",
    "{1:",
    "{4:",
]

# Minimum keyword density threshold to classify
MIN_DENSITY_THRESHOLD = 0.02  # At least 2% of words must be keywords


def detect_schema(doc: AssembledDocument) -> str:
    """Detect the document schema type based on structural signals.

    Uses keyword density analysis and structural patterns (SWIFT tags,
    page layout) to determine the document type.

    Args:
        doc: The assembled document to classify.

    Returns:
        Schema type string: "bank_statement", "custody_statement",
        "swift_confirm", or "unknown".
    """
    # Build full text from document for keyword analysis
    full_text = _build_full_text(doc).lower()
    word_count = max(len(full_text.split()), 1)

    # Check for SWIFT structural signals first (most distinctive)
    swift_score = _compute_keyword_score(full_text, SWIFT_CONFIRM_KEYWORDS, word_count)
    has_swift_tags = _has_swift_structure(full_text)

    # If SWIFT tags are present, strongly favour swift_confirm
    if has_swift_tags:
        swift_score += 0.10

    # Compute scores for other types
    bank_score = _compute_keyword_score(full_text, BANK_STATEMENT_KEYWORDS, word_count)
    custody_score = _compute_keyword_score(full_text, CUSTODY_STATEMENT_KEYWORDS, word_count)

    scores = {
        "swift_confirm": swift_score,
        "bank_statement": bank_score,
        "custody_statement": custody_score,
    }

    # Select the highest scoring type
    best_type = max(scores, key=lambda k: scores[k])
    best_score = scores[best_type]

    logger.info(
        "schema.detected",
        schema_type=best_type if best_score >= MIN_DENSITY_THRESHOLD else "unknown",
        scores=scores,
        word_count=word_count,
    )

    if best_score >= MIN_DENSITY_THRESHOLD:
        return best_type

    return "unknown"


def get_extractor(schema_type: str) -> BaseSchemaExtractor | None:
    """Get the appropriate extractor for a schema type.

    Args:
        schema_type: The detected schema type.

    Returns:
        The extractor instance, or None if schema is unknown.
    """
    extractors: dict[str, BaseSchemaExtractor] = {
        "bank_statement": BankStatementExtractor(),
        "custody_statement": CustodyStatementExtractor(),
        "swift_confirm": SwiftConfirmExtractor(),
    }
    return extractors.get(schema_type)


def route_and_extract(
    doc: AssembledDocument,
    schema_type_hint: str | None = None,
) -> tuple[str, dict]:
    """Route to the appropriate extractor and extract fields.

    If schema_type_hint is provided, uses it directly. Otherwise,
    detects the schema from structural signals.

    Args:
        doc: The assembled document.
        schema_type_hint: Optional pre-determined schema type.

    Returns:
        Tuple of (schema_type, extraction_result_dict).
        If schema is unknown, returns an abstention result.
    """
    # Determine schema type
    if schema_type_hint and schema_type_hint != "unknown":
        schema_type = schema_type_hint
    else:
        schema_type = detect_schema(doc)

    # Handle unknown schema
    if schema_type == "unknown":
        abstention = Abstention(
            field=None,
            table_id=None,
            reason=ErrorCode.EXTRACTION_SCHEMA_UNKNOWN,
            detail="Document structural signals do not match any known schema",
            vlm_attempted=False,
        )
        return "unknown", {
            "fields": {},
            "tables": [],
            "abstentions": [abstention],
        }

    # Get extractor and run
    extractor = get_extractor(schema_type)
    if extractor is None:
        abstention = Abstention(
            field=None,
            table_id=None,
            reason=ErrorCode.EXTRACTION_SCHEMA_UNKNOWN,
            detail=f"No extractor available for schema type '{schema_type}'",
            vlm_attempted=False,
        )
        return "unknown", {
            "fields": {},
            "tables": [],
            "abstentions": [abstention],
        }

    result = extractor.extract(doc)
    return schema_type, result


# ─── Private Helpers ──────────────────────────────────────────────────────────


def _build_full_text(doc: AssembledDocument) -> str:
    """Build full text content from the assembled document."""
    parts: list[str] = []

    # From text blocks
    for block in doc.blocks:
        text = block.get("text", "")
        if text:
            parts.append(str(text))

    # From token stream if blocks are empty
    if not parts and doc.token_stream:
        parts = [token.text for token in doc.token_stream]

    return " ".join(parts)


def _compute_keyword_score(
    text: str, keywords: list[str], word_count: int
) -> float:
    """Compute keyword density score for a set of keywords.

    Returns the fraction of keywords found in the text, weighted by
    occurrence count relative to document length.
    """
    if not text or word_count == 0:
        return 0.0

    matches = 0
    for keyword in keywords:
        if keyword in text:
            # Count occurrences
            count = text.count(keyword)
            matches += min(count, 3)  # Cap at 3 to avoid single-keyword dominance

    # Normalise by keyword list size and word count
    return matches / (len(keywords) * max(word_count / 100, 1))


def _has_swift_structure(text: str) -> bool:
    """Check for SWIFT message structural patterns.

    SWIFT messages have distinctive block markers like {1:, {2:, {4:
    and field tags like :20:, :98A:, :35B:, etc.
    """
    swift_markers = ["{1:", "{4:", ":20:", ":16R:"]
    found = sum(1 for marker in swift_markers if marker in text)
    return found >= 2
