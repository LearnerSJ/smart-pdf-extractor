"""Long-term pattern mining across all extraction failures.

Aggregates failure patterns and generates improvement suggestions.
Runs as a background task (hourly) analyzing structured logs.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger()


@dataclass
class FailureRecord:
    """A single extraction failure record."""
    job_id: str
    tenant_id: str
    schema_type: str
    institution: str | None
    error_code: str
    field_name: str | None
    document_characteristics: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ImprovementSuggestion:
    """A generated improvement suggestion."""
    category: str  # "schema_detection", "field_mapping", "extraction_strategy"
    priority: str  # "high", "medium", "low"
    description: str
    affected_count: int  # Number of jobs affected
    auto_applicable: bool  # Can be applied without human review
    suggested_action: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PatternMiner:
    """Aggregates failure patterns and generates improvement suggestions."""

    def __init__(self) -> None:
        self._failures: list[FailureRecord] = []
        self._suggestions: list[ImprovementSuggestion] = []
        self._running = False
        self._task: asyncio.Task | None = None

    def record_failure(
        self,
        job_id: str,
        tenant_id: str,
        schema_type: str,
        error_code: str,
        field_name: str | None = None,
        institution: str | None = None,
        document_characteristics: dict | None = None,
    ) -> None:
        """Record a failure for pattern analysis."""
        self._failures.append(FailureRecord(
            job_id=job_id,
            tenant_id=tenant_id,
            schema_type=schema_type,
            institution=institution,
            error_code=error_code,
            field_name=field_name,
            document_characteristics=document_characteristics or {},
        ))
        # Keep last 1000 failures
        if len(self._failures) > 1000:
            self._failures = self._failures[-1000:]

    async def start(self, interval_seconds: int = 3600) -> None:
        """Start the background pattern mining task."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop(interval_seconds))
        logger.info("pattern_miner.started", interval_seconds=interval_seconds)

    async def stop(self) -> None:
        """Stop the background task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("pattern_miner.stopped")

    async def _run_loop(self, interval: int) -> None:
        """Background loop that runs analysis periodically."""
        while self._running:
            try:
                await asyncio.sleep(interval)
                if self._failures:
                    self._analyze_patterns()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("pattern_miner.error", error=str(e))

    def _analyze_patterns(self) -> None:
        """Analyze accumulated failures and generate suggestions."""
        if len(self._failures) < 5:
            return

        # Pattern 1: Same field fails repeatedly for same institution
        field_by_institution: dict[tuple[str, str], int] = defaultdict(int)
        for f in self._failures:
            if f.field_name and f.institution:
                field_by_institution[(f.institution, f.field_name)] += 1

        for (institution, field_name), count in field_by_institution.items():
            if count >= 3:
                self._suggestions.append(ImprovementSuggestion(
                    category="field_mapping",
                    priority="high" if count >= 5 else "medium",
                    description=(
                        f"Field '{field_name}' fails {count} times for institution '{institution}'. "
                        f"The field likely has a different name or location in documents from this institution."
                    ),
                    affected_count=count,
                    auto_applicable=False,
                    suggested_action={
                        "type": "refine_schema",
                        "institution": institution,
                        "field_name": field_name,
                    },
                ))

        # Pattern 2: Schema detection misclassification
        schema_errors: dict[str, int] = defaultdict(int)
        for f in self._failures:
            if f.error_code in ("ERR_VLM_003", "ERR_EXTRACT_002"):
                schema_errors[f.schema_type] += 1

        for schema_type, count in schema_errors.items():
            if count >= 5:
                self._suggestions.append(ImprovementSuggestion(
                    category="schema_detection",
                    priority="high",
                    description=(
                        f"Schema '{schema_type}' has {count} VLM null/unknown failures. "
                        f"Documents may be misclassified — consider adding negative keywords or "
                        f"lowering the detection threshold."
                    ),
                    affected_count=count,
                    auto_applicable=True,
                    suggested_action={
                        "type": "adjust_schema_detection",
                        "schema_type": schema_type,
                        "failure_count": count,
                    },
                ))

        # Pattern 3: Error code concentration
        error_counts: dict[str, int] = defaultdict(int)
        for f in self._failures:
            error_counts[f.error_code] += 1

        for error_code, count in error_counts.items():
            if count >= 10:
                self._suggestions.append(ImprovementSuggestion(
                    category="extraction_strategy",
                    priority="high" if count >= 20 else "medium",
                    description=(
                        f"Error code '{error_code}' occurred {count} times. "
                        f"This indicates a systemic issue that may need architectural attention."
                    ),
                    affected_count=count,
                    auto_applicable=False,
                    suggested_action={
                        "type": "investigate_error_pattern",
                        "error_code": error_code,
                        "count": count,
                    },
                ))

        # Deduplicate suggestions
        seen = set()
        unique_suggestions = []
        for s in self._suggestions:
            key = (s.category, s.description[:50])
            if key not in seen:
                seen.add(key)
                unique_suggestions.append(s)
        self._suggestions = unique_suggestions[-50:]  # Keep last 50

        if self._suggestions:
            logger.info(
                "pattern_miner.analysis_complete",
                total_failures_analyzed=len(self._failures),
                suggestions_generated=len(self._suggestions),
            )

    def get_suggestions(self) -> list[dict]:
        """Get current improvement suggestions (for admin dashboard)."""
        return [
            {
                "category": s.category,
                "priority": s.priority,
                "description": s.description,
                "affected_count": s.affected_count,
                "auto_applicable": s.auto_applicable,
                "suggested_action": s.suggested_action,
                "created_at": s.created_at.isoformat(),
            }
            for s in self._suggestions
        ]

    def clear_failures(self) -> None:
        """Clear accumulated failures (after processing)."""
        self._failures.clear()
