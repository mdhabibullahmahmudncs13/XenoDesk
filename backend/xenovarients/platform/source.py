"""The authoritative data source: the adapter interface and the shipped stub.

**The adapter is the only place that knows the source's shape.** Everything above it
reads normalised rows, so replacing a real source with the stub is a one-class
change (OD-01).

The normalised records here are deliberately plain: they carry the source's values,
not the application's. The mapping to the application's model — E.164, lowercase
emails, the qualifying flag — happens at ingest, in ``sync.py``, so the rule is
applied in exactly one place and recorded with its version.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from xenovarients.platform.identity import normalise_email, normalise_phone


@dataclass(frozen=True)
class SourceCustomer:
    """One customer as the source has them."""

    source_customer_id: str
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class SourceOrderItem:
    """One line of an order."""

    source_product_id: str
    product_name: str
    quantity: int = 1
    line_total: Decimal = Decimal("0.00")
    source_variant_id: str | None = None
    variant_name: str | None = None


@dataclass(frozen=True)
class SourceOrder:
    """One order as the source has them."""

    source_order_id: str
    source_customer_id: str
    status: str
    ordered_at: datetime
    total_amount: Decimal = Decimal("0.00")
    currency: str = "BDT"
    refund_amount: Decimal = Decimal("0.00")
    is_cancelled: bool = False
    is_returned: bool = False
    is_refunded: bool = False
    delivered_at: datetime | None = None
    items: tuple[SourceOrderItem, ...] = ()
    updated_at: datetime | None = None

    @property
    def source_status(self) -> str:
        """The status as a lowercase token the rule set can match on.

        The source may write ``"Paid"`` or ``"PAID"``; the rules are written in
        lowercase, so the comparison happens here, in one place.
        """
        return self.status.strip().lower()


@dataclass(frozen=True)
class SourceVariant:
    """One variant's inventory state."""

    source_variant_id: str
    source_product_id: str
    product_name: str
    variant_name: str
    is_available: bool = False
    stock_on_hand: int = 0
    updated_at: datetime | None = None


@dataclass(frozen=True)
class SourceProduct:
    """One product, for the catalogue."""

    source_product_id: str
    name: str
    category: str | None = None
    variants: tuple[SourceVariant, ...] = ()
    updated_at: datetime | None = None


@dataclass(frozen=True)
class Page:
    """One page of records, with the cursor for the next.

    An empty ``next_cursor`` means the source is exhausted.
    """

    records: tuple[Any, ...]
    next_cursor: str | None = None

    def __bool__(self) -> bool:
        return bool(self.records)


class CustomerOrderSource(Protocol):
    """What every source adapter must provide."""

    async def fetch_customers(self, cursor: str | None, updated_since: datetime | None) -> Page: ...

    async def fetch_orders(self, cursor: str | None, updated_since: datetime | None) -> Page: ...

    async def fetch_inventory(self, cursor: str | None) -> Page: ...


class StubSource:
    """A source that serves seeded fixtures.

    This is what makes M1 buildable and testable before the real source is
    confirmed (OD-01). The fixtures are fixed, so a test that depends on them
    depends on a known world.
    """

    def __init__(self, fixtures: "SourceFixtures | None" = None) -> None:
        self.fixtures = fixtures or default_fixtures()

    async def fetch_customers(self, cursor: str | None, updated_since: datetime | None) -> Page:
        return _paginate(
            [
                c
                for c in self.fixtures.customers
                if updated_since is None or _is_updated_after(c.updated_at, updated_since)
            ],
            cursor,
        )

    async def fetch_orders(self, cursor: str | None, updated_since: datetime | None) -> Page:
        return _paginate(
            [
                o
                for o in self.fixtures.orders
                if updated_since is None or _is_updated_after(o.updated_at, updated_since)
            ],
            cursor,
        )

    async def fetch_inventory(self, cursor: str | None) -> Page:
        return _paginate(self.fixtures.products, cursor)


@dataclass(frozen=True)
class SourceFixtures:
    """A source's world, for the stub and for tests."""

    customers: tuple[SourceCustomer, ...] = ()
    orders: tuple[SourceOrder, ...] = ()
    products: tuple[SourceProduct, ...] = ()


def _is_updated_after(updated_at: datetime | None, since: datetime) -> bool:
    """Whether a record changed after the given point.

    A record with no timestamp is treated as changed: it might be new, and missing
    it would leave the platform permanently out of date. The cost is re-reading it
    every poll, which is cheaper than never seeing it.
    """
    if updated_at is None:
        return True
    return updated_at > since


def _paginate(records: Sequence[Any], cursor: str | None) -> Page:
    """One page of records, with a cursor for the next.

    The cursor is an index into the list. A real adapter would use the source's
    own cursor; the shape is what matters, and that is what the interface pins.
    """
    start = 0
    if cursor:
        try:
            start = int(cursor)
        except ValueError:
            start = 0
    page = records[start : start + _PAGE_SIZE]
    next_cursor = str(start + _PAGE_SIZE) if start + _PAGE_SIZE < len(records) else None
    return Page(records=tuple(page), next_cursor=next_cursor)


_PAGE_SIZE = 50


