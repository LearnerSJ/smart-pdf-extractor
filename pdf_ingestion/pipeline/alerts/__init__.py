"""Alert evaluation engine and notification dispatcher.

This package provides the background alert evaluation engine that periodically
checks alert rules against usage and job data, and dispatches notifications
when thresholds are crossed or conditions resolve.
"""

from pipeline.alerts.engine import AlertEngine
from pipeline.alerts.notifier import NotificationDispatcher

__all__ = ["AlertEngine", "NotificationDispatcher"]
