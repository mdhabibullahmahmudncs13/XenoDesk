"""The sync job: source rows → platform rows (CG-04, OD-02).

The properties worth pinning:

- Normalisation happens once, at ingest: E.164 phones, lowercase emails.
- The qualifying flag follows the OD-02 rule set, and the rule version is written
  onto every order so a later change is auditable.
- The derived figures are *recomputed*, not accumulated: a corrected order changes
  the total instead of adding to it.
- The sync is idempotent — running it twice changes nothing.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.jobs.handlers import source_sync
from xenovarients.models.customer import Customer, CustomerOrder, OrderItem, Product, ProductVariant
from xenovarients.platform.source import SourceFixtures, StubSource, default_fixtures
from xenovarients.platform.sync import (
    load_rules,
    recompute_figures,
    sync_customers,
    sync_inventory,
    sync_orders,
)

pytestmark = pytest.mark.integration


@asynccontextmanager
async def _tenant_session(factory, business_id) -> AsyncIterator[AsyncSession]:
    """A session bound to one business, closed on the way out."""
    session = await factory(business_id)
    try:
        yield session
    finally:
        await session.close()


async def _customer(session: AsyncSession, source_customer_id: str) -> Customer:
    result = await session.execute(
        select(Customer).where(Customer.source_customer_id == source_customer_id)
    )
    row = result.scalar_one_or_none()
    assert row is not None, f"customer {source_customer_id} was not synced"
    return row


async def _order(session: AsyncSession, source_order_id: str) -> CustomerOrder:
    result = await session.execute(
        select(CustomerOrder).where(CustomerOrder.source_order_id == source_order_id)
    )
    row = result.scalar_one_or_none()
    assert row is not None, f"order {source_order_id} was not synced"
    return row


@pytest.mark.asyncio
async def test_customers_are_mirrored_with_normalised_contacts(businesses, tenant_session_factory):
    """The phone becomes E.164 and the email lowercase, at ingest."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await sync_customers(session, business_id=business_one.id, source=StubSource())
        await session.commit()

        customer = await _customer(session, "cus-001")
        assert customer.phone_e164 == "+8801712345678"
        assert customer.email_normalised == "nadia@example.com"
        assert customer.name == "Nadia Rahman"


@pytest.mark.asyncio
async def test_orders_are_mirrored_with_the_qualifying_flag(businesses, tenant_session_factory):
    """A paid or completed order qualifies; a cancelled one does not."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        source = StubSource()
        await sync_customers(session, business_id=business_one.id, source=source)
        await sync_orders(session, business_id=business_one.id, source=source)
        await session.commit()

        assert (await _order(session, "ord-001")).qualifying is True
        assert (await _order(session, "ord-002")).qualifying is True
        assert (await _order(session, "ord-004")).qualifying is False


@pytest.mark.asyncio
async def test_a_fully_refunded_order_does_not_qualify(businesses, tenant_session_factory):
    """OD-02: fully refunded orders are excluded."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        source = StubSource()
        await sync_customers(session, business_id=business_one.id, source=source)
        await sync_orders(session, business_id=business_one.id, source=source)
        await session.commit()

        assert (await _order(session, "ord-005")).qualifying is False


@pytest.mark.asyncio
async def test_every_order_records_the_rule_version(businesses, tenant_session_factory):
    """The version is what makes a later rule change auditable."""
    business_one, _ = businesses
    rules = load_rules()
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        source = StubSource()
        await sync_customers(session, business_id=business_one.id, source=source)
        await sync_orders(session, business_id=business_one.id, source=source, rules=rules)
        await session.commit()

        assert (await _order(session, "ord-001")).qualifying_rule_version == rules.version


