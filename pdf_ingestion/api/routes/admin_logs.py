"""Admin log query routes.

Provides endpoints for querying structured log entries with filtering,
severity-level filtering, trace correlation, and pagination.

NOTE: For the demo/MVP, uses the in-memory log store from log_sink.
In production, these would query the structured_logs table via SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.middleware.log_sink import get_logs
from api.middleware.rbac import Permission, require_permission
from api.models.response import APIResponse, ResponseMeta

router = APIRouter()
logger = structlog.get_logger()

# Severity level ordering for validation
_SEVERITY_LEVELS = ("debug", "info", "warning", "error", "critical")


# ─── Response Models ──────────────────────────────────────────────────────────


class LogEntry(BaseModel):
    """A single structured log entry."""

    id: int
    timestamp: str  # ISO 8601
    severity: str
    event_name: str
    tenant_id: str | None = None
    job_id: str | None = None
    trace_id: str | None = None
    message: str | None = None
    fields: dict | None = None


class PaginationInfo(BaseModel):
    """Pagination metadata."""

    page: int
    page_size: int
    total: int
    total_pages: int


class LogListData(BaseModel):
    """Paginated list of log entries."""

    entries: list[LogEntry]
    pagination: PaginationInfo


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/v1/admin/logs", status_code=200)
async def get_admin_logs(
    tenant_id: str | None = Query(None, description="Filter by tenant ID"),
    job_id: str | None = Query(None, description="Filter by job ID"),
    trace_id: str | None = Query(None, description="Filter by trace ID"),
    severity: str | None = Query(None, description="Minimum severity level (debug, info, warning, error, critical)"),
    start_time: str | None = Query(None, description="Start time (ISO 8601, inclusive)"),
    end_time: str | None = Query(None, description="End time (ISO 8601, exclusive)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Page size (max 200)"),
    user: dict = Depends(require_permission(Permission.READ, tenant_id_param="tenant_id")),
) -> APIResponse[LogListData]:
    """Get paginated list of structured log entries with optional filters.

    Supports filtering by tenant_id, job_id, trace_id, severity level,
    and time range. Results are returned in chronological order with
    configurable pagination (default page_size=50, max 200).

    Severity filtering returns entries at or above the specified level:
    debug < info < warning < error < critical.
    """
    request_id = str(uuid.uuid4())

    # Validate severity if provided
    if severity is not None and severity.lower() not in _SEVERITY_LEVELS:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422,
            detail=f"Invalid severity level: '{severity}'. Must be one of: {', '.join(_SEVERITY_LEVELS)}",
        )

    # Query logs using the log_sink helper
    result = get_logs(
        tenant_id=tenant_id,
        job_id=job_id,
        trace_id=trace_id,
        severity=severity,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )

    entries = [LogEntry(**entry) for entry in result["data"]]
    pagination = PaginationInfo(**result["pagination"])

    return APIResponse[LogListData](
        data=LogListData(
            entries=entries,
            pagination=pagination,
        ),
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )


@router.get("/v1/admin/logs/trace/{trace_id}", status_code=200)
async def get_logs_by_trace(
    trace_id: str,
    user: dict = Depends(require_permission(Permission.READ)),
) -> APIResponse[LogListData]:
    """Get all log entries for a specific trace in chronological order.

    Returns all log entries sharing the given trace_id, ordered by timestamp.
    No pagination is applied — all entries for the trace are returned.
    """
    request_id = str(uuid.uuid4())

    # Query all logs for this trace (use large page_size to get all)
    result = get_logs(
        trace_id=trace_id,
        page=1,
        page_size=200,
    )

    # If there are more than 200 entries, fetch remaining pages
    all_entries = list(result["data"])
    total = result["pagination"]["total"]

    if total > 200:
        pages_needed = (total + 199) // 200
        for p in range(2, pages_needed + 1):
            more = get_logs(trace_id=trace_id, page=p, page_size=200)
            all_entries.extend(more["data"])

    entries = [LogEntry(**entry) for entry in all_entries]
    pagination = PaginationInfo(
        page=1,
        page_size=total if total > 0 else 200,
        total=total,
        total_pages=1,
    )

    return APIResponse[LogListData](
        data=LogListData(
            entries=entries,
            pagination=pagination,
        ),
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )
