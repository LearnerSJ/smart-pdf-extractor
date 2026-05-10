"""Structlog processor that persists log entries to an in-memory store.

For the demo/MVP, log entries are written to an in-memory list (_LOG_STORE)
instead of the actual PostgreSQL structured_logs table. The log query service
reads from this store.

The processor is safe to use in async context (non-blocking) and handles
errors gracefully — if the log sink fails, it does not break the logging
pipeline.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

# In-memory log store (simulates the structured_logs table for demo/MVP)
_LOG_STORE: list[dict[str, Any]] = []
_LOG_STORE_LOCK = threading.Lock()
_ID_COUNTER: int = 0

# Severity levels for validation/normalization
_VALID_SEVERITIES = {"debug", "info", "warning", "error", "critical"}

# Fields that are extracted into dedicated columns (not stored in 'fields' JSONB)
_EXTRACTED_FIELDS = {
    "event",
    "level",
    "timestamp",
    "tenant_id",
    "job_id",
    "trace_id",
    "message",
    "logger",
    "logger_name",
}


def _normalize_severity(level: str | None) -> str:
    """Normalize the log level to a valid severity string."""
    if level is None:
        return "info"
    level_lower = level.lower()
    if level_lower in _VALID_SEVERITIES:
        return level_lower
    # Map common aliases
    if level_lower in ("warn",):
        return "warning"
    if level_lower in ("fatal", "crit"):
        return "critical"
    if level_lower in ("err",):
        return "error"
    return "info"


def db_log_sink(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Structlog processor that persists log entries to the in-memory store.

    Extracts relevant fields from the event_dict and stores them in a
    structured format matching the structured_logs table schema. All
    remaining fields are stored in the 'fields' JSONB column.

    This processor returns the event_dict unchanged so that existing
    stdout output is preserved (dual output).

    Args:
        logger: The structlog logger instance.
        method_name: The name of the log method called (e.g., 'info', 'error').
        event_dict: The structured log event dictionary.

    Returns:
        The event_dict unchanged.
    """
    global _ID_COUNTER

    try:
        # Extract dedicated columns
        event_name = event_dict.get("event", "")
        severity = _normalize_severity(method_name or event_dict.get("level"))
        tenant_id = event_dict.get("tenant_id")
        job_id = event_dict.get("job_id")
        trace_id = event_dict.get("trace_id")
        message = event_dict.get("message")

        # If message is not set separately, use event as message
        if message is None and isinstance(event_name, str):
            message = event_name

        # Collect remaining fields (everything not in the extracted set)
        fields = {
            k: v
            for k, v in event_dict.items()
            if k not in _EXTRACTED_FIELDS and v is not None
        }

        # Build the log entry matching the structured_logs table schema
        with _LOG_STORE_LOCK:
            _ID_COUNTER += 1
            log_entry: dict[str, Any] = {
                "id": _ID_COUNTER,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "severity": severity,
                "event_name": str(event_name) if event_name else "",
                "tenant_id": str(tenant_id) if tenant_id is not None else None,
                "job_id": str(job_id) if job_id is not None else None,
                "trace_id": str(trace_id) if trace_id is not None else None,
                "message": str(message) if message is not None else None,
                "fields": fields if fields else None,
            }
            _LOG_STORE.append(log_entry)

    except Exception:
        # If the log sink fails, do not break the logging pipeline.
        # Silently swallow the error so downstream processors and
        # stdout output continue to work.
        pass

    return event_dict


def get_logs(
    *,
    tenant_id: str | None = None,
    job_id: str | None = None,
    trace_id: str | None = None,
    severity: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Retrieve stored logs with optional filtering and pagination.

    This helper function is used by the log query service to read from
    the in-memory store.

    Args:
        tenant_id: Filter by tenant ID.
        job_id: Filter by job ID.
        trace_id: Filter by trace ID.
        severity: Minimum severity level filter.
        start_time: ISO 8601 start time (inclusive).
        end_time: ISO 8601 end time (exclusive).
        page: Page number (1-indexed).
        page_size: Number of entries per page (max 200).

    Returns:
        Dictionary with 'data' (list of log entries) and 'pagination' metadata.
    """
    severity_order = {"debug": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}

    # Clamp page_size
    page_size = max(1, min(page_size, 200))
    page = max(1, page)

    with _LOG_STORE_LOCK:
        filtered = list(_LOG_STORE)

    # Apply filters
    if tenant_id is not None:
        filtered = [e for e in filtered if e["tenant_id"] == tenant_id]

    if job_id is not None:
        filtered = [e for e in filtered if e["job_id"] == job_id]

    if trace_id is not None:
        filtered = [e for e in filtered if e["trace_id"] == trace_id]

    if severity is not None:
        min_level = severity_order.get(severity.lower(), 0)
        filtered = [
            e for e in filtered
            if severity_order.get(e["severity"], 0) >= min_level
        ]

    if start_time is not None:
        filtered = [e for e in filtered if e["timestamp"] >= start_time]

    if end_time is not None:
        filtered = [e for e in filtered if e["timestamp"] < end_time]

    # Sort chronologically
    filtered.sort(key=lambda e: e["timestamp"])

    # Pagination
    total = len(filtered)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_data = filtered[start_idx:end_idx]

    return {
        "data": page_data,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        },
    }


def clear_logs() -> None:
    """Clear all stored logs. Useful for testing."""
    global _ID_COUNTER
    with _LOG_STORE_LOCK:
        _LOG_STORE.clear()
        _ID_COUNTER = 0
