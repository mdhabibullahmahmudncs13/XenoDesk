"""Ads models: insight snapshots, own-account connections, collaboration suggestions (M2)."""

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
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from xenovarients.db.base import Base, TenantScopedMixin, TimestampMixin


class AdScope(str, enum.Enum):
    competitor = "competitor"
    own = "own"


class AdObjective(str, enum.Enum):
    sales = "sales"
    traffic = "traffic"
    leads = "leads"


class AdSourceTier(str, enum.Enum):
    """Where the metrics came from. Never mix tiers into one ranking (MI-03, OD-06)."""

    meta_api = "meta_api"
    licensed_provider = "licensed_provider"
    manual_intake = "manual_intake"


class CollaborationKind(str, enum.Enum):
    collaborator = "collaborator"
    influencer = "influencer"


class AdInsightSnapshot(Base, TenantScopedMixin, TimestampMixin):
    """One ad's metrics at a point in time.

    ``metrics`` holds explicit nulls with reasons rather than fabricated numbers (MI-03).
    """

    __tablename__ = "ad_insight_snapshots"
    __table_args__ = (
        Index(
            "ix_ad_insight_snapshots_business_id_scope_objective_synced_at",
            "business_id",
            "scope",
            "objective",
            "synced_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    account_id: Mapped[str | None] = mapped_column(String(255))
    ad_id: Mapped[str | None] = mapped_column(String(255))
    advertiser_name: Mapped[str | None] = mapped_column(String(255))
    ad_url: Mapped[str | None] = mapped_column(Text)
    objective: Mapped[str | None] = mapped_column(String(16))
    source_tier: Mapped[str] = mapped_column(String(24), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON(), nullable=False, default=dict)
    creative: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    score_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AdAccountConnection(Base, TenantScopedMixin, TimestampMixin):
    """Own Meta ad account link. Read-only scopes only (MP-01)."""

    __tablename__ = "ad_account_connections"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "provider",
            "external_account_id",
            name="uq_ad_account_connections_business_provider_account",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="meta")
    external_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    account_name: Mapped[str | None] = mapped_column(String(255))
    scopes: Mapped[list[str]] = mapped_column(JSON(), default=list, server_default="[]")
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class CollaborationSuggestion(Base, TenantScopedMixin, TimestampMixin):
    """Collaborator / influencer candidate. Display-only — no outreach (CF-03)."""

    __tablename__ = "collaboration_suggestions"
    __table_args__ = (
        Index("ix_collaboration_suggestions_business_id_kind", "business_id", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(64))
    niche: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    audience_metric: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    contact_route: Mapped[str | None] = mapped_column(Text)
    match_reasons: Mapped[dict[str, Any]] = mapped_column(JSON(), nullable=False, default=dict)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_ref: Mapped[str | None] = mapped_column(String(255))
