"""Outbound messages and delivery attempts — the shared delivery log (RP, RV)."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from xenovarients.db.base import Base, TenantScopedMixin, TimestampMixin


class OutboundPurpose(str, enum.Enum):
    restock = "restock"
    review_request = "review_request"
    review_consent = "review_consent"


class OutboundStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    delivered = "delivered"
    failed = "failed"
    skipped = "skipped"


class SkipReason(str, enum.Enum):
    opted_out = "opted_out"
    no_permission = "no_permission"
    channel_ineligible = "channel_ineligible"
    order_invalid = "order_invalid"
    invalid_address = "invalid_address"


class OutboundMessage(Base, TenantScopedMixin, TimestampMixin):
    """One row per recipient per channel per purpose.

    ``idempotency_key`` is unique — a repeated confirm cannot create a second message
    (RP-08, RP-T05).
    """

    __tablename__ = "outbound_messages"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_outbound_messages_idempotency_key"),
        Index(
            "ix_outbound_messages_business_id_purpose_status", "business_id", "purpose", "status"
        ),
        Index(
            "ix_outbound_messages_pending",
            "status",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    # Polymorphic reference to restock_batches.id or review_requests.id.
    ref_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    to_address: Mapped[str] = mapped_column(String(320), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=OutboundStatus.pending.value
    )
    skip_reason: Mapped[str | None] = mapped_column(String(32))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    error_code: Mapped[str | None] = mapped_column(String(64))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeliveryAttempt(Base):
    """Per-attempt record. Cascade-deleted with the parent message."""

    __tablename__ = "delivery_attempts"
    __table_args__ = (
        UniqueConstraint(
            "outbound_message_id",
            "attempt_number",
            name="uq_delivery_attempts_outbound_message_id_attempt_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    outbound_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outbound_messages.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    provider_response: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    error_code: Mapped[str | None] = mapped_column(String(64))


class MessageTemplate(Base, TenantScopedMixin, TimestampMixin):
    """Message bodies with merge fields. Snapshotted onto a batch at send time."""

    __tablename__ = "message_templates"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "key",
            "locale",
            "version",
            name="uq_message_templates_business_id_key_locale_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    locale: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
