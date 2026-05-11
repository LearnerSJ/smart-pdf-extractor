"""Immediate self-retry with diagnostic VLM call.

When extraction produces >50% abstentions, makes a diagnostic call to understand
why, then retries with an adjusted strategy.
"""

from __future__ import annotations

import asyncio
import json

import structlog

from api.errors import ErrorCode
from api.models.response import Abstention, Field
from pipeline.models import AssembledDocument, VLMFieldResult
from pipeline.ports import VLMClientPort, RedactorPort
from pipeline.vlm.response_parser import strip_markdown_fences

logger = structlog.get_logger()

DIAGNOSTIC_PROMPT = '''You are diagnosing why a PDF extraction failed. The system tried to extract fields from a financial document but most fields returned null.

Document type detected: {schema_type}
Fields that failed (returned null): {failed_fields}
Fields that succeeded: {succeeded_fields}

First 3 pages of the document:
---
{sample_text}
---

Analyze why extraction failed and respond with JSON:
{{
  "diagnosis": "brief explanation of why fields couldn't be extracted",
  "correct_document_type": "what this document actually is (e.g., futures_trade_confirmation, visa_settlement_report, margin_call)",
  "correct_field_mapping": {{
    "original_field_name": "where_the_value_actually_is_in_this_document"
  }},
  "recommended_strategy": "auto_discovery | retry_with_correct_schema | extract_from_tables",
  "key_identifiers": ["list", "of", "keywords", "unique", "to", "this", "doc", "type"]
}}
'''


class DiagnosticRetry:
    """Diagnoses extraction failures and retries with adjusted strategy."""

    def __init__(self, vlm_client: VLMClientPort) -> None:
        self._vlm = vlm_client

    async def should_retry(
        self,
        fields: dict[str, Field],
        abstentions: list[Abstention],
        schema_type: str,
    ) -> bool:
        """Check if extraction quality is poor enough to warrant a retry."""
        total_attempted = len(fields) + len([a for a in abstentions if a.field])
        if total_attempted == 0:
            return False
        abstention_rate = len([a for a in abstentions if a.field]) / total_attempted
        return abstention_rate > 0.5

    async def diagnose(
        self,
        sample_text: str,
        schema_type: str,
        fields: dict[str, Field],
        abstentions: list[Abstention],
        trace_id: str,
    ) -> dict:
        """Make a diagnostic VLM call to understand why extraction failed.
        
        Returns a diagnosis dict with recommended_strategy and correct_document_type.
        """
        failed_fields = [a.field for a in abstentions if a.field]
        succeeded_fields = list(fields.keys())

        prompt = DIAGNOSTIC_PROMPT.format(
            schema_type=schema_type,
            failed_fields=", ".join(failed_fields),
            succeeded_fields=", ".join(succeeded_fields) or "none",
            sample_text=sample_text[:8000],
        )

        logger.info(
            "self_healing.diagnostic_triggered",
            trace_id=trace_id,
            schema_type=schema_type,
            failed_count=len(failed_fields),
            succeeded_count=len(succeeded_fields),
        )

        vlm_result: VLMFieldResult = await asyncio.to_thread(
            self._vlm.extract_field,
            prompt,
            "diagnostic",
            "Diagnose extraction failure",
            "diagnostic",
        )

        if vlm_result.value is None:
            logger.warning("self_healing.diagnostic_null", trace_id=trace_id)
            return {"recommended_strategy": "none", "diagnosis": "VLM returned null"}

        try:
            cleaned = strip_markdown_fences(vlm_result.value)
            diagnosis = json.loads(cleaned)
            logger.info(
                "self_healing.diagnosis_complete",
                trace_id=trace_id,
                recommended_strategy=diagnosis.get("recommended_strategy"),
                correct_document_type=diagnosis.get("correct_document_type"),
            )
            return diagnosis
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("self_healing.diagnostic_parse_error", error=str(e))
            return {"recommended_strategy": "auto_discovery", "diagnosis": str(e)}

    def get_retry_strategy(self, diagnosis: dict) -> str:
        """Determine the retry strategy from the diagnosis."""
        return diagnosis.get("recommended_strategy", "auto_discovery")
