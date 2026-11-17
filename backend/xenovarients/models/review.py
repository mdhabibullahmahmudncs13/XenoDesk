"""Review models: requests, replies, consent, cards (M2)."""

import enum
import uuid
from datetime import datetime

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


class ReviewRequestState(str, enum.Enum):
    scheduled = "scheduled"
    sent = "sent"
    replied = "replied"
    cancelled = "cancelled"
    skipped = "skipped"
    needs_assignment = "needs_assignment"
    unresolved = "unresolved"


class ConsentState(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    anonymous = "anonymous"
    declined = "declined"
    revoked = "revoked"


class ReviewSettings(Base, TenantScopedMixin, TimestampMixin):
    """One row per business."""

    __tablename__ = "review_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    delay_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    send_window_start: Mapped[str] = mapped_column(String(8), nullable=False, default="09:00")
    send_window_end: Mapped[str] = mapped_column(String(8), nullable=False, default="20:00")
    reply_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    channel_order: Mapped[list[str]] = mapped_column(JSON(), default=list, server_default="[]")
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("message_templates.id", ondelete="SET NULL")
    )


class ReviewRequest(Base, TenantScopedMixin, TimestampMixin):
    """One request per order (RV-05)."""

    __tablename__ = "review_requests"
    __table_args__ = (
        UniqueConstraint("business_id", "order_id", name="uq_review_requests_business_id_order_id"),
        Index("ix_review_requests_business_id_state_due_at", "business_id", "state", "due_at"),
        Index("ix_review_requests_business_id_reference_token", "business_id", "reference_token"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customer_orders.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    delivery_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(
        String(24), nullable=False, default=ReviewRequestState.scheduled.value
    )
    state_reason: Mapped[str | None] = mapped_column(String(64))
    reference_token: Mapped[str] = mapped_column(String(64), nullable=False)
    sent_channel: Mapped[str | None] = mapped_column(String(16))


class ReviewReply(Base, TenantScopedMixin, TimestampMixin):
    """Verbatim customer reply. The content column is protected by a DB trigger."""

    __tablename__ = "review_replies"
    __table_args__ = (
        UniqueConstraint(
            "inbound_message_id",
            name="uq_review_replies_inbound_message_id",
        ),
        Index(
            "ix_review_replies_business_id_customer_id_received_at",
            "business_id",
            "customer_id",
            "received_at",
        ),
        Index("ix_review_replies_review_request_id", "review_request_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    review_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("review_requests.id", ondelete="SET NULL")
    )
    inbound_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inbound_message_events.id", ondelete="SET NULL")
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customer_orders.id", ondelete="SET NULL")
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sentiment: Mapped[str | None] = mapped_column(String(16))


class ReviewReplyProduct(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "review_reply_products"
    __table_args__ = (
        UniqueConstraint(
            "review_reply_id",
            "product_id",
            name="uq_review_reply_products_review_reply_id_product_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    review_reply_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("review_replies.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="SET NULL")
    )


class ReviewPermission(Base, TenantScopedMixin, TimestampMixin):
    """Consent state per review request (RV-09)."""

    __tablename__ = "review_permissions"
    __table_args__ = (
        UniqueConstraint("review_request_id", name="uq_review_permissions_review_request_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    review_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("review_requests.id", ondelete="CASCADE"), nullable=False
    )
    review_reply_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("review_replies.id", ondelete="SET NULL")
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ConsentState.pending.value
    )
    consent_method: Mapped[str] = mapped_column(String(32), nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_text_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")


class ReviewCard(Base, TenantScopedMixin, TimestampMixin):
    """Generated marketing card. Words are copied exactly from the reply (RV-10)."""

    __tablename__ = "review_cards"
    __table_args__ = (
        UniqueConstraint(
            "review_request_id", "version", name="uq_review_cards_review_request_id_version"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    review_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("review_requests.id", ondelete="CASCADE"), nullable=False
    )
    review_reply_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("review_replies.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    display_text: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    display_label: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Customer review"
    )
    is_anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    template_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
