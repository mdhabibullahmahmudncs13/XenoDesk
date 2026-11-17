"""The sync job: source rows → platform rows.

**One place decides what a row means.** The source's status string is mapped to
``qualifying`` here, by the OD-02 rule set, and the rule version is written onto every
order. A later rule change re-derives the flag rather than rewriting history
silently — the version column is what makes that auditable.

**Normalisation happens here too.** Phone → E.164 and email → lowercase are applied
once, at ingest, so every read path compares like with like (CG-03's ladder depends
on it).

**Figures are recomputed, never accumulated** (CG-09). After the orders land, each
customer's totals are derived from the qualifying orders that are actually stored, so
a correction in the source propagates instead of drifting.

The sync is idempotent: the same source row maps to the same platform row, keyed on
the source's own id. Re-running a sync over the same data changes nothing.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.customer import (
    Customer,
    CustomerOrder,
    OrderItem,
    Product,
    ProductVariant,
)
from xenovarients.models.tenancy import Business
from xenovarients.platform.identity import normalise_email, normalise_phone
from xenovarients.platform.reviews import schedule_review_request
from xenovarients.platform.source import (
    CustomerOrderSource,
    Page,
    SourceCustomer,
    SourceOrder,
    SourceProduct,
)

CONFIG_DIR = Path(__file__).resolve().parents[3] / "configs"
CONFIG_FILE = CONFIG_DIR / "qualifying_order_rules.json"


@dataclass(frozen=True)
class QualifyingRules:
    """The OD-02 rule set: which orders count, and the version that decided."""

    version: str
    qualifying_statuses: frozenset[str]
    excluded_statuses: frozenset[str]
    fully_refunded_excludes: bool
    partially_refunded_counts_net: bool
    repeat_buyer_min_orders: int

    def qualifies(self, order: SourceOrder) -> bool:
        """Whether this order counts toward the customer's history.

        An order that is cancelled or returned never counts. A fully refunded order
        does not count either. A partially refunded order counts, and its amount
        counts net of the refund.
        """
        if order.is_cancelled or order.is_returned:
            return False
        if order.source_status in self.excluded_statuses:
            return False
        if self.fully_refunded_excludes and order.is_refunded:
            return False
        return order.source_status in self.qualifying_statuses


def load_rules(path: Path | None = None) -> QualifyingRules:
    """Read the qualifying-order rules from the config file."""
    target = path or CONFIG_FILE
    data = json.loads(target.read_text(encoding="utf-8"))
    refund = data.get("refund_policy", {})
    definitions = data.get("definitions", {})
    return QualifyingRules(
        version=str(data.get("version", "v1")),
        qualifying_statuses=frozenset(data.get("qualifying_statuses", [])),
        excluded_statuses=frozenset(data.get("excluded_statuses", [])),
        fully_refunded_excludes=bool(refund.get("fully_refunded_excludes_order", True)),
        partially_refunded_counts_net=bool(refund.get("partially_refunded_counts_net", True)),
        repeat_buyer_min_orders=int(
            definitions.get("repeat_buyer", {}).get("min_qualifying_orders", 2)
        ),
    )


@dataclass(frozen=True)
class SyncReport:
    """What one sync run did."""

    customers_seen: int = 0
    customers_upserted: int = 0
    orders_seen: int = 0
    orders_upserted: int = 0
    products_upserted: int = 0
    variants_upserted: int = 0
    skipped_orders: int = 0


async def sync_customers(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    source: CustomerOrderSource,
    updated_since: datetime | None = None,
) -> SyncReport:
    """Pull customers from the source and upsert them."""
    seen = 0
    upserted = 0
    for record in await _drain(_paged(source, "fetch_customers"), updated_since):
        if not isinstance(record, SourceCustomer):
            continue
        seen += 1
        await _upsert_customer(session, business_id=business_id, record=record)
        upserted += 1
    await session.flush()
    return SyncReport(customers_seen=seen, customers_upserted=upserted)


async def sync_orders(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    source: CustomerOrderSource,
    rules: QualifyingRules | None = None,
    updated_since: datetime | None = None,
) -> SyncReport:
    """Pull orders from the source, upsert them and recompute the derived figures."""
    active_rules = rules or load_rules()
    seen = 0
    upserted = 0
    skipped = 0
    business = await session.get(Business, business_id)
    if business is None:
        raise ValueError(f"Business {business_id} does not exist.")
    for record in await _drain(_paged(source, "fetch_orders"), updated_since):
        if not isinstance(record, SourceOrder):
            continue
        seen += 1
        customer = await _customer_by_source_id(
            session, business_id=business_id, source_customer_id=record.source_customer_id
        )
        if customer is None:
            # The order's customer is not in the mirror yet. Skipping it is honest;
            # inventing a placeholder customer would put a name-less row into the
            # history of whoever later claims that id.
            skipped += 1
            continue
        order = await _upsert_order(
            session, business_id=business_id, record=record, rules=active_rules
        )
        await schedule_review_request(session, business=business, order=order)
        upserted += 1
    await session.flush()
    await recompute_figures(session, business_id=business_id, rules=active_rules)
    return SyncReport(orders_seen=seen, orders_upserted=upserted, skipped_orders=skipped)


async def sync_inventory(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    source: CustomerOrderSource,
) -> SyncReport:
    """Pull products and variants from the source."""
    products = 0
    variants = 0
    for record in await _drain(_paged(source, "fetch_inventory")):
        if not isinstance(record, SourceProduct):
            continue
        product = await _upsert_product(session, business_id=business_id, record=record)
        products += 1
        for variant_record in record.variants:
            await _upsert_variant(
                session, business_id=business_id, product=product, record=variant_record
            )
            variants += 1
    await session.flush()
    return SyncReport(products_upserted=products, variants_upserted=variants)


async def recompute_figures(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    rules: QualifyingRules | None = None,
) -> None:
    """Recompute every customer's derived figures from the stored qualifying orders.

    Derived, never accumulated (CG-09): a correction in the source shows up here
    instead of being added on top of the old number.
    """
    active_rules = rules or load_rules()
    result = await session.execute(select(Customer).where(Customer.business_id == business_id))
    customers = list(result.scalars().all())

    orders_result = await session.execute(
        select(CustomerOrder).where(CustomerOrder.business_id == business_id)
    )
    orders = list(orders_result.scalars().all())

    by_customer: dict[uuid.UUID, list[CustomerOrder]] = {}
    for order in orders:
        if not order.qualifying:
            continue
        by_customer.setdefault(order.customer_id, []).append(order)

    for customer in customers:
        qualifying = by_customer.get(customer.id, [])
        customer.total_orders = len(qualifying)
        customer.total_spend = sum(
            (_net_amount(order) for order in qualifying), start=Decimal("0.00")
        )
        customer.last_purchase_at = max((order.ordered_at for order in qualifying), default=None)
        customer.is_repeat_buyer = len(qualifying) >= active_rules.repeat_buyer_min_orders
    await session.flush()


def _net_amount(order: CustomerOrder) -> Decimal:
    """The order's amount net of any refund."""
    return order.total_amount - order.refund_amount