def default_fixtures() -> SourceFixtures:
    """The seeded world the stub serves.

    It covers the cases the acceptance tests need: a returning customer, a
    first-time buyer, a cancelled order, a refunded order and a variant that is
    out of stock.
    """
    now = datetime(2026, 11, 1, tzinfo=UTC)
    yesterday = datetime(2026, 10, 31, tzinfo=UTC)

    return SourceFixtures(
        customers=(
            SourceCustomer(
                source_customer_id="cus-001",
                name="Nadia Rahman",
                phone="01712345678",
                email="Nadia@Example.COM",
                first_seen_at=datetime(2025, 6, 1, tzinfo=UTC),
                last_seen_at=now,
                updated_at=now,
            ),
            SourceCustomer(
                source_customer_id="cus-002",
                name="Tanvir Hasan",
                phone="+8801799999999",
                email="tanvir@example.com",
                first_seen_at=now,
                last_seen_at=now,
                updated_at=now,
            ),
            SourceCustomer(
                source_customer_id="cus-003",
                name="Old Customer",
                phone="01711111111",
                email="old@example.com",
                first_seen_at=datetime(2024, 1, 1, tzinfo=UTC),
                last_seen_at=yesterday,
                updated_at=yesterday,
            ),
        ),
        orders=(
            SourceOrder(
                source_order_id="ord-001",
                source_customer_id="cus-001",
                status="completed",
                ordered_at=datetime(2025, 6, 2, tzinfo=UTC),
                total_amount=Decimal("2400.00"),
                currency="BDT",
                delivered_at=datetime(2025, 6, 5, tzinfo=UTC),
                items=(
                    SourceOrderItem(
                        source_product_id="prod-001",
                        product_name="Kurta",
                        quantity=1,
                        line_total=Decimal("2400.00"),
                        source_variant_id="var-001",
                        variant_name="Red / M",
                    ),
                ),
                updated_at=datetime(2025, 6, 2, tzinfo=UTC),
            ),
            SourceOrder(
                source_order_id="ord-002",
                source_customer_id="cus-001",
                status="paid",
                ordered_at=datetime(2026, 10, 30, tzinfo=UTC),
                total_amount=Decimal("1200.00"),
                currency="BDT",
                items=(
                    SourceOrderItem(
                        source_product_id="prod-001",
                        product_name="Kurta",
                        quantity=1,
                        line_total=Decimal("1200.00"),
                        source_variant_id="var-001",
                        variant_name="Red / M",
                    ),
                ),
                updated_at=datetime(2026, 10, 30, tzinfo=UTC),
            ),
            SourceOrder(
                source_order_id="ord-003",
                source_customer_id="cus-002",
                status="completed",
                ordered_at=datetime(2026, 11, 1, tzinfo=UTC),
                total_amount=Decimal("900.00"),
                currency="BDT",
                items=(
                    SourceOrderItem(
                        source_product_id="prod-002",
                        product_name="Scarf",
                        quantity=1,
                        line_total=Decimal("900.00"),
                        source_variant_id="var-002",
                        variant_name="Green",
                    ),
                ),
                updated_at=datetime(2026, 11, 1, tzinfo=UTC),
            ),
            # Cancelled — does not qualify.
            SourceOrder(
                source_order_id="ord-004",
                source_customer_id="cus-001",
                status="cancelled",
                ordered_at=datetime(2026, 10, 20, tzinfo=UTC),
                total_amount=Decimal("500.00"),
                is_cancelled=True,
                updated_at=datetime(2026, 10, 20, tzinfo=UTC),
            ),
            # Fully refunded — does not qualify.
            SourceOrder(
                source_order_id="ord-005",
                source_customer_id="cus-003",
                status="refunded",
                ordered_at=datetime(2024, 1, 2, tzinfo=UTC),
                total_amount=Decimal("700.00"),
                refund_amount=Decimal("700.00"),
                is_refunded=True,
                updated_at=datetime(2024, 1, 2, tzinfo=UTC),
            ),
        ),
        products=(
            SourceProduct(
                source_product_id="prod-001",
                name="Kurta",
                category="Women",
                variants=(
                    SourceVariant(
                        source_variant_id="var-001",
                        source_product_id="prod-001",
                        product_name="Kurta",
                        variant_name="Red / M",
                        is_available=True,
                        stock_on_hand=12,
                        updated_at=now,
                    ),
                ),
                updated_at=now,
            ),
            SourceProduct(
                source_product_id="prod-002",
                name="Scarf",
                category="Accessories",
                variants=(
                    SourceVariant(
                        source_variant_id="var-002",
                        source_product_id="prod-002",
                        product_name="Scarf",
                        variant_name="Green",
                        is_available=False,
                        stock_on_hand=0,
                        updated_at=now,
                    ),
                ),
                updated_at=now,
            ),
        ),
    )


def normalised_phone(value: str | None) -> str | None:
    """The phone as the platform stores it, or None when there is none."""
    if not value:
        return None
    phone = normalise_phone(value)
    return phone or None


def normalised_email(value: str | None) -> str | None:
    """The email as the platform stores it, or None when there is none."""
    if not value:
        return None
    email = normalise_email(value)
    return email or None