@pytest.mark.asyncio
async def test_derived_figures_count_only_qualifying_orders(businesses, tenant_session_factory):
    """Nadia has three orders, but only two of them count."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        source = StubSource()
        await sync_customers(session, business_id=business_one.id, source=source)
        await sync_orders(session, business_id=business_one.id, source=source)
        await session.commit()

        customer = await _customer(session, "cus-001")
        assert customer.total_orders == 2
        assert customer.total_spend == Decimal("3600.00")
        assert customer.last_purchase_at == datetime(2026, 10, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_a_customer_with_two_qualifying_orders_is_a_repeat_buyer(
    businesses, tenant_session_factory
):
    """Nadia has two; Tanvir has one, so he is not a repeat buyer."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        source = StubSource()
        await sync_customers(session, business_id=business_one.id, source=source)
        await sync_orders(session, business_id=business_one.id, source=source)
        await session.commit()

        assert (await _customer(session, "cus-001")).is_repeat_buyer is True
        assert (await _customer(session, "cus-002")).is_repeat_buyer is False


@pytest.mark.asyncio
async def test_the_sync_is_idempotent(businesses, tenant_session_factory):
    """Running the same sync twice must not double the history."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        source = StubSource()
        for _ in range(2):
            await sync_customers(session, business_id=business_one.id, source=source)
            await sync_orders(session, business_id=business_one.id, source=source)
        await session.commit()

        result = await session.execute(select(CustomerOrder))
        assert len(list(result.scalars().all())) == 5

        customer = await _customer(session, "cus-001")
        assert customer.total_orders == 2
        assert customer.total_spend == Decimal("3600.00")


@pytest.mark.asyncio
async def test_figures_are_recomputed_not_accumulated(businesses, tenant_session_factory):
    """A corrected order changes the total instead of adding to it (CG-09)."""
    business_one, _ = businesses
    fixtures = default_fixtures()
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        source = StubSource(fixtures)
        await sync_customers(session, business_id=business_one.id, source=source)
        await sync_orders(session, business_id=business_one.id, source=source)
        await session.commit()

        assert (await _customer(session, "cus-001")).total_spend == Decimal("3600.00")

        # The source corrects ord-002's amount. Re-syncing with the correction must
        # produce the corrected total, not the old total plus the new one.
        corrected = SourceFixtures(
            customers=fixtures.customers,
            orders=tuple(
                order.__class__(
                    source_order_id=order.source_order_id,
                    source_customer_id=order.source_customer_id,
                    status=order.status,
                    ordered_at=order.ordered_at,
                    total_amount=(
                        Decimal("1000.00")
                        if order.source_order_id == "ord-002"
                        else order.total_amount
                    ),
                    currency=order.currency,
                    refund_amount=order.refund_amount,
                    is_cancelled=order.is_cancelled,
                    is_returned=order.is_returned,
                    is_refunded=order.is_refunded,
                    delivered_at=order.delivered_at,
                    items=order.items,
                    updated_at=order.updated_at,
                )
                for order in fixtures.orders
            ),
            products=fixtures.products,
        )
        await sync_orders(session, business_id=business_one.id, source=StubSource(corrected))
        await session.commit()

        assert (await _customer(session, "cus-001")).total_spend == Decimal("3400.00")


@pytest.mark.asyncio
async def test_inventory_syncs_products_and_variants(businesses, tenant_session_factory):
    """The variant's availability is what the restock detector later watches."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await sync_inventory(session, business_id=business_one.id, source=StubSource())
        await session.commit()

        result = await session.execute(select(Product))
        products = list(result.scalars().all())
        assert {p.name for p in products} == {"Kurta", "Scarf"}

        variants_result = await session.execute(select(ProductVariant))
        variants = {v.source_variant_id: v for v in variants_result.scalars().all()}
        assert variants["var-001"].is_available is True
        assert variants["var-001"].stock_on_hand == 12
        assert variants["var-002"].is_available is False


