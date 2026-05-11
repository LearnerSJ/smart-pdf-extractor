"""Schema learning — tracks success rates and triggers refinement.

Monitors extraction quality per cached schema and automatically refines
schemas that perform poorly over multiple jobs.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog

from pipeline.discovery.schema_cache import SchemaCache
from pipeline.models import DiscoveredSchema, SchemaFingerprint
from pipeline.ports import VLMClientPort
from pipeline.vlm.response_parser import strip_markdown_fences

logger = structlog.get_logger()

REFINEMENT_PROMPT = '''You are improving a document extraction schema that has been performing poorly.

Current schema definition:
- Document type: {document_type_label}
- Institution: {institution}
- Fields: {field_definitions}
- Tables: {table_definitions}

Performance data:
- Success rate: {success_rate}% over {total_uses} documents
- Fields that commonly fail: {common_failures}

Example failure (document sample where extraction failed):
---
{failure_sample}
---

Produce an IMPROVED schema that would extract these documents correctly.
Respond with JSON matching the same schema structure but with corrected/additional field definitions:
{{
  "document_type_label": "string",
  "institution": "string",
  "metadata_fields": [
    {{"field_name": "string", "description": "string", "location_hint": "string"}}
  ],
  "table_definitions": [
    {{"table_type": "string", "expected_headers": ["string"], "data_pattern": "string", "location_hint": "string"}}
  ]
}}
'''

MIN_USES_BEFORE_REFINEMENT = 5
REFINEMENT_THRESHOLD = 0.70  # Refine if success rate drops below 70%
STABLE_THRESHOLD = 0.95  # Mark as stable if success rate exceeds 95%
STABLE_MIN_USES = 10


@dataclass
class SchemaPerformance:
    """Tracks extraction performance for a cached schema."""
    fingerprint_key: str
    total_uses: int = 0
    successful_extractions: int = 0
    failure_samples: list[dict] = field(default_factory=list)  # Last 3 failures
    common_failure_fields: dict[str, int] = field(default_factory=dict)
    last_refined_at: datetime | None = None
    is_stable: bool = False

    @property
    def success_rate(self) -> float:
        if self.total_uses == 0:
            return 0.0
        return self.successful_extractions / self.total_uses

    def record_result(self, fields_extracted: int, fields_abstained: int, sample_text: str = "") -> None:
        """Record an extraction result for this schema."""
        self.total_uses += 1
        total = fields_extracted + fields_abstained
        if total > 0 and fields_extracted / total >= 0.5:
            self.successful_extractions += 1
        else:
            # Record failure sample (keep last 3)
            if sample_text and len(self.failure_samples) < 3:
                self.failure_samples.append({
                    "sample": sample_text[:2000],
                    "fields_extracted": fields_extracted,
                    "fields_abstained": fields_abstained,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

    def needs_refinement(self) -> bool:
        """Check if this schema should be refined."""
        if self.is_stable:
            return False
        if self.total_uses < MIN_USES_BEFORE_REFINEMENT:
            return False
        return self.success_rate < REFINEMENT_THRESHOLD

    def is_now_stable(self) -> bool:
        """Check if this schema has proven itself stable."""
        return (
            self.total_uses >= STABLE_MIN_USES
            and self.success_rate >= STABLE_THRESHOLD
        )


class SchemaLearner:
    """Tracks schema performance and triggers refinement when needed."""

    def __init__(self, schema_cache: SchemaCache, vlm_client: VLMClientPort) -> None:
        self._cache = schema_cache
        self._vlm = vlm_client
        self._performance: dict[str, SchemaPerformance] = {}

    def record_extraction_result(
        self,
        fingerprint: SchemaFingerprint,
        fields_extracted: int,
        fields_abstained: int,
        sample_text: str = "",
    ) -> None:
        """Record an extraction result for performance tracking."""
        key = fingerprint.key
        if key not in self._performance:
            self._performance[key] = SchemaPerformance(fingerprint_key=key)

        perf = self._performance[key]
        perf.record_result(fields_extracted, fields_abstained, sample_text)

        # Check if schema is now stable
        if perf.is_now_stable() and not perf.is_stable:
            perf.is_stable = True
            logger.info(
                "schema_learner.schema_stable",
                fingerprint=key,
                success_rate=perf.success_rate,
                total_uses=perf.total_uses,
            )

    async def check_and_refine(
        self,
        fingerprint: SchemaFingerprint,
        tenant_id: str,
        trace_id: str,
    ) -> DiscoveredSchema | None:
        """Check if a schema needs refinement and refine it if so.
        
        Returns the refined schema if refinement was performed, None otherwise.
        """
        key = fingerprint.key
        perf = self._performance.get(key)
        if perf is None or not perf.needs_refinement():
            return None

        # Get current schema from cache
        current_schema = await self._cache.lookup(fingerprint, tenant_id)
        if current_schema is None:
            return None

        logger.info(
            "schema_learner.refinement_triggered",
            fingerprint=key,
            success_rate=perf.success_rate,
            total_uses=perf.total_uses,
            trace_id=trace_id,
        )

        # Build refinement prompt
        failure_sample = perf.failure_samples[0]["sample"] if perf.failure_samples else ""
        common_failures = sorted(
            perf.common_failure_fields.items(), key=lambda x: x[1], reverse=True
        )[:5]

        prompt = REFINEMENT_PROMPT.format(
            document_type_label=current_schema.document_type_label,
            institution=current_schema.institution,
            field_definitions=json.dumps([
                {"field_name": f.field_name, "description": f.description, "location_hint": f.location_hint}
                for f in current_schema.metadata_fields
            ]),
            table_definitions=json.dumps([
                {"table_type": t.table_type, "expected_headers": t.expected_headers}
                for t in current_schema.table_definitions
            ]),
            success_rate=int(perf.success_rate * 100),
            total_uses=perf.total_uses,
            common_failures=", ".join(f"{k} ({v} failures)" for k, v in common_failures),
            failure_sample=failure_sample,
        )

        vlm_result = await asyncio.to_thread(
            self._vlm.extract_field,
            prompt,
            "schema_refinement",
            "Refine discovered schema",
            "refinement",
        )

        if vlm_result.value is None:
            logger.warning("schema_learner.refinement_null", fingerprint=key)
            return None

        try:
            cleaned = strip_markdown_fences(vlm_result.value)
            data = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            logger.warning("schema_learner.refinement_parse_error", fingerprint=key)
            return None

        # Parse into DiscoveredSchema
        from pipeline.models import DiscoveredFieldDefinition, DiscoveredTableDefinition

        refined_schema = DiscoveredSchema(
            document_type_label=data.get("document_type_label", current_schema.document_type_label),
            institution=data.get("institution", current_schema.institution),
            metadata_fields=[
                DiscoveredFieldDefinition(
                    field_name=f["field_name"],
                    description=f.get("description", ""),
                    location_hint=f.get("location_hint", ""),
                )
                for f in data.get("metadata_fields", [])
                if isinstance(f, dict) and f.get("field_name")
            ],
            table_definitions=[
                DiscoveredTableDefinition(
                    table_type=t["table_type"],
                    expected_headers=t.get("expected_headers", []),
                    data_pattern=t.get("data_pattern", ""),
                    location_hint=t.get("location_hint", ""),
                )
                for t in data.get("table_definitions", [])
                if isinstance(t, dict) and t.get("table_type")
            ],
        )

        # Store refined schema (overwrites old version)
        await self._cache.store(refined_schema, refined_schema.fingerprint, tenant_id)
        perf.last_refined_at = datetime.now(timezone.utc)
        perf.failure_samples.clear()  # Reset failure samples after refinement

        logger.info(
            "schema_learner.refinement_complete",
            fingerprint=key,
            new_fields=len(refined_schema.metadata_fields),
            new_tables=len(refined_schema.table_definitions),
            trace_id=trace_id,
        )

        return refined_schema

    def get_performance_summary(self) -> list[dict]:
        """Get performance summary for all tracked schemas (for admin dashboard)."""
        return [
            {
                "fingerprint": perf.fingerprint_key,
                "total_uses": perf.total_uses,
                "success_rate": round(perf.success_rate, 3),
                "is_stable": perf.is_stable,
                "needs_refinement": perf.needs_refinement(),
                "last_refined_at": perf.last_refined_at.isoformat() if perf.last_refined_at else None,
            }
            for perf in self._performance.values()
        ]
