"""SQLAlchemy ORM models defining all required entities with indexes and foreign keys."""

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.domain.enums import (
    DeliveryStatus,
    ExportFormat,
    ExportStatus,
    ProcessingStatus,
    ScheduleType,
    UserRole,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


PG_JSON = JSON().with_variant(JSONB, "postgresql")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.STUDENT, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    submissions: Mapped[list["Submission"]] = relationship(
        "Submission", back_populates="user", cascade="all, delete-orphan"
    )


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    submitted_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )
    business_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    original_file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    processed_file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    question_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    option_a: Mapped[str | None] = mapped_column(Text, nullable=True)
    option_b: Mapped[str | None] = mapped_column(Text, nullable=True)
    option_c: Mapped[str | None] = mapped_column(Text, nullable=True)
    option_d: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus), default=ProcessingStatus.RECEIVED, index=True, nullable=False
    )
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus), default=DeliveryStatus.PENDING, index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="submissions")
    attempts: Mapped[list["ProcessingAttempt"]] = relationship(
        "ProcessingAttempt", back_populates="submission", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_submissions_user_date", "user_id", "business_date"),
        Index("ix_submissions_date_status", "business_date", "processing_status"),
        Index("ix_submissions_sort", "submitted_at_utc", "id"),
    )


class ProcessingAttempt(Base):
    __tablename__ = "processing_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("submissions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    submission: Mapped["Submission"] = relationship("Submission", back_populates="attempts")


class Recipient(Base):
    __tablename__ = "recipients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(64), default="TEACHER", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # UUID string
    export_type: Mapped[str] = mapped_column(String(32), default="MANUAL", nullable=False)
    date_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    date_to: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    format: Mapped[ExportFormat] = mapped_column(Enum(ExportFormat), default=ExportFormat.DOCX, nullable=False)
    content_config: Mapped[dict[str, Any]] = mapped_column(PG_JSON, default=dict, nullable=False)
    status: Mapped[ExportStatus] = mapped_column(
        Enum(ExportStatus), default=ExportStatus.PENDING, index=True, nullable=False
    )
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    export_recipients: Mapped[list["ExportRecipient"]] = relationship(
        "ExportRecipient", back_populates="export", cascade="all, delete-orphan"
    )


class ExportRecipient(Base):
    __tablename__ = "export_recipients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    export_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("exports.id", ondelete="CASCADE"), index=True, nullable=False
    )
    recipient_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recipients.id", ondelete="CASCADE"), index=True, nullable=False
    )
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus), default=DeliveryStatus.PENDING, nullable=False
    )
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)

    export: Mapped["Export"] = relationship("Export", back_populates="export_recipients")
    recipient: Mapped["Recipient"] = relationship("Recipient")


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_type: Mapped[ScheduleType] = mapped_column(Enum(ScheduleType), default=ScheduleType.DAILY, nullable=False)
    time_of_day: Mapped[str] = mapped_column(String(8), default="23:00", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Riyadh", nullable=False)
    format: Mapped[ExportFormat] = mapped_column(Enum(ExportFormat), default=ExportFormat.DOCX, nullable=False)
    content_config: Mapped[dict[str, Any]] = mapped_column(PG_JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    executions: Mapped[list["ScheduleExecution"]] = relationship(
        "ScheduleExecution", back_populates="schedule", cascade="all, delete-orphan"
    )


class ScheduleExecution(Base):
    __tablename__ = "schedule_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("schedules.id", ondelete="CASCADE"), index=True, nullable=False
    )
    business_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING", nullable=False)
    export_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    schedule: Mapped["Schedule"] = relationship("Schedule", back_populates="executions")

    __table_args__ = (UniqueConstraint("schedule_id", "business_date", name="uq_schedule_business_date"),)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_safe: Mapped[dict[str, Any]] = mapped_column(PG_JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True, nullable=False)

    __table_args__ = (Index("ix_admin_audit_logs_action_created", "action", "created_at"),)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
