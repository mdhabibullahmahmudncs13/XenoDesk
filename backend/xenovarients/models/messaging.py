"""Messaging identity, inbound events, bubbles and contact permissions (M1 + shared)."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from xenovarients.db.base import Base, TenantScopedMixin, TimestampMixin


class Channel(str, enum.Enum):
    messenger = "messenger"
    whatsapp = "whatsapp"
    sms = "sms"
    email = "email"


class IdentityMethod(str, enum.Enum):
    verified_link = "verified_link"
    phone = "phone"
    email = "email"
    staff_link = "staff_link"
    customer_shared_phone = "customer_shared_phone"


class MessagingIdentityLink(Base, TenantScopedMixin, TimestampMixin):
    """Maps a platform-scoped channel identity to a customer (CG-03)."""

    __tablename__ = "messaging_identity_links"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "channel",
            "channel_user_id",
            name="uq_messaging_identity_links_business_id_channel_channel_user_id",
        ),
        Index("ix_messaging_identity_links_business_id_customer_id", "business_id", "customer_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    channel_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class IdentityConflict(Base, TenantScopedMixin, TimestampMixin):
    """An unresolved match. Never auto-merged (CG-03, CG-10)."""

    __tablename__ = "identity_conflicts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    channel_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    candidate_customer_ids: Mapped[list[str]] = mapped_column(
        JSON(), default=list, server_default="[]"
    )
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    resolved_customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL")
    )
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class InboundMessageEvent(Base, TenantScopedMixin, TimestampMixin):
    """Insert-only. The unique provider_event_id is the inbound idempotency key."""

    __tablename__ = "inbound_message_events"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "provider_event_id",
            name="uq_inbound_message_events_business_id_provider_event_id",
        ),
        Index(
            "ix_inbound_message_events_business_id_channel_user_recv_at",
            "business_id",
            "channel_user_id",
            "received_at",
        ),
        Index(
            "ix_inbound_message_events_business_id_conversation_id",
            "business_id",
            "conversation_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String(255))
    channel_user_id: Mapped[str | None] = mapped_column(String(255))
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="inbound")
    message_id: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str | None] = mapped_column(Text)
    # Provider timestamp — qualification compares against this, not processing time (CG-06).
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL")
    )
    review_request_id: Mapped[uuid.UUID | None] = mapped_column()


class BubbleState(str, enum.Enum):
    new = "new"
    seen = "seen"
    dismissed = "dismissed"


class CustomerBubble(Base, TenantScopedMixin, TimestampMixin):
    """One bubble per customer and conversation (CG-08)."""

    __tablename__ = "customer_bubbles"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "customer_id",
            "conversation_id",
            name="uq_customer_bubbles_business_id_customer_id_conversation_id",
        ),
        Index(
            "ix_customer_bubbles_business_id_state_last_message_at",
            "business_id",
            "state",
            "last_message_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    # False means: no "Returning Customer" label and no figures at all (CG-10).
    is_returning_customer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_spend: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BDT")
    last_purchase_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_message_preview: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default=BubbleState.new.value)
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    link_customer_offered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ContactPermission(Base, TenantScopedMixin, TimestampMixin):
    """Per-channel send eligibility and opt-out state (RP-08)."""

    __tablename__ = "contact_permissions"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "customer_id",
            "channel",
            name="uq_contact_permissions_business_id_customer_id_channel",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    contact_value: Mapped[str] = mapped_column(String(320), nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
