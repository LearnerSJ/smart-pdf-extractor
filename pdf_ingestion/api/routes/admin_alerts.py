"""Admin alert rule CRUD routes.

Provides endpoints for managing alert rules (create, read, update, delete),
viewing alert history, and acknowledging firing alerts.

NOTE: For the demo/MVP, uses in-memory stores.
In production, these would use the alert_rules and alert_history tables via SQLAlchemy.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from api.middleware.rbac import Permission, require_permission
from api.models.response import APIResponse, ResponseMeta

router = APIRouter()
logger = structlog.get_logger()


# ─── Request Models ───────────────────────────────────────────────────────────


class AlertRuleCreate(BaseModel):
    """Request body for creating an alert rule."""

    name: str
    rule_type: Literal["budget", "error_rate", "circuit_breaker"]
    tenant_id: str | None = None
    config: dict
    notification_channel: Literal["webhook", "email"]
    notification_target: str
    enabled: bool = True


class AlertRuleUpdate(BaseModel):
    """Request body for updating an alert rule (all fields optional)."""

    name: str | None = None
    config: dict | None = None
    notification_channel: Literal["webhook", "email"] | None = None
    notification_target: str | None = None
    enabled: bool | None = None


# ─── Response Models ──────────────────────────────────────────────────────────


class AlertRuleResponse(BaseModel):
    """Response model for an alert rule."""

    id: str
    name: str
    rule_type: str
    tenant_id: str | None
    config: dict
    notification_channel: str
    notification_target: str
    enabled: bool
    state: str
    last_evaluated_at: str | None
    created_at: str


class AlertRuleListData(BaseModel):
    """List of alert rules."""

    rules: list[AlertRuleResponse]


class AlertHistoryEntry(BaseModel):
    """A single alert history entry."""

    id: str
    rule_id: str
    tenant_id: str | None
    fired_at: str
    resolved_at: str | None
    notification_sent: bool
    acknowledged_by: str | None
    acknowledged_at: str | None
    context: dict | None


class AlertHistoryListData(BaseModel):
    """List of alert history entries."""

    entries: list[AlertHistoryEntry]


class AlertAckData(BaseModel):
    """Response data for alert acknowledgment."""

    acknowledged: bool


class AlertRuleDeleteData(BaseModel):
    """Response data for alert rule deletion."""

    success: bool


# ─── In-Memory Demo Stores ────────────────────────────────────────────────────

_ALERT_RULES: list[dict] = []
_ALERT_HISTORY: list[dict] = []


def _seed_demo_data() -> None:
    """Seed demo alert rules and history for testing."""
    now = datetime.now(timezone.utc)

    # Seed a few demo alert rules
    rules = [
        {
            "id": str(uuid.uuid4()),
            "name": "Tenant-1 Budget Alert",
            "rule_type": "budget",
            "tenant_id": "tenant-1",
            "config": {"threshold_tokens": 1000000, "billing_period": "monthly"},
            "notification_channel": "webhook",
            "notification_target": "https://hooks.example.com/budget",
            "enabled": True,
            "state": "idle",
            "last_evaluated_at": now.isoformat(),
            "created_at": now.isoformat(),
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Global Error Rate Alert",
            "rule_type": "error_rate",
            "tenant_id": None,
            "config": {"threshold_percent": 10.0, "evaluation_window_minutes": 15},
            "notification_channel": "email",
            "notification_target": "ops@example.com",
            "enabled": True,
            "state": "firing",
            "last_evaluated_at": now.isoformat(),
            "created_at": now.isoformat(),
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Delivery Service Circuit Breaker",
            "rule_type": "circuit_breaker",
            "tenant_id": "tenant-2",
            "config": {"service_name": "delivery-api"},
            "notification_channel": "webhook",
            "notification_target": "https://hooks.example.com/cb",
            "enabled": False,
            "state": "resolved",
            "last_evaluated_at": None,
            "created_at": now.isoformat(),
        },
    ]
    _ALERT_RULES.extend(rules)

    # Seed some alert history entries
    history = [
        {
            "id": str(uuid.uuid4()),
            "rule_id": rules[1]["id"],
            "tenant_id": None,
            "fired_at": now.isoformat(),
            "resolved_at": None,
            "notification_sent": True,
            "acknowledged_by": None,
            "acknowledged_at": None,
            "context": {"threshold_percent": 10.0, "actual_percent": 15.3},
        },
    ]
    _ALERT_HISTORY.extend(history)


# Seed on module load
_seed_demo_data()


# ─── Validation Helpers ───────────────────────────────────────────────────────

_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URL_REGEX = re.compile(r"^https?://\S+$")


def _validate_notification_target(channel: str, target: str) -> str | None:
    """Validate notification target based on channel type.

    Returns an error message if invalid, None if valid.
    """
    if channel == "webhook":
        if not _URL_REGEX.match(target):
            return "notification_target must be a valid URL for webhook channel"
    elif channel == "email":
        if not _EMAIL_REGEX.match(target):
            return "notification_target must be a valid email address for email channel"
    return None


def _validate_rule_config(rule_type: str, config: dict) -> list[str]:
    """Validate rule config based on rule_type.

    Returns a list of error messages. Empty list means valid.
    """
    errors: list[str] = []

    if rule_type == "budget":
        if "threshold_tokens" not in config:
            errors.append("config.threshold_tokens is required for budget rules")
        else:
            threshold = config["threshold_tokens"]
            if not isinstance(threshold, int) or threshold <= 0:
                errors.append("config.threshold_tokens must be a positive integer")

        if "billing_period" not in config:
            errors.append("config.billing_period is required for budget rules")
        else:
            period = config["billing_period"]
            if period not in ("monthly", "weekly"):
                errors.append("config.billing_period must be 'monthly' or 'weekly'")

    elif rule_type == "error_rate":
        if "threshold_percent" not in config:
            errors.append("config.threshold_percent is required for error_rate rules")
        else:
            threshold = config["threshold_percent"]
            if not isinstance(threshold, (int, float)) or threshold < 0 or threshold > 100:
                errors.append("config.threshold_percent must be a float between 0 and 100")

        if "evaluation_window_minutes" not in config:
            errors.append("config.evaluation_window_minutes is required for error_rate rules")
        else:
            window = config["evaluation_window_minutes"]
            if not isinstance(window, int) or window <= 0:
                errors.append("config.evaluation_window_minutes must be a positive integer")

    elif rule_type == "circuit_breaker":
        if "service_name" not in config:
            errors.append("config.service_name is required for circuit_breaker rules")
        else:
            service_name = config["service_name"]
            if not isinstance(service_name, str) or not service_name.strip():
                errors.append("config.service_name must be a non-empty string")

    return errors


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/v1/admin/alerts/rules", status_code=200)
async def list_alert_rules(
    user: dict = Depends(require_permission(Permission.WRITE)),
) -> APIResponse[AlertRuleListData]:
    """List all alert rules.

    Requires Admin or Operator role (WRITE permission).
    """
    request_id = str(uuid.uuid4())

    rules = [AlertRuleResponse(**r) for r in _ALERT_RULES]

    return APIResponse[AlertRuleListData](
        data=AlertRuleListData(rules=rules),
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )


@router.post("/v1/admin/alerts/rules", status_code=201)
async def create_alert_rule(
    body: AlertRuleCreate,
    user: dict = Depends(require_permission(Permission.WRITE)),
) -> APIResponse[AlertRuleResponse]:
    """Create a new alert rule with validation.

    Requires Admin or Operator role (WRITE permission).
    Returns 422 for invalid rule parameters.
    """
    request_id = str(uuid.uuid4())

    # Validate config based on rule_type
    config_errors = _validate_rule_config(body.rule_type, body.config)
    if config_errors:
        raise HTTPException(
            status_code=422,
            detail="; ".join(config_errors),
        )

    # Validate notification target
    target_error = _validate_notification_target(body.notification_channel, body.notification_target)
    if target_error:
        raise HTTPException(
            status_code=422,
            detail=target_error,
        )

    now = datetime.now(timezone.utc)
    rule = {
        "id": str(uuid.uuid4()),
        "name": body.name,
        "rule_type": body.rule_type,
        "tenant_id": body.tenant_id,
        "config": body.config,
        "notification_channel": body.notification_channel,
        "notification_target": body.notification_target,
        "enabled": body.enabled,
        "state": "idle",
        "last_evaluated_at": None,
        "created_at": now.isoformat(),
    }
    _ALERT_RULES.append(rule)

    logger.info(
        "alert_rule.created",
        rule_id=rule["id"],
        rule_type=body.rule_type,
        name=body.name,
    )

    return APIResponse[AlertRuleResponse](
        data=AlertRuleResponse(**rule),
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=now.isoformat(),
        ),
    )


@router.put("/v1/admin/alerts/rules/{rule_id}", status_code=200)
async def update_alert_rule(
    rule_id: str,
    body: AlertRuleUpdate,
    user: dict = Depends(require_permission(Permission.WRITE)),
) -> APIResponse[AlertRuleResponse]:
    """Update an existing alert rule.

    Requires Admin or Operator role (WRITE permission).
    Returns 404 if rule not found, 422 for invalid parameters.
    """
    request_id = str(uuid.uuid4())

    # Find the rule
    rule = None
    for r in _ALERT_RULES:
        if r["id"] == rule_id:
            rule = r
            break

    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    # Validate config if provided
    if body.config is not None:
        config_errors = _validate_rule_config(rule["rule_type"], body.config)
        if config_errors:
            raise HTTPException(
                status_code=422,
                detail="; ".join(config_errors),
            )

    # Validate notification target if channel or target is being updated
    channel = body.notification_channel if body.notification_channel is not None else rule["notification_channel"]
    target = body.notification_target if body.notification_target is not None else rule["notification_target"]
    target_error = _validate_notification_target(channel, target)
    if target_error:
        raise HTTPException(
            status_code=422,
            detail=target_error,
        )

    # Apply updates
    if body.name is not None:
        rule["name"] = body.name
    if body.config is not None:
        rule["config"] = body.config
    if body.notification_channel is not None:
        rule["notification_channel"] = body.notification_channel
    if body.notification_target is not None:
        rule["notification_target"] = body.notification_target
    if body.enabled is not None:
        rule["enabled"] = body.enabled

    logger.info(
        "alert_rule.updated",
        rule_id=rule_id,
    )

    return APIResponse[AlertRuleResponse](
        data=AlertRuleResponse(**rule),
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )


@router.delete("/v1/admin/alerts/rules/{rule_id}", status_code=200)
async def delete_alert_rule(
    rule_id: str,
    user: dict = Depends(require_permission(Permission.ADMIN)),
) -> APIResponse[AlertRuleDeleteData]:
    """Delete an alert rule.

    Requires Admin role (ADMIN permission).
    Returns 404 if rule not found.
    """
    request_id = str(uuid.uuid4())

    # Find and remove the rule
    for i, r in enumerate(_ALERT_RULES):
        if r["id"] == rule_id:
            _ALERT_RULES.pop(i)
            logger.info("alert_rule.deleted", rule_id=rule_id)
            return APIResponse[AlertRuleDeleteData](
                data=AlertRuleDeleteData(success=True),
                meta=ResponseMeta(
                    request_id=request_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ),
            )

    raise HTTPException(status_code=404, detail="Alert rule not found")


@router.get("/v1/admin/alerts/history", status_code=200)
async def list_alert_history(
    rule_id: str | None = Query(None, description="Filter by rule ID"),
    tenant_id: str | None = Query(None, description="Filter by tenant ID"),
    user: dict = Depends(require_permission(Permission.READ)),
) -> APIResponse[AlertHistoryListData]:
    """List alert history entries.

    Requires Admin or Operator role (READ permission).
    Supports optional filtering by rule_id and tenant_id.
    """
    request_id = str(uuid.uuid4())

    results = _ALERT_HISTORY

    if rule_id is not None:
        results = [h for h in results if h["rule_id"] == rule_id]

    if tenant_id is not None:
        results = [h for h in results if h["tenant_id"] == tenant_id]

    entries = [AlertHistoryEntry(**h) for h in results]

    return APIResponse[AlertHistoryListData](
        data=AlertHistoryListData(entries=entries),
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )


@router.post("/v1/admin/alerts/{alert_id}/ack", status_code=200)
async def acknowledge_alert(
    alert_id: str,
    user: dict = Depends(require_permission(Permission.WRITE)),
) -> APIResponse[AlertAckData]:
    """Acknowledge a firing alert.

    Requires Admin or Operator role (WRITE permission).
    Records the acknowledgment with user_id and timestamp.
    Returns 404 if alert history entry not found.
    """
    request_id = str(uuid.uuid4())

    # Find the alert history entry
    entry = None
    for h in _ALERT_HISTORY:
        if h["id"] == alert_id:
            entry = h
            break

    if entry is None:
        raise HTTPException(status_code=404, detail="Alert history entry not found")

    # Record acknowledgment
    now = datetime.now(timezone.utc)
    user_id = user.get("sub", "unknown")
    entry["acknowledged_by"] = user_id
    entry["acknowledged_at"] = now.isoformat()

    logger.info(
        "alert.acknowledged",
        alert_id=alert_id,
        acknowledged_by=user_id,
    )

    return APIResponse[AlertAckData](
        data=AlertAckData(acknowledged=True),
        meta=ResponseMeta(
            request_id=request_id,
            timestamp=now.isoformat(),
        ),
    )
