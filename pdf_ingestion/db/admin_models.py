"""SQLAlchemy 2.0 async models for the Admin Dashboard tables."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models import Base


class DashboardUser(Base):
    """Dashboard user model — operator/admin accounts for the admin dashboard."""

    __tablename__ = "dashboard_users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # admin, operator, viewer
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    role_assignments: Mapped[list[RoleAssignment]] = relationship(
        "RoleAssignment", back_populates="user", cascade="all, delete-orphan"
    )
    created_alert_rules: Mapped[list[AlertRule]] = relationship(
        "AlertRule", back_populates="creator", foreign_keys="AlertRule.created_by"
    )
    acknowledged_alerts: Mapped[list[AlertHistory]] = relationship(
        "AlertHistory",
        back_populates="acknowledger",
        foreign_keys="AlertHistory.acknowledged_by",
    )


class RoleAssignment(Base):
    """Role assignment model — maps dashboard users to tenants."""

    __tablename__ = "role_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dashboard_users.id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    user: Mapped[DashboardUser] = relationship(
        "DashboardUser", back_populates="role_assignments"
    )

    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_role_user_tenant"),
    )


class AlertRule(Base):
    """Alert rule model — configurable alert definitions."""

    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    rule_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # budget, error_rate, circuit_breaker
    tenant_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    notification_channel: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # webhook, email
    notification_target: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="idle"
    )  # idle, firing, resolved
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dashboard_users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    creator: Mapped[DashboardUser | None] = relationship(
        "DashboardUser",
        back_populates="created_alert_rules",
        foreign_keys=[created_by],
    )
    history: Mapped[list[AlertHistory]] = relationship(
        "AlertHistory", back_populates="rule", cascade="all, delete-orphan"
    )


class AlertHistory(Base):
    """Alert history model — records of alert firings and resolutions."""

    __tablename__ = "alert_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alert_rules.id"), nullable=False
    )
    tenant_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    fired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notification_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dashboard_users.id"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    rule: Mapped[AlertRule] = relationship(
        "AlertRule", back_populates="history"
    )
    acknowledger: Mapped[DashboardUser | None] = relationship(
        "DashboardUser",
        back_populates="acknowledged_alerts",
        foreign_keys=[acknowledged_by],
    )


class StructuredLog(Base):
    """Structured log model — persisted log entries for SQL-based querying."""

    __tablename__ = "structured_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    event_name: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    trace_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("idx_logs_trace_id", "trace_id"),
        Index("idx_logs_tenant_time", "tenant_id", "timestamp"),
        Index("idx_logs_severity_time", "severity", "timestamp"),
        Index("idx_logs_job_id", "job_id"),
    )


class TokenRevocation(Base):
    """Token revocation model — tracks invalidated JWTs for logout support."""

    __tablename__ = "token_revocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jti: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
