"""Presidio-based PII redactor — concrete implementation of RedactorPort.

Supports per-tenant global config and per-schema overrides.
Replaces detected PII with "[REDACTED]". Never mutates original text.
"""

from __future__ import annotations

from typing import Any

import structlog
from presidio_analyzer import AnalyzerEngine  # type: ignore[import-untyped]
from presidio_anonymizer import AnonymizerEngine  # type: ignore[import-untyped]
from presidio_anonymizer.entities import OperatorConfig  # type: ignore[import-untyped]

from pipeline.models import EntityRedactionConfig, RedactionLog
from pipeline.ports import RedactorPort

logger = structlog.get_logger()


class PageRedactor(RedactorPort):
    """Concrete Presidio-based redactor implementing RedactorPort.

    Supports per-tenant global config and per-schema overrides.
    Replaces detected PII entities with "[REDACTED]".
    Produces a RedactionLog with positions, types, and config_snapshot.
    Never mutates the original text.
    """

    def __init__(self) -> None:
        """Initialize Presidio analyzer and anonymizer engines."""
        self._analyzer = AnalyzerEngine()
        self._anonymizer = AnonymizerEngine()

    def redact_page_text(
        self,
        text: str,
        config: list[EntityRedactionConfig],
    ) -> tuple[str, RedactionLog]:
        """Redact PII from text according to the provided configuration.

        Args:
            text: The original text to redact. Never mutated.
            config: List of entity redaction configurations.

        Returns:
            Tuple of (redacted_text, redaction_log).
            If no entities are enabled, returns original text unchanged.
        """
        # Determine which entities to redact
        entities_to_redact = [e.entity_type for e in config if e.enabled]

        # If no entities enabled, return original text unchanged
        if not entities_to_redact:
            return text, RedactionLog(
                entities_redacted=[],
                redacted_count=0,
                config_snapshot=[{"entity_type": e.entity_type, "enabled": e.enabled} for e in config],
            )

        # Analyze text for PII entities
        try:
            results = self._analyzer.analyze(
                text=text,
                language="en",
                entities=entities_to_redact,
            )
        except Exception as e:
            logger.warning("redactor.analysis_failed", error=str(e))
            return text, RedactionLog(
                entities_redacted=[],
                redacted_count=0,
                config_snapshot=[{"entity_type": et, "enabled": True} for et in entities_to_redact],
            )

        if not results:
            return text, RedactionLog(
                entities_redacted=[],
                redacted_count=0,
                config_snapshot=[{"entity_type": et, "enabled": True} for et in entities_to_redact],
            )

        # Anonymize — replace all detected entities with "[REDACTED]"
        try:
            anonymized = self._anonymizer.anonymize(
                text=text,
                analyzer_results=results,
                operators={"DEFAULT": OperatorConfig("replace", {"new_value": "[REDACTED]"})},
            )
            redacted_text = anonymized.text
        except Exception as e:
            logger.warning("redactor.anonymization_failed", error=str(e))
            return text, RedactionLog(
                entities_redacted=[],
                redacted_count=0,
                config_snapshot=[{"entity_type": et, "enabled": True} for et in entities_to_redact],
            )

        # Build redaction log
        entities_redacted: list[dict[str, object]] = [
            {
                "entity_type": r.entity_type,
                "start": r.start,
                "end": r.end,
                "score": r.score,
            }
            for r in results
        ]

        config_snapshot: list[dict[str, object]] = [
            {"entity_type": et, "enabled": True} for et in entities_to_redact
        ]

        redaction_log = RedactionLog(
            entities_redacted=entities_redacted,
            redacted_count=len(results),
            config_snapshot=config_snapshot,
        )

        logger.info(
            "redactor.applied",
            entities_redacted_count=len(results),
            entity_types=entities_to_redact,
        )

        return redacted_text, redaction_log

    def redact_with_schema_override(
        self,
        text: str,
        global_config: list[EntityRedactionConfig],
        schema_overrides: dict[str, list[EntityRedactionConfig]],
        schema_type: str | None = None,
    ) -> tuple[str, RedactionLog]:
        """Redact with per-schema override support.

        If schema_type has an override, use that config.
        Otherwise, fall back to global config.

        Args:
            text: The original text to redact.
            global_config: Global entity redaction config.
            schema_overrides: Per-schema override configs.
            schema_type: The document schema type.

        Returns:
            Tuple of (redacted_text, redaction_log).
        """
        config = global_config
        if schema_type and schema_type in schema_overrides:
            config = schema_overrides[schema_type]

        return self.redact_page_text(text, config)