async def _drain(fetch: Any, *args: Any) -> list[Any]:
    """Every record from a paged fetch, following the cursors to the end."""
    records: list[Any] = []
    cursor: str | None = None
    while True:
        page: Page = await fetch(cursor, *args)
        records.extend(page.records)
        cursor = page.next_cursor
        if not cursor:
            return records


def _paged(source: CustomerOrderSource, method: str) -> Any:
    """The source's fetch method, bound so it can be awaited page by page."""
    return getattr(source, method)


async def _upsert_customer(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    record: SourceCustomer,
) -> Customer:
    """Insert or update the mirror row for one source customer."""
    customer = await _customer_by_source_id(
        session, business_id=business_id, source_customer_id=record.source_customer_id
    )
    if customer is None:
        customer = Customer(
            business_id=business_id,
            source_customer_id=record.source_customer_id,
        )
        session.add(customer)

    customer.name = record.name
    customer.phone_e164 = _normalised_phone(record.phone)
    customer.email_normalised = _normalised_email(record.email)
    customer.first_seen_at = record.first_seen_at
    customer.last_seen_at = record.last_seen_at
    customer.source_updated_at = record.updated_at
    await session.flush()
    return customer


async def _upsert_order(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    record: SourceOrder,
    rules: QualifyingRules,
) -> CustomerOrder:
    """Insert or update the mirror row for one source order, and its items."""
    result = await session.execute(
        select(CustomerOrder).where(
            CustomerOrder.business_id == business_id,
            CustomerOrder.source_order_id == record.source_order_id,
        )
    )
    order = result.scalar_one_or_none()
    if order is None:
        customer = await _customer_by_source_id(
            session, business_id=business_id, source_customer_id=record.source_customer_id
        )
        if customer is None:
            raise ValueError(
                f"Order {record.source_order_id} has no mirrored customer "
                f"{record.source_customer_id}."
            )
        order = CustomerOrder(
            business_id=business_id,
            customer_id=customer.id,
            source_order_id=record.source_order_id,
            ordered_at=record.ordered_at,
            status=record.status,
        )
        session.add(order)

    order.ordered_at = record.ordered_at
    order.status = record.status
    order.qualifying = rules.qualifies(record)
    order.qualifying_rule_version = rules.version
    order.total_amount = record.total_amount
    order.currency = record.currency
    order.refund_amount = record.refund_amount
    order.is_cancelled = record.is_cancelled
    order.is_returned = record.is_returned
    order.is_refunded = record.is_refunded
    order.delivered_at = record.delivered_at
    order.source_payload = _order_payload(record)
    order.source_updated_at = record.updated_at
    await session.flush()

    await _sync_order_items(session, business_id=business_id, order=order, record=record)
    return order


