"""Admin usage query routes.

Provides endpoints for querying VLM token usage data with filtering,
aggregation, cost computation, and time-series bucketing.

NOTE: For the demo/MVP, uses an in-memory store of usage records.
In production, these would query the vlm_usage table via SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.config import get_settings
from api.middleware.rbac import Permission, require_permission
from api.models.response import APIResponse, ResponseMeta

router = APIRouter()
logger = structlog.get_logger()


# ─── Response Models ──────────────────────────────────────────────────────────


class UsageRecord(BaseModel):
    """A single VLM usage record."""

    id: str
    tenant_id: str
    job_id: str
    model_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost: float
    timestamp: str  # ISO 8601


class PaginationInfo(BaseModel):
    """Pagination metadata."""

    page: int
    page_size: int
    total: int


class UsageListData(BaseModel):
    """Paginated list of usage records."""

    data: list[UsageRecord]
    pagination: PaginationInfo


class ModelUsageBreakdown(BaseModel):
    """Usage breakdown for a single model."""

    model_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost: float


class UsageSummaryData(BaseModel):
    """Aggregated usage summary."""

    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    estimated_cost: float
    by_model: list[ModelUsageBreakdown]


class TimeseriesBucket(BaseModel):
    """A single time-series bucket."""

    period: str  # ISO 8601 date string for the bucket start
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost: float


class UsageTimeseriesData(BaseModel):
    """Time-series usage data."""

    buckets: list[TimeseriesBucket]


# ─── In-Memory Demo Store ─────────────────────────────────────────────────────

_USAGE_RECORDS: list[dict] = []


def _compute_cost(input_tokens: int, output_tokens: int) -> float:
    """Compute estimated cost based on token counts and configured rates.

    cost = input_tokens * cost_per_1k_input / 1000 + output_tokens * cost_per_1k_output / 1000
    """
    settings = get_settings()
    cost = (
        input_tokens * settings.token_cost_per_1k_input / 1000
        + output_tokens * settings.token_cost_per_1k_output / 1000
    )
    return round(cost, 6)


def _seed_demo_usage() -> None:
    """Seed demo usage records on module load for testing."""
    import random

    random.seed(42)

    tenants = ["tenant-1", "tenant-2", "tenant-3"]
    models = ["us.anthropic.claude-sonnet-4-6", "us.anthropic.claude-haiku-4", "us.amazon.nova-pro-v1:0"]
    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)

    for i in range(100):
        tenant_id = random.choice(tenants)
        model_id = random.choice(models)
        input_tokens = random.randint(500, 10000)
        output_tokens = random.randint(100, 5000)
        total_tokens = input_tokens + output_tokens
        timestamp = base_time + timedelta(days=random.randint(0, 89), hours=random.randint(0, 23))

        record = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "job_id": f"job-{uuid.uuid4().hex[:8]}",
            "model_id": model_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "estimated_cost": _compute_cost(input_tokens, output_tokens),
            "timestamp": timestamp.isoformat(),
        }
        _USAGE_RECORDS.append(record)

    # Sort by timestamp
    _USAGE_RECORDS.sort(key=lambda r: r["timestamp"])


# Seed on module load
_seed_demo_usage()


# ─── Filtering Helpers ────────────────────────────────────────────────────────


def _filter_records(
    tenant_id: str | None = None,
    job_id: str | None = None,
    model_id: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> list[dict]:
    """Filter usage records based on provided criteria."""
    results = _USAGE_RECORDS

    if tenant_id is not None:
        results = [r for r in results if r["tenant_id"] == tenant_id]

    if job_id is not None:
        results = [r for r in results if r["job_id"] == job_id]

    if model_id is not None:
        results = [r for r in results if r["model_id"] == model_id]

    if start_time is not None:
        start_dt = datetime.fromisoformat(start_time)
        results = [r for r in results if datetime.fromisoformat(r["timestamp"]) >= start_dt]

    if end_time is not None:
        end_dt = datetime.fromisoformat(end_time)
        results = [r for r in results if datetime.fromisoformat(r["timestamp"]) < end_dt]

    return results


def _get_bucket_key(timestamp: str, granularity: str) -> str:
    """Get the bucket key for a timestamp based on granularity.

    Returns the ISO date string for the start of the bucket period.
    """
    dt = datetime.fromisoformat(timestamp)

    if granularity == "day":
        return dt.strftime("%Y-%m-%d")
    elif granularity == "week":
        # ISO week: Monday-aligned
        start_of_week = dt - timedelta(days=dt.weekday())
        return start_of_week.strftime("%Y-%m-%d")
    elif granularity == "month":
        return dt.strftime("%Y-%m-01")
    else:
        return dt.strftime("%Y-%m-%d")


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/v1/admin/usage", status_code=200)
async def get_usage(
    tenant_id: str | None = Query(None, description="Filter by tenant ID"),
    job_id: str | None = Query(None, description="Filter by job ID"),
    model_id: str | None = Query(None, description="Filter by model ID"),
    start_time: str | None = Query(None, description="Start time (ISO 8601)"),
    end_time: str | None = Query(None, description="End time (ISO 8601)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Page size"),
    user: dict = Depends(require_permission(Permission.READ, tenant_id_param="tenant_id")),
) -> APIResponse[UsageListData]:
    """Get paginated list of VLM usage records with optional filters.

    Supports filtering by tenant_id, job_id, model_id, and time range.
    Results are paginated with configurable page size (default 50, max 200).
    """
    request_id = str(uuid.uuid4())

    filtered = _filter_records(
        tenant_id=tenant_id,
        job_id=job_id,
        model_id=model_id,
        start_time=start_time,
        end_time=end_time,
    )

    total = len(filtered)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_records = filtered[start_idx:end_idx]

    records = [UsageRecord(**r) for r in page_records]

    return APIResponse[UsageListData](
        data=UsageListData(
            data=records,
            pagination=PaginationInfo(
                page=page,
                page_size=page_size,
                total=total,
            ),
        ),
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )


@router.get("/v1/admin/usage/summary", status_code=200)
async def get_usage_summary(
    tenant_id: str | None = Query(None, description="Filter by tenant ID"),
    job_id: str | None = Query(None, description="Filter by job ID"),
    model_id: str | None = Query(None, description="Filter by model ID"),
    start_time: str | None = Query(None, description="Start time (ISO 8601)"),
    end_time: str | None = Query(None, description="End time (ISO 8601)"),
    user: dict = Depends(require_permission(Permission.READ, tenant_id_param="tenant_id")),
) -> APIResponse[UsageSummaryData]:
    """Get aggregated usage summary with cost computation.

    Returns total token counts and estimated cost, with a breakdown by model.
    """
    request_id = str(uuid.uuid4())

    filtered = _filter_records(
        tenant_id=tenant_id,
        job_id=job_id,
        model_id=model_id,
        start_time=start_time,
        end_time=end_time,
    )

    # Aggregate totals
    total_input = sum(r["input_tokens"] for r in filtered)
    total_output = sum(r["output_tokens"] for r in filtered)
    total_tokens = total_input + total_output
    total_cost = _compute_cost(total_input, total_output)

    # Aggregate by model
    model_aggregates: dict[str, dict] = {}
    for record in filtered:
        mid = record["model_id"]
        if mid not in model_aggregates:
            model_aggregates[mid] = {
                "model_id": mid,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        model_aggregates[mid]["input_tokens"] += record["input_tokens"]
        model_aggregates[mid]["output_tokens"] += record["output_tokens"]

    by_model = []
    for mid, agg in model_aggregates.items():
        inp = agg["input_tokens"]
        out = agg["output_tokens"]
        by_model.append(
            ModelUsageBreakdown(
                model_id=mid,
                input_tokens=inp,
                output_tokens=out,
                total_tokens=inp + out,
                estimated_cost=_compute_cost(inp, out),
            )
        )

    return APIResponse[UsageSummaryData](
        data=UsageSummaryData(
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_tokens=total_tokens,
            estimated_cost=total_cost,
            by_model=by_model,
        ),
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )


@router.get("/v1/admin/usage/timeseries", status_code=200)
async def get_usage_timeseries(
    tenant_id: str | None = Query(None, description="Filter by tenant ID"),
    job_id: str | None = Query(None, description="Filter by job ID"),
    model_id: str | None = Query(None, description="Filter by model ID"),
    start_time: str | None = Query(None, description="Start time (ISO 8601)"),
    end_time: str | None = Query(None, description="End time (ISO 8601)"),
    granularity: Literal["day", "week", "month"] = Query("day", description="Time bucket granularity"),
    user: dict = Depends(require_permission(Permission.READ, tenant_id_param="tenant_id")),
) -> APIResponse[UsageTimeseriesData]:
    """Get bucketed time-series usage data.

    Groups usage records into time buckets based on the specified granularity
    (day, week, or month) and returns aggregated token counts and cost per bucket.
    """
    request_id = str(uuid.uuid4())

    filtered = _filter_records(
        tenant_id=tenant_id,
        job_id=job_id,
        model_id=model_id,
        start_time=start_time,
        end_time=end_time,
    )

    # Group by bucket
    bucket_aggregates: dict[str, dict] = {}
    for record in filtered:
        bucket_key = _get_bucket_key(record["timestamp"], granularity)
        if bucket_key not in bucket_aggregates:
            bucket_aggregates[bucket_key] = {
                "period": bucket_key,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        bucket_aggregates[bucket_key]["input_tokens"] += record["input_tokens"]
        bucket_aggregates[bucket_key]["output_tokens"] += record["output_tokens"]

    # Build sorted buckets
    buckets = []
    for key in sorted(bucket_aggregates.keys()):
        agg = bucket_aggregates[key]
        inp = agg["input_tokens"]
        out = agg["output_tokens"]
        buckets.append(
            TimeseriesBucket(
                period=agg["period"],
                input_tokens=inp,
                output_tokens=out,
                total_tokens=inp + out,
                estimated_cost=_compute_cost(inp, out),
            )
        )

    return APIResponse[UsageTimeseriesData](
        data=UsageTimeseriesData(buckets=buckets),
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )
