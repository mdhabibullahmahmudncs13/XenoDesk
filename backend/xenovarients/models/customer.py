"""Customer, order and product models (M1 Customer Genome)."""

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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from xenovarients.db.base import Base, TenantScopedMixin, TimestampMixin


class OrderStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    completed = "completed"
    cancelled = "cancelled"
    returned = "returned"
    refunded = "refunded"


class Customer(Base, TenantScopedMixin, TimestampMixin):
    """Mirror of a customer from the authoritative source (CG-04)."""

    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "source_customer_id", name="uq_customers_business_id_source_customer_id"
        ),
        Index("ix_customers_business_id_phone_e164", "business_id", "phone_e164"),
        Index("ix_customers_business_id_email_normalised", "business_id", "email_normalised"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_customer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    phone_e164: Mapped[str | None] = mapped_column(String(20))
    email_normalised: Mapped[str | None] = mapped_column(String(320))
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Derived from authoritative history, recomputed on sync (CG-01, CG-09).
    total_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_spend: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    last_purchase_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_repeat_buyer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Product(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_product_id: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(255))


class ProductVariant(Base, TenantScopedMixin, TimestampMixin):
    """Restock detection reads is_available / stock_on_hand (RP-04)."""

    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "source_variant_id",
            name="uq_product_variants_business_id_source_variant_id",
        ),
        Index("ix_product_variants_business_id_product_id", "business_id", "product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    source_variant_id: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stock_on_hand: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_inventory_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CustomerOrder(Base, TenantScopedMixin, TimestampMixin):
    """Mirror of an order. `qualifying` encodes the OD-02 rule set."""

    __tablename__ = "customer_orders"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "source_order_id", name="uq_customer_orders_business_id_source_order_id"
        ),
        Index(
            "ix_customer_orders_business_id_customer_id_ordered_at",
            "business_id",
            "customer_id",
            "ordered_at",
        ),
        Index(
            "ix_customer_orders_business_id_qualifying_ordered_at",
            "business_id",
            "qualifying",
            "ordered_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    source_order_id: Mapped[str] = mapped_column(String(255), nullable=False)
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    qualifying: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    qualifying_rule_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BDT")
    refund_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    is_cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_returned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_refunded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderItem(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "order_items"
    __table_args__ = (
        Index("ix_order_items_business_id_order_id", "business_id", "order_id"),
        Index("ix_order_items_business_id_product_id", "business_id", "product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customer_orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="SET NULL")
    )
    # Name as shown on the order — the source may be gone by the time we read it (RV-13).
    product_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
