"""VLM usage event emission for cost attribution and monitoring.

Emits structured log events per LLM call and per job for downstream
consumption by monitoring dashboards and cost allocation systems.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import structlog

logger = structlog.get_logger()


@dataclass
class VLMUsageEvent:
    """Structured usage event emitted per LLM call.

    Contains token consumption, model metadata, and cost attribution
    fields for downstream monitoring.
    """

    tenant_id: str
    job_id: str
    schema_type: str
    model_id: str
    input_tokens: int
    output_tokens: int
    tier: str  # "single", "tier1", "tier2", "tier3"
    window_index: int | None = None
    window_start_page: int | None = None
    window_end_page: int | None = None
    target_fields: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class VLMJobUsageSummary:
    """Aggregate usage summary emitted at job completion.

    Provides total token consumption, tier used, and budget status
    for the entire extraction job.
    """

    tenant_id: str
    job_id: str
    schema_type: str
    model_id: str
    tier: str
    total_input_tokens: int
    total_output_tokens: int
    total_calls: int
    budget_max_tokens: int
    budget_exceeded: bool
    budget_action: str  # "flag", "skip", "proceed"
    pages_processed: int = 0
    windows_processed: int = 0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


def emit_window_usage(event: VLMUsageEvent) -> None:
    """Emit a structured log event for a single LLM call.

    Logs at info level with all cost attribution metadata for
    downstream aggregation and monitoring.
    """
    logger.info(
        "vlm.window_usage",
        tenant_id=event.tenant_id,
        job_id=event.job_id,
        schema_type=event.schema_type,
        model_id=event.model_id,
        input_tokens=event.input_tokens,
        output_tokens=event.output_tokens,
        tier=event.tier,
        window_index=event.window_index,
        window_start_page=event.window_start_page,
        window_end_page=event.window_end_page,
        target_fields=event.target_fields,
        timestamp=event.timestamp,
    )


def emit_job_usage_summary(summary: VLMJobUsageSummary) -> None:
    """Emit an aggregate structured log event at job completion.

    Summarises total token consumption, tier used, and budget status
    for the entire extraction job.
    """
    logger.info(
        "vlm.job_usage_summary",
        tenant_id=summary.tenant_id,
        job_id=summary.job_id,
        schema_type=summary.schema_type,
        model_id=summary.model_id,
        tier=summary.tier,
        total_input_tokens=summary.total_input_tokens,
        total_output_tokens=summary.total_output_tokens,
        total_calls=summary.total_calls,
        budget_max_tokens=summary.budget_max_tokens,
        budget_exceeded=summary.budget_exceeded,
        budget_action=summary.budget_action,
        pages_processed=summary.pages_processed,
        windows_processed=summary.windows_processed,
        timestamp=summary.timestamp,
    )
