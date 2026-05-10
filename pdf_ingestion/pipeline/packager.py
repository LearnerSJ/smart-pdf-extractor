"""Result packager.

Assembles the FinalOutput with confidence summary, pipeline version,
and all metadata from the extraction and validation stages.
"""

from __future__ import annotations

from api.models.response import (
    Abstention,
    ConfidenceSummary,
    Field,
    FinalOutput,
    Table,
)
from pipeline.validator import ValidationReport

# Pipeline version — updated on each release
PIPELINE_VERSION = "0.1.0"


def package_result(
    doc_id: str,
    schema_type: str,
    fields: dict[str, Field],
    tables: list[Table],
    abstentions: list[Abstention],
    validation: ValidationReport,
    pages_digital: int = 0,
    pages_scanned: int = 0,
) -> FinalOutput:
    """Assemble the final extraction output.

    Computes confidence summary from extracted fields, determines
    overall status, and packages everything into a FinalOutput.

    Args:
        doc_id: Document identifier (sha256:...).
        schema_type: Detected schema type.
        fields: Extracted fields dict.
        tables: Extracted tables list.
        abstentions: List of abstentions.
        validation: Validation report from run_validators().
        pages_digital: Number of digital pages.
        pages_scanned: Number of scanned pages.

    Returns:
        Complete FinalOutput ready for persistence and delivery.
    """
    # Compute confidence summary
    confidence_summary = _compute_confidence_summary(
        fields=fields,
        abstentions=abstentions,
        tables=tables,
        pages_digital=pages_digital,
        pages_scanned=pages_scanned,
    )

    # Determine status
    status = _determine_status(fields, abstentions, validation)

    return FinalOutput(
        doc_id=doc_id,
        schema_type=schema_type,
        status=status,
        fields=fields,
        tables=tables,
        abstentions=abstentions,
        confidence_summary=confidence_summary,
        pipeline_version=PIPELINE_VERSION,
    )


def _compute_confidence_summary(
    fields: dict[str, Field],
    abstentions: list[Abstention],
    tables: list[Table],
    pages_digital: int,
    pages_scanned: int,
) -> ConfidenceSummary:
    """Compute confidence summary from extraction results.

    Calculates mean and min confidence across all extracted fields,
    counts VLM usage, and summarises page classifications.
    """
    confidences = [f.confidence for f in fields.values()]
    vlm_count = sum(1 for f in fields.values() if f.vlm_used)
    tables_hard_flagged = sum(
        1 for t in tables if t.triangulation.verdict == "hard_flag"
    )

    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    min_conf = min(confidences) if confidences else 0.0

    return ConfidenceSummary(
        mean_confidence=round(mean_conf, 4),
        min_confidence=round(min_conf, 4),
        fields_extracted=len(fields),
        fields_abstained=len([a for a in abstentions if a.field is not None]),
        vlm_used_count=vlm_count,
    )


def _determine_status(
    fields: dict[str, Field],
    abstentions: list[Abstention],
    validation: ValidationReport,
) -> str:
    """Determine the overall extraction status.

    - "complete": meaningful data extracted (accounts with tables/transactions)
    - "partial": some data extracted but significant abstentions remain
    - "failed": no useful data extracted at all
    """
    if not fields:
        return "failed"

    # If we have accounts with actual data (tables or transactions), that's success
    accounts_field = fields.get("accounts")
    if accounts_field and accounts_field.value:
        accounts = accounts_field.value if isinstance(accounts_field.value, list) else []
        has_data = any(
            isinstance(a, dict) and (a.get("tables") or a.get("transactions"))
            for a in accounts
        )
        if has_data:
            return "complete"

    # If we have multiple fields extracted and few abstentions, it's complete
    field_abstentions = [a for a in abstentions if a.field is not None]
    if len(fields) >= 3 and len(field_abstentions) <= 2:
        return "complete"

    if field_abstentions:
        return "partial"

    return "complete"
