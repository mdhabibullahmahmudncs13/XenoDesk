"""Shared platform models: scheduled jobs and in-app notifications."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from xenovarients.db.base import Base, TenantScopedMixin, TimestampMixin


class JobType(str, enum.Enum):
    review_request = "review_request"
    restock_batch_dispatch = "restock_batch_dispatch"
    inventory_poll = "inventory_poll"
    retry_delivery = "retry_delivery"


class JobState(str, enum.Enum):
    pending = "pending"
    claimed = "claimed"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class NotificationKind(str, enum.Enum):
    restock = "restock"
    bubble = "bubble"
    review_reply = "review_reply"
    ad_sync = "ad_sync"
    chat_cost = "chat_cost"


class ScheduledJob(Base, TenantScopedMixin, TimestampMixin):
    """Delayed work. ``idempotency_key`` keeps a job unique per business."""

    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "idempotency_key", name="uq_scheduled_jobs_business_id_idempotency_key"
        ),
        Index("ix_scheduled_jobs_state_run_at", "state", "run_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default=JobState.pending.value)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON(), nullable=False, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class Notification(Base, TenantScopedMixin, TimestampMixin):
    """In-app dashboard notification. No browser push (CG-11)."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "ix_notifications_business_id_is_read_created_at",
            "business_id",
            "is_read",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
