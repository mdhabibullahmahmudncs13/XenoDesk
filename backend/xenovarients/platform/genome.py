"""The M1 read service: repeat buyers, customer history and the live figures.

**The figures are recomputed, not read from a counter** (CG-09). The bubble card and
the Repeat Buyers list both show "this customer has bought N times and spent X" —
and that number has to come from the authoritative history every time, so a
correction in the source shows up rather than drifting.

**A customer with one qualifying order is returning but not a repeat buyer.** The
two thresholds are different on purpose: the bubble needs one prior order, the list
needs two (OD-02). Getting that backwards is the mistake this module makes
impossible: the two thresholds are named, not inlined.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.customer import (
    Customer,
    CustomerOrder,
    OrderItem,
    Product,
    ProductVariant,
)
from xenovarients.platform.sync import load_rules

# The thresholds. Named, because the difference between them is the whole point.
RETURNING_MIN_ORDERS = 1
REPEAT_BUYER_MIN_ORDERS = 2


@dataclass(frozen=True)
class CustomerFigures:
    """A customer's figures, derived from their qualifying orders."""

    order_count: int
    total_spend: Decimal
    currency: str
    last_purchase_at: datetime | None
    data_as_of: datetime

    @property
    def is_returning_customer(self) -> bool:
        """One prior qualifying order is enough for the "Returning Customer" label."""
        return self.order_count >= RETURNING_MIN_ORDERS

    @property
    def is_repeat_buyer(self) -> bool:
        """Two or more — the Repeat Buyers list."""
        return self.order_count >= REPEAT_BUYER_MIN_ORDERS


@dataclass(frozen=True)
class HistoryEntry:
    """One order in a customer's timeline."""

    order_id: str
    source_order_id: str
    ordered_at: datetime
    status: str
    qualifying: bool
    total_amount: Decimal
    refund_amount: Decimal
    currency: str
    items: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class HistoryPage:
    """A page of a customer's order timeline."""

    entries: tuple[HistoryEntry, ...]
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True)
class RepeatBuyer:
    """One row of the Repeat Buyers list."""

    customer_id: uuid.UUID
    name: str | None
    phone_e164: str | None
    email_normalised: str | None
    order_count: int
    total_spend: Decimal
    currency: str
    last_purchase_at: datetime | None


async def customer_figures(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    customer_id: uuid.UUID,
    as_of: datetime | None = None,
) -> CustomerFigures:
    """A customer's figures, derived from their qualifying orders.

    ``as_of`` is the moment the figures were true up to. It is the caller's clock
    when not given — the bubble card shows it so a stale figure is visibly stale.
    """
    moment = as_of or datetime.now(UTC)

    result = await session.execute(
        select(
            func.count(CustomerOrder.id),
            func.coalesce(func.sum(CustomerOrder.total_amount - CustomerOrder.refund_amount), 0),
            func.max(CustomerOrder.ordered_at),
        ).where(
            CustomerOrder.business_id == business_id,
            CustomerOrder.customer_id == customer_id,
            CustomerOrder.qualifying.is_(True),
        )
    )
    count, spend, last_purchase = result.one()

    currency = await _currency_for(session, business_id=business_id, customer_id=customer_id)

    return CustomerFigures(
        order_count=int(count or 0),
        total_spend=Decimal(str(spend or 0)).quantize(Decimal("0.01")),
        currency=currency,
        last_purchase_at=last_purchase,
        data_as_of=moment,
    )


