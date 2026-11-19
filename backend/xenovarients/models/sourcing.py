import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from xenovarients.db.base import Base, TenantScopedMixin, TimestampMixin


class SourcingProfile(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "sourcing_profiles"
    __table_args__ = (
        UniqueConstraint("business_id", name="uq_sourcing_profiles_business_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    business_type: Mapped[str | None] = mapped_column(String(64))
    location: Mapped[str | None] = mapped_column(String(128))
    product_idea: Mapped[str | None] = mapped_column(String(255))
    investment_budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    team_size: Mapped[str | None] = mapped_column(String(32))
    account_type: Mapped[str | None] = mapped_column(String(32))
    experience: Mapped[str | None] = mapped_column(String(32))
    sales_channels: Mapped[list[str]] = mapped_column(JSON(), nullable=False, default=list)


class TrackedProduct(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "tracked_products"
    __table_args__ = (
        UniqueConstraint("business_id", "keyword", name="uq_tracked_products_business_keyword"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="tracking")


class MarketSnapshot(Base, TenantScopedMixin, TimestampMixin):
    """One Market Intelligence reading for a keyword.

    The payload is the computed result the screen renders, stored whole so a snapshot
    is reproducible and the UI never has to recompute (or re-call a provider) to show
    what was seen at capture time.
    """

    __tablename__ = "market_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    keyword: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quality_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON(), nullable=False)


class SourcingCartListing(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "sourcing_cart_listings"
    __table_args__ = (
        UniqueConstraint("business_id", "listing_id", name="uq_sourcing_cart_business_listing"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    listing_id: Mapped[str] = mapped_column(String(255), nullable=False)
    marketplace: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="BDT")
    shipping_estimate: Mapped[str | None] = mapped_column(String(255))
