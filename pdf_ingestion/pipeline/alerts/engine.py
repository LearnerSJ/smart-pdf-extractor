"""Alert evaluation engine.

Periodically evaluates enabled alert rules against usage and job data,
manages rule state transitions (idle → firing → resolved), and emits
notifications via the notification dispatcher.

State machine for alert rules:
- idle → firing: when threshold is crossed (emit notification)
- firing → firing: no action (already notified)
- firing → resolved: when condition returns to normal (emit recovery notification)
- resolved → idle: on next evaluation cycle

For the demo/MVP, uses in-memory stores from admin_alerts.py and admin_usage.py.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import structlog

logger = structlog.get_logger()


# ─── In-Memory Job Store ──────────────────────────────────────────────────────
# Simple in-memory store for job status tracking.
# In production, this would query the jobs table via SQLAlchemy.

_JOB_RECORDS: list[dict] = []


def _seed_demo_jobs() -> None:
    """Seed demo job records for testing."""
    import random

    random.seed(43)

    tenants = ["tenant-1", "tenant-2", "tenant-3"]
    statuses = ["completed", "completed", "completed", "completed", "failed"]  # 20% failure rate
    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)

    for i in range(50):
        tenant_id = random.choice(tenants)
        status = random.choice(statuses)
        timestamp = base_time + timedelta(days=random.randint(0, 89), hours=random.randint(0, 23))

        record = {
            "id": f"job-{uuid.uuid4().hex[:8]}",
            "tenant_id": tenant_id,
            "status": status,
            "created_at": timestamp.isoformat(),
        }
        _JOB_RECORDS.append(record)

    _JOB_RECORDS.sort(key=lambda r: r["created_at"])


_seed_demo_jobs()


# ─── Alert Engine ─────────────────────────────────────────────────────────────


class AlertEngine:
    """Evaluates alert rules on a configurable interval.

    The engine runs as an async background task, periodically evaluating
    all enabled alert rules and dispatching notifications when thresholds
    are crossed or conditions resolve.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running: bool = False
        self._notifier: object | None = None

    @property
    def running(self) -> bool:
        """Whether the engine background loop is currently running."""
        return self._running

    def set_notifier(self, notifier: object) -> None:
        """Set the notification dispatcher instance.

        Args:
            notifier: An object with `send_webhook(url, payload)` and
                      `send_email(to, subject, body)` async methods.
        """
        self._notifier = notifier

    async def start(self, interval_seconds: int = 60) -> None:
        """Start the background evaluation loop.

        Args:
            interval_seconds: How often to evaluate rules (default 60s).
        """
        if self._running:
            logger.warning("alert_engine.already_running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop(interval_seconds))
        logger.info("alert_engine.started", interval_seconds=interval_seconds)

    async def stop(self) -> None:
        """Stop the background evaluation loop."""
        if not self._running:
            logger.warning("alert_engine.not_running")
            return

        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("alert_engine.stopped")

    async def _run_loop(self, interval_seconds: int) -> None:
        """Internal loop that evaluates rules at the configured interval."""
        while self._running:
            try:
                await self.evaluate_all_rules()
            except Exception as exc:
                logger.error("alert_engine.evaluation_error", error=str(exc))
            await asyncio.sleep(interval_seconds)

    async def evaluate_all_rules(self) -> None:
        """Evaluate all enabled alert rules.

        Iterates through all alert rules, skipping disabled ones,
        and dispatches to the appropriate evaluation method based on rule_type.
        Transitions resolved rules back to idle at the start of each cycle
        (before evaluation), so the resolved state persists for one full cycle.
        """
        from api.routes.admin_alerts import _ALERT_RULES

        now = datetime.now(timezone.utc)

        for rule in _ALERT_RULES:
            if not rule.get("enabled", False):
                continue

            # Transition resolved → idle at the START of the next cycle
            # This ensures the resolved state is visible for one full cycle
            # before returning to idle.
            if rule.get("state") == "resolved":
                rule["state"] = "idle"
                logger.info(
                    "alert_engine.state_transition",
                    rule_id=rule.get("id"),
                    from_state="resolved",
                    to_state="idle",
                )
                rule["last_evaluated_at"] = now.isoformat()
                continue

            rule_type = rule.get("rule_type")

            try:
                if rule_type == "budget":
                    await self.evaluate_budget_rule(rule)
                elif rule_type == "error_rate":
                    await self.evaluate_error_rate_rule(rule)
                # circuit_breaker rules are event-driven, not polled
            except Exception as exc:
                logger.error(
                    "alert_engine.rule_evaluation_error",
                    rule_id=rule.get("id"),
                    rule_type=rule_type,
                    error=str(exc),
                )

            # Update last_evaluated_at
            rule["last_evaluated_at"] = now.isoformat()

    async def evaluate_budget_rule(self, rule: dict) -> None:
        """Evaluate a budget threshold alert rule.

        Sums tokens for the rule's tenant in the current billing period
        and compares to the configured threshold.

        Args:
            rule: The alert rule dict with config containing
                  threshold_tokens and billing_period.
        """
        from api.routes.admin_usage import _USAGE_RECORDS

        config = rule.get("config", {})
        threshold_tokens = config.get("threshold_tokens", 0)
        billing_period = config.get("billing_period", "monthly")
        tenant_id = rule.get("tenant_id")

        # Determine billing period start
        now = datetime.now(timezone.utc)
        if billing_period == "monthly":
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif billing_period == "weekly":
            # Start of current ISO week (Monday)
            days_since_monday = now.weekday()
            period_start = (now - timedelta(days=days_since_monday)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        else:
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Sum tokens for tenant in billing period
        total_tokens = 0
        for record in _USAGE_RECORDS:
            # Filter by tenant if rule is tenant-scoped
            if tenant_id and record.get("tenant_id") != tenant_id:
                continue

            record_time = datetime.fromisoformat(record["timestamp"])
            if record_time >= period_start:
                total_tokens += record.get("total_tokens", 0)

        current_state = rule.get("state", "idle")

        if total_tokens >= threshold_tokens:
            # Threshold crossed
            if current_state != "firing":
                # Transition to firing — emit notification
                rule["state"] = "firing"
                await self._emit_notification(
                    rule=rule,
                    event_type="firing",
                    context={
                        "threshold_tokens": threshold_tokens,
                        "actual_tokens": total_tokens,
                        "billing_period": billing_period,
                        "tenant_id": tenant_id,
                    },
                )
                logger.info(
                    "alert_engine.state_transition",
                    rule_id=rule.get("id"),
                    from_state=current_state,
                    to_state="firing",
                    threshold=threshold_tokens,
                    actual=total_tokens,
                )
            # If already firing, do nothing (no duplicate notifications)
        else:
            # Below threshold
            if current_state == "firing":
                # Transition to resolved — emit recovery notification
                rule["state"] = "resolved"
                await self._emit_notification(
                    rule=rule,
                    event_type="resolved",
                    context={
                        "threshold_tokens": threshold_tokens,
                        "actual_tokens": total_tokens,
                        "billing_period": billing_period,
                        "tenant_id": tenant_id,
                    },
                )
                logger.info(
                    "alert_engine.state_transition",
                    rule_id=rule.get("id"),
                    from_state="firing",
                    to_state="resolved",
                    threshold=threshold_tokens,
                    actual=total_tokens,
                )

    async def evaluate_error_rate_rule(self, rule: dict) -> None:
        """Evaluate an error rate alert rule.

        Counts failed/total jobs in the evaluation window and compares
        the error rate percentage to the configured threshold.

        Args:
            rule: The alert rule dict with config containing
                  threshold_percent and evaluation_window_minutes.
        """
        config = rule.get("config", {})
        threshold_percent = config.get("threshold_percent", 0.0)
        window_minutes = config.get("evaluation_window_minutes", 15)
        tenant_id = rule.get("tenant_id")

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=window_minutes)

        # Count jobs in the evaluation window
        total_jobs = 0
        failed_jobs = 0

        for job in _JOB_RECORDS:
            # Filter by tenant if rule is tenant-scoped
            if tenant_id and job.get("tenant_id") != tenant_id:
                continue

            job_time = datetime.fromisoformat(job["created_at"])
            if job_time >= window_start:
                total_jobs += 1
                if job.get("status") == "failed":
                    failed_jobs += 1

        # Calculate error rate (avoid division by zero)
        if total_jobs == 0:
            error_rate = 0.0
        else:
            error_rate = (failed_jobs / total_jobs) * 100

        current_state = rule.get("state", "idle")

        if error_rate > threshold_percent:
            # Threshold crossed
            if current_state != "firing":
                # Transition to firing — emit notification
                rule["state"] = "firing"
                await self._emit_notification(
                    rule=rule,
                    event_type="firing",
                    context={
                        "threshold_percent": threshold_percent,
                        "actual_percent": round(error_rate, 2),
                        "total_jobs": total_jobs,
                        "failed_jobs": failed_jobs,
                        "window_minutes": window_minutes,
                        "tenant_id": tenant_id,
                    },
                )
                logger.info(
                    "alert_engine.state_transition",
                    rule_id=rule.get("id"),
                    from_state=current_state,
                    to_state="firing",
                    threshold_percent=threshold_percent,
                    actual_percent=round(error_rate, 2),
                )
            # If already firing, do nothing (no duplicate notifications)
        else:
            # Below threshold
            if current_state == "firing":
                # Transition to resolved — emit recovery notification
                rule["state"] = "resolved"
                await self._emit_notification(
                    rule=rule,
                    event_type="resolved",
                    context={
                        "threshold_percent": threshold_percent,
                        "actual_percent": round(error_rate, 2),
                        "total_jobs": total_jobs,
                        "failed_jobs": failed_jobs,
                        "window_minutes": window_minutes,
                        "tenant_id": tenant_id,
                    },
                )
                logger.info(
                    "alert_engine.state_transition",
                    rule_id=rule.get("id"),
                    from_state="firing",
                    to_state="resolved",
                    threshold_percent=threshold_percent,
                    actual_percent=round(error_rate, 2),
                )

    async def handle_circuit_breaker_event(self, event: dict) -> None:
        """Handle a circuit breaker state transition event.

        This is event-driven (not polled). Called when a circuit breaker
        changes state (closed→open or open→closed).

        Args:
            event: Dict with keys: service_name, tenant_id, previous_state,
                   new_state, timestamp.
        """
        from api.routes.admin_alerts import _ALERT_RULES

        service_name = event.get("service_name", "")
        tenant_id = event.get("tenant_id")
        previous_state = event.get("previous_state", "")
        new_state = event.get("new_state", "")
        timestamp = event.get("timestamp", datetime.now(timezone.utc).isoformat())

        logger.info(
            "alert_engine.circuit_breaker_event",
            service_name=service_name,
            tenant_id=tenant_id,
            previous_state=previous_state,
            new_state=new_state,
            timestamp=timestamp,
        )

        # Find matching circuit breaker rules
        for rule in _ALERT_RULES:
            if not rule.get("enabled", False):
                continue
            if rule.get("rule_type") != "circuit_breaker":
                continue

            rule_config = rule.get("config", {})
            rule_service = rule_config.get("service_name", "")

            # Match by service name
            if rule_service != service_name:
                continue

            # Match by tenant if rule is tenant-scoped
            rule_tenant = rule.get("tenant_id")
            if rule_tenant and rule_tenant != tenant_id:
                continue

            # Determine notification type based on state transition
            if previous_state == "closed" and new_state == "open":
                # Circuit breaker opened — emit firing notification
                rule["state"] = "firing"
                rule["last_evaluated_at"] = datetime.now(timezone.utc).isoformat()
                await self._emit_notification(
                    rule=rule,
                    event_type="firing",
                    context={
                        "service_name": service_name,
                        "tenant_id": tenant_id,
                        "previous_state": previous_state,
                        "new_state": new_state,
                        "timestamp": timestamp,
                    },
                )
                logger.info(
                    "alert_engine.state_transition",
                    rule_id=rule.get("id"),
                    from_state="idle",
                    to_state="firing",
                    service_name=service_name,
                )

            elif previous_state == "open" and new_state == "closed":
                # Circuit breaker closed — emit recovery notification
                rule["state"] = "resolved"
                rule["last_evaluated_at"] = datetime.now(timezone.utc).isoformat()
                await self._emit_notification(
                    rule=rule,
                    event_type="resolved",
                    context={
                        "service_name": service_name,
                        "tenant_id": tenant_id,
                        "previous_state": previous_state,
                        "new_state": new_state,
                        "timestamp": timestamp,
                    },
                )
                logger.info(
                    "alert_engine.state_transition",
                    rule_id=rule.get("id"),
                    from_state="firing",
                    to_state="resolved",
                    service_name=service_name,
                )

    async def _emit_notification(
        self,
        rule: dict,
        event_type: str,
        context: dict,
    ) -> None:
        """Emit a notification and record it in alert history.

        Args:
            rule: The alert rule that triggered.
            event_type: Either "firing" or "resolved".
            context: Additional context about the alert condition.
        """
        from api.routes.admin_alerts import _ALERT_HISTORY

        now = datetime.now(timezone.utc)
        notification_sent = False

        # Attempt to send notification via dispatcher
        if self._notifier is not None:
            try:
                channel = rule.get("notification_channel", "webhook")
                target = rule.get("notification_target", "")
                rule_name = rule.get("name", "Unknown Rule")

                if event_type == "firing":
                    subject = f"[ALERT] {rule_name} - Threshold Exceeded"
                else:
                    subject = f"[RESOLVED] {rule_name} - Condition Recovered"

                payload = {
                    "rule_id": rule.get("id"),
                    "rule_name": rule_name,
                    "rule_type": rule.get("rule_type"),
                    "event_type": event_type,
                    "tenant_id": rule.get("tenant_id"),
                    "context": context,
                    "timestamp": now.isoformat(),
                }

                if channel == "webhook":
                    await self._notifier.send_webhook(target, payload)
                elif channel == "email":
                    body = (
                        f"Alert: {rule_name}\n"
                        f"Type: {rule.get('rule_type')}\n"
                        f"Event: {event_type}\n"
                        f"Context: {context}\n"
                        f"Time: {now.isoformat()}"
                    )
                    await self._notifier.send_email(target, subject, body)

                notification_sent = True
            except Exception as exc:
                logger.error(
                    "alert_engine.notification_failed",
                    rule_id=rule.get("id"),
                    channel=rule.get("notification_channel"),
                    error=str(exc),
                )
                notification_sent = False
        else:
            # No notifier configured — log only
            logger.warning(
                "alert_engine.no_notifier_configured",
                rule_id=rule.get("id"),
                event_type=event_type,
            )

        # Record in alert history
        if event_type == "firing":
            history_entry = {
                "id": str(uuid.uuid4()),
                "rule_id": rule.get("id"),
                "tenant_id": rule.get("tenant_id"),
                "fired_at": now.isoformat(),
                "resolved_at": None,
                "notification_sent": notification_sent,
                "acknowledged_by": None,
                "acknowledged_at": None,
                "context": context,
            }
            _ALERT_HISTORY.append(history_entry)
        elif event_type == "resolved":
            # Update the most recent firing entry for this rule with resolved_at
            for entry in reversed(_ALERT_HISTORY):
                if entry["rule_id"] == rule.get("id") and entry["resolved_at"] is None:
                    entry["resolved_at"] = now.isoformat()
                    break