async def _currency_for(
    session: AsyncSession, *, business_id: uuid.UUID, customer_id: uuid.UUID
) -> str:
    """The currency of the customer's most recent order."""
    result = await session.execute(
        select(CustomerOrder.currency)
        .where(
            CustomerOrder.business_id == business_id,
            CustomerOrder.customer_id == customer_id,
        )
        .order_by(CustomerOrder.ordered_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none() or "BDT"


async def repeat_buyers(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    limit: int = 25,
    cursor: str | None = None,
    name_contains: str | None = None,
    since: datetime | None = None,
) -> tuple[list[RepeatBuyer], str | None]:
    """The Repeat Buyers list, newest purchase first.

    A repeat buyer is a customer with **two or more qualifying orders** (OD-02). The
    list is built from a join with the orders rather than from the customer's cached
    counter, so a customer whose orders have been corrected appears or disappears
    from the list accordingly.
    """
    from xenovarients.api.pagination import decode_cursor, encode_cursor

    conditions = [Customer.business_id == business_id, CustomerOrder.qualifying.is_(True)]
    if name_contains:
        conditions.append(Customer.name.ilike(f"%{name_contains}%"))

    if since is not None:
        conditions.append(CustomerOrder.ordered_at >= since)

    having = func.count(CustomerOrder.id) >= REPEAT_BUYER_MIN_ORDERS

    query = (
        select(
            Customer.id,
            Customer.name,
            Customer.phone_e164,
            Customer.email_normalised,
            func.count(CustomerOrder.id),
            func.coalesce(func.sum(CustomerOrder.total_amount - CustomerOrder.refund_amount), 0),
            func.max(CustomerOrder.ordered_at),
            func.max(CustomerOrder.currency),
        )
        .join(CustomerOrder, CustomerOrder.customer_id == Customer.id)
        .where(*conditions)
        .group_by(Customer.id)
        .having(having)
        .order_by(func.max(CustomerOrder.ordered_at).desc(), Customer.id)
    )

    after = decode_cursor(cursor)
    if after is not None:
        last_purchase = datetime.fromisoformat(after.value)
        # The cursor compares against the customer's *latest* qualifying order, which
        # is an aggregate — so it has to be computed in a subquery rather than in the
        # outer WHERE, where Postgres rejects an aggregate.
        last_purchase_per_customer = (
            select(
                CustomerOrder.customer_id.label("customer_id"),
                func.max(CustomerOrder.ordered_at).label("last_purchase_at"),
            )
            .where(
                CustomerOrder.business_id == business_id,
                CustomerOrder.qualifying.is_(True),
            )
            .group_by(CustomerOrder.customer_id)
            .subquery()
        )
        query = query.join(
            last_purchase_per_customer,
            last_purchase_per_customer.c.customer_id == Customer.id,
        )
        query = query.where(
            (last_purchase_per_customer.c.last_purchase_at < last_purchase)
            | (
                (last_purchase_per_customer.c.last_purchase_at == last_purchase)
                & (Customer.id > uuid.UUID(after.id))
            )
        )

    query = query.limit(limit + 1)
    rows = (await session.execute(query)).all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    buyers = [
        RepeatBuyer(
            customer_id=row[0],
            name=row[1],
            phone_e164=row[2],
            email_normalised=row[3],
            order_count=int(row[4]),
            total_spend=Decimal(str(row[5] or 0)).quantize(Decimal("0.01")),
            currency=row[7] or "BDT",
            last_purchase_at=row[6],
        )
        for row in rows
    ]

    next_cursor = None
    if has_more and buyers:
        last = buyers[-1]
        if last.last_purchase_at is not None:
            next_cursor = encode_cursor(last.last_purchase_at.isoformat(), last.customer_id)

    return buyers, next_cursor


async def customer_history(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    customer_id: uuid.UUID,
    limit: int = 25,
    cursor: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    product_id: uuid.UUID | None = None,
) -> HistoryPage:
    """A customer's order timeline, newest first, with date and product filters.

    The product filter matches an order that *contains* the product, so filtering
    by a product narrows the timeline to the orders that included it rather than
    dropping the items from the orders that did.
    """
    from xenovarients.api.pagination import decode_cursor, encode_cursor

    conditions = [
        CustomerOrder.business_id == business_id,
        CustomerOrder.customer_id == customer_id,
    ]
    if since is not None:
        conditions.append(CustomerOrder.ordered_at >= since)
    if until is not None:
        conditions.append(CustomerOrder.ordered_at <= until)
    if product_id is not None:
        # The order must contain the product. A join, not a filter on the item list.
        matching = (
            select(OrderItem.order_id)
            .where(
                OrderItem.business_id == business_id,
                OrderItem.product_id == product_id,
            )
            .scalar_subquery()
        )
        conditions.append(CustomerOrder.id.in_(matching))

    query = (
        select(CustomerOrder)
        .where(*conditions)
        .order_by(CustomerOrder.ordered_at.desc(), CustomerOrder.id)
    )

    after = decode_cursor(cursor)
    if after is not None:
        last_ordered = datetime.fromisoformat(after.value)
        query = query.where(
            (CustomerOrder.ordered_at < last_ordered)
            | (
                (CustomerOrder.ordered_at == last_ordered)
                & (CustomerOrder.id < uuid.UUID(after.id))
            )
        )

    query = query.limit(limit + 1)
    orders = list((await session.execute(query)).scalars().all())

    has_more = len(orders) > limit
    orders = orders[:limit]

    entries: list[HistoryEntry] = []
    for order in orders:
        items = await _items_for(session, business_id=business_id, order_id=order.id)
        entries.append(
            HistoryEntry(
                order_id=str(order.id),
                source_order_id=order.source_order_id,
                ordered_at=order.ordered_at,
                status=order.status,
                qualifying=order.qualifying,
                total_amount=order.total_amount,
                refund_amount=order.refund_amount,
                currency=order.currency,
                items=items,
            )
        )

    next_cursor = None
    if has_more and entries:
        last = entries[-1]
        next_cursor = encode_cursor(last.ordered_at.isoformat(), last.order_id)

    return HistoryPage(
        entries=tuple(entries),
        next_cursor=next_cursor,
        has_more=has_more,
    )


async def _items_for(
    session: AsyncSession, *, business_id: uuid.UUID, order_id: uuid.UUID
) -> tuple[dict[str, Any], ...]:
    """One order's line items, with the product and variant names."""
    result = await session.execute(
        select(
            OrderItem,
        )
        .where(
            OrderItem.business_id == business_id,
            OrderItem.order_id == order_id,
        )
        .order_by(OrderItem.id)
    )
    items: list[dict[str, Any]] = []
    for (item,) in result.all():
        items.append(
            {
                "product_name": item.product_name_snapshot,
                "quantity": item.quantity,
                "line_total": str(item.line_total),
                "product_id": str(item.product_id),
                "variant_id": str(item.variant_id) if item.variant_id else None,
            }
        )
    return tuple(items)


def repeat_buyer_threshold() -> int:
    """The Repeat Buyers threshold, from the rule set rather than a literal."""
    return max(REPEAT_BUYER_MIN_ORDERS, load_rules().repeat_buyer_min_orders)


@dataclass(frozen=True)
class DirectoryEntry:
    """One customer in the searchable directory.

    Every customer is listed, not only repeat buyers: staff need to reach a
    first-time buyer to add them to a waiting list, and the history page is where
    their (possibly empty) timeline lives.
    """

    customer_id: uuid.UUID
    name: str | None
    phone_e164: str | None
    email_normalised: str | None
    order_count: int
    total_spend: Decimal
    currency: str
    last_purchase_at: datetime | None

    @property
    def is_repeat_buyer(self) -> bool:
        return self.order_count >= REPEAT_BUYER_MIN_ORDERS


async def customer_directory(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    query: str | None = None,
    limit: int = 25,
) -> tuple[list[DirectoryEntry], bool]:
    """Search customers by name, phone or normalised email (CG-03).

    The figures come from the same derived join as the Repeat Buyers list, so a
    customer's order count here matches the list and the bubble card.
    """
    conditions = [Customer.business_id == business_id]
    if query and query.strip():
        needle = f"%{query.strip()}%"
        conditions.append(
            func.coalesce(Customer.name, "").ilike(needle)
            | func.coalesce(Customer.phone_e164, "").ilike(needle)
            | func.coalesce(Customer.email_normalised, "").ilike(needle)
        )

    rows = (
        await session.execute(
            select(
                Customer.id,
                Customer.name,
                Customer.phone_e164,
                Customer.email_normalised,
                func.count(CustomerOrder.id),
                func.coalesce(
                    func.sum(CustomerOrder.total_amount - CustomerOrder.refund_amount), 0
                ),
                func.max(CustomerOrder.ordered_at),
                func.max(CustomerOrder.currency),
            )
            .outerjoin(
                CustomerOrder,
                and_(
                    CustomerOrder.customer_id == Customer.id,
                    CustomerOrder.qualifying.is_(True),
                ),
            )
            .where(*conditions)
            .group_by(Customer.id)
            .order_by(func.max(CustomerOrder.ordered_at).desc().nulls_last(), Customer.name)
            .limit(limit + 1)
        )
    ).all()

    has_more = len(rows) > limit
    entries = [
        DirectoryEntry(
            customer_id=row[0],
            name=row[1],
            phone_e164=row[2],
            email_normalised=row[3],
            order_count=int(row[4] or 0),
            total_spend=Decimal(str(row[5] or 0)).quantize(Decimal("0.01")),
            last_purchase_at=row[6],
            currency=row[7] or "BDT",
        )
        for row in rows[:limit]
    ]
    return entries, has_more


@dataclass(frozen=True)
class CatalogueVariant:
    """One product variant, as the waiting-list form needs it."""

    variant_id: uuid.UUID
    name: str
    is_available: bool
    stock_on_hand: int


@dataclass(frozen=True)
class CatalogueProduct:
    """One product with its variants (RP-02: interest is per variant)."""

    product_id: uuid.UUID
    name: str
    category: str | None
    variants: tuple[CatalogueVariant, ...]


async def product_catalogue(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    query: str | None = None,
    limit: int = 50,
) -> list[CatalogueProduct]:
    """The products and variants staff can add a customer to (RP-02)."""
    conditions = [Product.business_id == business_id]
    if query and query.strip():
        conditions.append(Product.name.ilike(f"%{query.strip()}%"))

    rows = (
        await session.execute(
            select(
                Product.id,
                Product.name,
                Product.category,
                ProductVariant.id,
                ProductVariant.name,
                ProductVariant.is_available,
                ProductVariant.stock_on_hand,
            )
            .outerjoin(
                ProductVariant,
                and_(
                    ProductVariant.product_id == Product.id,
                    ProductVariant.business_id == business_id,
                ),
            )
            .where(*conditions)
            .order_by(Product.name, ProductVariant.name)
            .limit(limit * 20)
        )
    ).all()

    products: dict[uuid.UUID, dict[str, Any]] = {}
    for product_id, product_name, category, variant_id, variant_name, available, stock in rows:
        entry = products.setdefault(
            product_id,
            {"name": product_name, "category": category, "variants": []},
        )
        if variant_id is not None:
            entry["variants"].append(
                CatalogueVariant(
                    variant_id=variant_id,
                    name=variant_name,
                    is_available=bool(available),
                    stock_on_hand=int(stock or 0),
                )
            )

    return [
        CatalogueProduct(
            product_id=product_id,
            name=entry["name"],
            category=entry["category"],
            variants=tuple(entry["variants"]),
        )
        for product_id, entry in list(products.items())[:limit]
    ]
