"""Restore Product models: interests, restock events, batches (M1)."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
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


class BatchState(str, enum.Enum):
    queued = "queued"
    sending = "sending"
    completed = "completed"
    cancelled = "cancelled"


class ProductInterest(Base, TenantScopedMixin, TimestampMixin):
    """A customer waiting for a product+variant (RP-02)."""

    __tablename__ = "product_interests"
    __table_args__ = (
        Index(
            "ix_product_interests_business_id_variant_id_requested_at",
            "business_id",
            "variant_id",
            "requested_at",
        ),
        Index("ix_product_interests_business_id_customer_id", "business_id", "customer_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quantity: Mapped[int | None] = mapped_column(Integer)
    contact_channel: Mapped[str] = mapped_column(String(16), nullable=False)
    contact_value: Mapped[str] = mapped_column(String(320), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class RestockEvent(Base, TenantScopedMixin, TimestampMixin):
    """Unavailable → available transition (RP-04). Creating one sends nothing."""

    __tablename__ = "restock_events"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "variant_id",
            "source_ref",
            name="uq_restock_events_business_id_variant_id_source_ref",
        ),
        Index("ix_restock_events_business_id_detected_at", "business_id", "detected_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stock_after: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="poll")
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    notified_owner_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RestockBatch(Base, TenantScopedMixin, TimestampMixin):
    """Owner-confirmed batch. One confirmation queues the messages (RP-07)."""

    __tablename__ = "restock_batches"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "idempotency_key", name="uq_restock_batches_business_id_idempotency_key"
        ),
        Index("ix_restock_batches_business_id_restock_event_id", "business_id", "restock_event_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    restock_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("restock_events.id", ondelete="CASCADE"), nullable=False
    )
    approved_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message_templates.id", ondelete="RESTRICT"), nullable=False
    )
    template_version: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default=BatchState.queued.value)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