@pytest.mark.asyncio
async def test_order_items_snapshot_the_product_name(businesses, tenant_session_factory):
    """The name is snapshotted: the source may be gone by the time we read it (RV-13)."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        source = StubSource()
        await sync_inventory(session, business_id=business_one.id, source=source)
        await sync_customers(session, business_id=business_one.id, source=source)
        await sync_orders(session, business_id=business_one.id, source=source)
        await session.commit()

        result = await session.execute(select(OrderItem))
        items = list(result.scalars().all())
        assert sorted(i.product_name_snapshot for i in items) == ["Kurta", "Kurta", "Scarf"]


@pytest.mark.asyncio
async def test_an_incremental_sync_only_reads_what_changed(businesses, tenant_session_factory):
    """``updated_since`` narrows the read: an old order is not re-ingested."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        source = StubSource()
        await sync_customers(session, business_id=business_one.id, source=source)
        await sync_orders(session, business_id=business_one.id, source=source)
        await session.commit()

        report = await sync_orders(
            session,
            business_id=business_one.id,
            source=source,
            updated_since=datetime(2026, 10, 31, tzinfo=UTC),
        )
        assert report.orders_seen == 1, "only the order changed after the cut-off was read"


@pytest.mark.asyncio
async def test_an_order_for_an_unknown_customer_is_skipped(businesses, tenant_session_factory):
    """An order whose customer is not mirrored is skipped, not invented."""
    business_one, _ = businesses
    fixtures = default_fixtures()
    without_customer = SourceFixtures(
        customers=tuple(c for c in fixtures.customers if c.source_customer_id != "cus-001"),
        orders=fixtures.orders,
        products=fixtures.products,
    )
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        source = StubSource(without_customer)
        await sync_customers(session, business_id=business_one.id, source=source)
        report = await sync_orders(session, business_id=business_one.id, source=source)
        await session.commit()

        # Nadia's three orders are skipped; the other two customers' orders still land.
        assert report.skipped_orders == 3
        result = await session.execute(select(CustomerOrder))
        assert len(list(result.scalars().all())) == 2


@pytest.mark.asyncio
async def test_the_sync_does_not_write_to_another_tenant(businesses, tenant_session_factory):
    """Two businesses sync the same source; each keeps its own mirror."""
    business_one, business_two = businesses
    source = StubSource()

    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await sync_customers(session, business_id=business_one.id, source=source)
        await session.commit()

    async with _tenant_session(tenant_session_factory, business_two.id) as session:
        await sync_customers(session, business_id=business_two.id, source=source)
        await session.commit()

        result = await session.execute(select(Customer))
        customers = list(result.scalars().all())
        assert len(customers) == 3
        assert {c.business_id for c in customers} == {business_two.id}


@pytest.mark.asyncio
async def test_recompute_figures_leaves_non_qualifying_orders_out(
    businesses, tenant_session_factory
):
    """The recompute is the same derivation the sync uses, and it is idempotent."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        source = StubSource()
        await sync_customers(session, business_id=business_one.id, source=source)
        await sync_orders(session, business_id=business_one.id, source=source)
        await session.commit()

        await recompute_figures(session, business_id=business_one.id)
        await session.commit()

        customer = await _customer(session, "cus-001")
        assert customer.total_orders == 2
        assert customer.total_spend == Decimal("3600.00")


@pytest.mark.asyncio
async def test_the_source_sync_job_handler_mirrors_the_source(businesses, tenant_session_factory):
    """The handler is the path the scheduler takes, so it has to work."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await source_sync(session, {"business_id": business_one.id})
        await session.commit()

        customer = await _customer(session, "cus-001")
        assert customer.total_orders == 2
        assert customer.total_spend == Decimal("3600.00")

        result = await session.execute(select(Product))
        assert len(list(result.scalars().all())) == 2


@pytest.mark.asyncio
async def test_the_source_sync_job_handler_without_a_business_id_raises(
    businesses, tenant_session_factory
):
    """A payload with no business is a bug, not a silent no-op."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        with pytest.raises(ValueError):
            await source_sync(session, {})
