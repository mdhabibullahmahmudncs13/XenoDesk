"""Agent Workspace models: FAQ registry, chat, AI usage, tours (M3)."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

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


class ChatRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class AnswerType(str, enum.Enum):
    faq = "faq"
    data = "data"
    ai = "ai"
    blocked = "blocked"


class AiRoute(str, enum.Enum):
    faq = "faq"
    data = "data"
    ai = "ai"
    blocked = "blocked"


class TourState(str, enum.Enum):
    offered = "offered"
    in_progress = "in_progress"
    skipped = "skipped"
    completed = "completed"


class FaqEntry(Base, TenantScopedMixin, TimestampMixin):
    """One answerable topic. ``business_id`` is always set — the tenant filter needs it."""

    __tablename__ = "faq_entries"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "faq_key", "locale", name="uq_faq_entries_business_id_faq_key_locale"
        ),
        Index("ix_faq_entries_business_id_is_active", "business_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    faq_key: Mapped[str] = mapped_column(String(64), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    answer_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AnswerType.faq.value
    )
    references: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    locale: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    review_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class FaqAlias(Base, TenantScopedMixin, TimestampMixin):
    """Normalised alias pointing at an FAQ entry (AW-03)."""

    __tablename__ = "faq_aliases"
    __table_args__ = (
        UniqueConstraint("faq_entry_id", "alias", name="uq_faq_aliases_faq_entry_id_alias"),
        Index("ix_faq_aliases_alias", "alias"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    faq_entry_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("faq_entries.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    locale: Mapped[str] = mapped_column(String(8), nullable=False, default="en")


class ChatSession(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        Index(
            "ix_chat_sessions_business_id_user_id_last_message_at",
            "business_id",
            "user_id",
            "last_message_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChatMessage(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_chat_session_id_created_at", "chat_session_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chat_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    answer_type: Mapped[str | None] = mapped_column(String(16))
    references: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    data_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiUsageEvent(Base, TenantScopedMixin, TimestampMixin):
    """Per-request usage and cost. FAQ route costs zero tokens (AW-04)."""

    __tablename__ = "ai_usage_events"
    __table_args__ = (
        Index("ix_ai_usage_events_business_id_created_at", "business_id", "created_at"),
        Index("ix_ai_usage_events_route_created_at", "route", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    chat_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="SET NULL")
    )
    route: Mapped[str] = mapped_column(String(16), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, default=Decimal("0")
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model: Mapped[str | None] = mapped_column(String(64))
    tools_invoked: Mapped[list[str]] = mapped_column(JSON(), default=list, server_default="[]")
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TourStep(Base, TenantScopedMixin, TimestampMixin):
    """One step of a product tour (AW-10)."""

    __tablename__ = "tour_steps"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "step_order",
            "locale",
            name="uq_tour_steps_business_id_step_order_locale",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    selector: Mapped[str | None] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class TourProgress(Base, TenantScopedMixin, TimestampMixin):
    """Per-user tour state (AW-11)."""

    __tablename__ = "tour_progress"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "user_id",
            "tour_key",
            name="uq_tour_progress_business_id_user_id_tour_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tour_key: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default=TourState.offered.value)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