async def _sync_order_items(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    order: CustomerOrder,
    record: SourceOrder,
) -> None:
    """Replace the order's items with the source's current set."""
    existing_result = await session.execute(
        select(OrderItem).where(
            OrderItem.business_id == business_id,
            OrderItem.order_id == order.id,
        )
    )
    for item in list(existing_result.scalars().all()):
        await session.delete(item)
    await session.flush()

    for source_item in record.items:
        product = await _product_by_source_id(
            session, business_id=business_id, source_product_id=source_item.source_product_id
        )
        variant = None
        if source_item.source_variant_id is not None:
            variant = await _variant_by_source_id(
                session,
                business_id=business_id,
                source_variant_id=source_item.source_variant_id,
            )
        if product is None:
            # The catalogue has not been synced yet. The item still belongs on the
            # order — the name is snapshotted so the history reads correctly — but it
            # cannot point at a product row that does not exist.
            continue
        session.add(
            OrderItem(
                business_id=business_id,
                order_id=order.id,
                product_id=product.id,
                variant_id=variant.id if variant is not None else None,
                product_name_snapshot=source_item.product_name,
                quantity=source_item.quantity,
                line_total=source_item.line_total,
            )
        )
    await session.flush()


async def _upsert_product(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    record: SourceProduct,
) -> Product:
    """Insert or update the catalogue row for one source product."""
    product = await _product_by_source_id(
        session, business_id=business_id, source_product_id=record.source_product_id
    )
    if product is None:
        product = Product(
            business_id=business_id,
            source_product_id=record.source_product_id,
            name=record.name,
        )
        session.add(product)
    product.name = record.name
    product.category = record.category
    await session.flush()
    return product


async def _upsert_variant(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    product: Product,
    record: Any,
) -> ProductVariant:
    """Insert or update the variant row for one source variant."""
    result = await session.execute(
        select(ProductVariant).where(
            ProductVariant.business_id == business_id,
            ProductVariant.source_variant_id == record.source_variant_id,
        )
    )
    variant = result.scalar_one_or_none()
    if variant is None:
        variant = ProductVariant(
            business_id=business_id,
            product_id=product.id,
            source_variant_id=record.source_variant_id,
            name=record.variant_name,
        )
        session.add(variant)
    variant.product_id = product.id
    variant.name = record.variant_name
    variant.is_available = record.is_available
    variant.stock_on_hand = record.stock_on_hand
    variant.last_inventory_sync_at = record.updated_at or datetime.now(UTC)
    await session.flush()
    return variant


async def _customer_by_source_id(
    session: AsyncSession, *, business_id: uuid.UUID, source_customer_id: str
) -> Customer | None:
    result = await session.execute(
        select(Customer).where(
            Customer.business_id == business_id,
            Customer.source_customer_id == source_customer_id,
        )
    )
    return result.scalar_one_or_none()


async def _product_by_source_id(
    session: AsyncSession, *, business_id: uuid.UUID, source_product_id: str
) -> Product | None:
    result = await session.execute(
        select(Product).where(
            Product.business_id == business_id,
            Product.source_product_id == source_product_id,
        )
    )
    return result.scalar_one_or_none()


async def _variant_by_source_id(
    session: AsyncSession, *, business_id: uuid.UUID, source_variant_id: str
) -> ProductVariant | None:
    result = await session.execute(
        select(ProductVariant).where(
            ProductVariant.business_id == business_id,
            ProductVariant.source_variant_id == source_variant_id,
        )
    )
    return result.scalar_one_or_none()


def _normalised_phone(value: str | None) -> str | None:
    if not value:
        return None
    return normalise_phone(value) or None


def _normalised_email(value: str | None) -> str | None:
    if not value:
        return None
    return normalise_email(value) or None


def _order_payload(record: SourceOrder) -> dict[str, Any]:
    """The raw source order, kept so the flag can be re-derived later.

    The rule version changes what ``qualifying`` means; the payload is what lets the
    platform answer "why was this order counted?" after the rules have moved on.
    """
    return {
        "source_order_id": record.source_order_id,
        "source_customer_id": record.source_customer_id,
        "status": record.status,
        "ordered_at": record.ordered_at.isoformat(),
        "total_amount": str(record.total_amount),
        "currency": record.currency,
        "refund_amount": str(record.refund_amount),
        "is_cancelled": record.is_cancelled,
        "is_returned": record.is_returned,
        "is_refunded": record.is_refunded,
        "items": [
            {
                "source_product_id": item.source_product_id,
                "product_name": item.product_name,
                "quantity": item.quantity,
                "line_total": str(item.line_total),
                "source_variant_id": item.source_variant_id,
                "variant_name": item.variant_name,
            }
            for item in record.items
        ],
    }
