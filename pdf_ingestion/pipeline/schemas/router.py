"""Schema router.

Detects document schema type based on structural signals and routes
to the appropriate extractor. Uses keyword density and structural
patterns — no LLM involved.

When schema is unknown and VLM is enabled, delegates to AutoSchemaDiscovery
for dynamic schema detection and extraction.
"""

from __future__ import annotations

import structlog

from api.errors import ErrorCode
from api.models.response import Abstention
from api.models.tenant import TenantContext
from pipeline.models import AssembledDocument
from pipeline.ports import VLMClientPort, RedactorPort
from pipeline.schemas.bank_statement import BankStatementExtractor
from pipeline.schemas.base import BaseSchemaExtractor
from pipeline.schemas.custody_statement import CustodyStatementExtractor
from pipeline.schemas.swift_confirm import SwiftConfirmExtractor
from pipeline.vlm.token_budget import TokenBudget

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
    """Route to the appropriate extractor and extract fields (sync path).

    If schema_type_hint is provided, uses it directly. Otherwise,
    detects the schema from structural signals.

    This is the synchronous version that does not support auto-discovery.
    Use route_and_extract_async for discovery support.

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


async def route_and_extract_async(
    doc: AssembledDocument,
    schema_type_hint: str | None = None,
    tenant: TenantContext | None = None,
    vlm_client: VLMClientPort | None = None,
    redactor: RedactorPort | None = None,
    schema_cache: "SchemaCache | None" = None,
    token_budget: TokenBudget | None = None,
    trace_id: str = "",
) -> tuple[str, dict]:
    """Route to the appropriate extractor and extract fields.

    Modified to support auto-schema discovery when schema is unknown
    and tenant has VLM enabled.

    Args:
        doc: The assembled document.
        schema_type_hint: Optional pre-determined schema type.
        tenant: Tenant context (needed for discovery).
        vlm_client: VLM client port (needed for discovery).
        redactor: Redactor port (needed for discovery).
        schema_cache: Schema cache instance (needed for discovery).
        token_budget: Token budget tracker (needed for discovery).
        trace_id: Request trace ID for logging.

    Returns:
        Tuple of (schema_type, extraction_result_dict).
        If schema is unknown, returns an abstention result.
    """
    from pipeline.discovery.auto_discovery import AutoSchemaDiscovery
    from pipeline.discovery.dynamic_extractor import DynamicExtractor
    from pipeline.discovery.schema_cache import SchemaCache
    from pipeline.models import DiscoveredSchema

    # Determine schema type
    if schema_type_hint and schema_type_hint != "unknown":
        schema_type = schema_type_hint
    else:
        schema_type = detect_schema(doc)

    # Handle unknown schema — try auto-discovery if VLM enabled
    if schema_type == "unknown":
        if tenant and tenant.vlm_enabled and vlm_client and redactor and schema_cache and token_budget:
            discovery = AutoSchemaDiscovery(vlm_client, redactor, schema_cache)
            result = await discovery.discover(doc, tenant, token_budget, trace_id)

            if isinstance(result, Abstention):
                return "unknown", {
                    "fields": {},
                    "tables": [],
                    "abstentions": [result],
                }

            # Discovery succeeded — extract using discovered schema
            extractor = DynamicExtractor(vlm_client, redactor)
            extraction_result = await extractor.extract(
                doc, result, tenant, token_budget, trace_id
            )
            return extraction_result.get("schema_type", f"discovered:{result.document_type_label}"), extraction_result

        # VLM not available — fall back to standard abstention
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

    # Known schema — use static extractor (unchanged)
    extractor_instance = get_extractor(schema_type)
    if extractor_instance is None:
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

    result = extractor_instance.extract(doc)
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
