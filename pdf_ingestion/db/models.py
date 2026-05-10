"""SQLAlchemy 2.0 async models for the PDF Ingestion Layer."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class Tenant(Base):
    """Tenant model — authenticated API consumer with configurable settings."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    vlm_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    redaction_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    delivery_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    jobs: Mapped[list[Job]] = relationship("Job", back_populates="tenant")
    batches: Mapped[list[Batch]] = relationship("Batch", back_populates="tenant")


class Batch(Base):
    """Batch model — groups multiple extraction jobs for coordinated delivery."""

    __tablename__ = "batches"

    batch_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False
    )  # pending | complete | delivered | delivery_failed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivery_status: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relationships
    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="batches")
    jobs: Mapped[list[Job]] = relationship("Job", back_populates="batch")
    delivery_logs: Mapped[list[DeliveryLog]] = relationship(
        "DeliveryLog", back_populates="batch"
    )


class Job(Base):
    """Job model — a single extraction job for one document."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.id"), nullable=False
    )
    batch_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("batches.batch_id"), nullable=True
    )
    schema_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), default="submitted", nullable=False
    )  # submitted | processing | complete | failed | partial
    trace_id: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    doc_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="jobs")
    batch: Mapped[Batch | None] = relationship("Batch", back_populates="jobs")
    results: Mapped[list[Result]] = relationship("Result", back_populates="job")
    feedback: Mapped[list[Feedback]] = relationship("Feedback", back_populates="job")
    vlm_usage: Mapped[list[VLMUsage]] = relationship("VLMUsage", back_populates="job")
    delivery_logs: Mapped[list[DeliveryLog]] = relationship(
        "DeliveryLog", back_populates="job"
    )

    __table_args__ = (
        Index("idx_jobs_batch", "batch_id"),
        Index("idx_jobs_tenant", "tenant_id"),
    )


class Result(Base):
    """Result model — extraction output for a completed job."""

    __tablename__ = "results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    output: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    job: Mapped[Job] = relationship("Job", back_populates="results")


class Feedback(Base):
    """Feedback model — corrections and triangulation flags."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    field_name: Mapped[str] = mapped_column(Text, nullable=False)
    table_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    correct_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # triangulation | correction_api
    triangulation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    vlm_was_used: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    job: Mapped[Job] = relationship("Job", back_populates="feedback")

    __table_args__ = (
        Index("idx_feedback_tenant", "tenant_id"),
        Index("idx_feedback_job", "job_id"),
        Index("idx_feedback_field", "field_name"),
    )


class VLMUsage(Base):
    """VLMUsage model — tracks VLM invocations and token usage."""

    __tablename__ = "vlm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    field_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    job: Mapped[Job] = relationship("Job", back_populates="vlm_usage")


class DeliveryLog(Base):
    """DeliveryLog model — records every delivery attempt for audit."""

    __tablename__ = "delivery_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("batches.batch_id"), nullable=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True
    )
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str] = mapped_column(Text, nullable=False)
    callback_url: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    batch: Mapped[Batch | None] = relationship("Batch", back_populates="delivery_logs")
    job: Mapped[Job | None] = relationship("Job", back_populates="delivery_logs")
