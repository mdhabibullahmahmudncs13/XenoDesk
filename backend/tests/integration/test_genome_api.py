"""The Customer Genome read endpoints (CG-01, CG-02, CG-03, CG-09).

The properties worth pinning:

- A customer with **one** qualifying order is returning but **absent** from Repeat
  Buyers; at two orders they appear (CG-T08's list half).
- The figures come from the authoritative history at read time, not from a counter.
- The history filters by date and by product.
- The endpoints are tenant-scoped: another business's customer is not found.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.customer import Customer, CustomerOrder, Product
from xenovarients.platform.source import StubSource
from xenovarients.platform.sync import sync_customers, sync_inventory, sync_orders

pytestmark = pytest.mark.integration


@asynccontextmanager
async def _tenant_session(factory, business_id) -> AsyncIterator[AsyncSession]:
    """A session bound to one business, closed on the way out."""
    session = await factory(business_id)
    try:
        yield session
    finally:
        await session.close()


async def _login(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "correct-horse-battery"},
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


async def _seed_source(session: AsyncSession, business_id: uuid.UUID) -> None:
    """Run the stub source into the mirror."""
    source = StubSource()
    await sync_inventory(session, business_id=business_id, source=source)
    await sync_customers(session, business_id=business_id, source=source)
    await sync_orders(session, business_id=business_id, source=source)


@pytest.mark.asyncio
async def test_the_repeat_buyers_list_holds_only_two_order_customers(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    """Nadia has two qualifying orders; Tanvir has one, so he is not listed (CG-T08)."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)
        await session.commit()

    token = await _login(client)
    response = await client.get(
        "/api/v1/customer-genome/repeat-buyers", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text
    body = response.json()

    names = [item["name"] for item in body["items"]]
    assert names == ["Nadia Rahman"]
    assert body["items"][0]["order_count"] == 2
    assert body["items"][0]["total_spend"] == "3600.00"


@pytest.mark.asyncio
async def test_a_customer_with_one_order_is_absent_from_the_repeat_buyers(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    """The threshold is two, not one — the bubble threshold is the one that is one."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)
        await session.commit()

        result = await session.execute(
            select(Customer).where(Customer.source_customer_id == "cus-002")
        )
        tanvir = result.scalar_one()

    token = await _login(client)
    response = await client.get(
        "/api/v1/customer-genome/repeat-buyers", headers={"Authorization": f"Bearer {token}"}
    )
    ids = {item["id"] for item in response.json()["items"]}
    assert str(tanvir.id) not in ids


@pytest.mark.asyncio
async def test_the_repeat_buyers_list_is_cursor_paginated(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    """The cursor walks the list without repeating or skipping a row.

    The list is derived from the orders, so a second qualifying order is what
    puts a customer on it — not a flag on the customer row.
    """
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)
        await session.commit()

        result = await session.execute(select(Customer))
        customers = list(result.scalars().all())
        for offset, customer in enumerate(customers):
            for index in range(2):
                session.add(
                    CustomerOrder(
                        business_id=business_one.id,
                        customer_id=customer.id,
                        source_order_id=f"extra-{offset}-{index}",
                        ordered_at=datetime(2026, 11, 1, tzinfo=UTC)
                        - timedelta(days=offset, minutes=index),
                        status="completed",
                        qualifying=True,
                        total_amount=Decimal("1000.00"),
                    )
                )
        await session.commit()

    token = await _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.get(
        "/api/v1/customer-genome/repeat-buyers", params={"limit": 1}, headers=headers
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["items"]) == 1
    assert body["next_cursor"]

    second = await client.get(
        "/api/v1/customer-genome/repeat-buyers",
        params={"limit": 1, "cursor": body["next_cursor"]},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["items"][0]["id"] != body["items"][0]["id"]


@pytest.mark.asyncio
async def test_the_history_shows_the_timeline_and_the_figures(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    """The history endpoint carries the derived figures alongside the timeline."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)
        await session.commit()

        result = await session.execute(
            select(Customer).where(Customer.source_customer_id == "cus-001")
        )
        customer = result.scalar_one()

    token = await _login(client)
    response = await client.get(
        f"/api/v1/customers/{customer.id}/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["order_count"] == 2
    assert body["total_spend"] == "3600.00"
    assert body["currency"] == "BDT"
    assert body["data_as_of"]
    # The timeline shows every order, including the cancelled one; the *figures*
    # count only the qualifying ones.
    assert len(body["items"]) == 3
    assert body["items"][0]["items"][0]["product_name"] == "Kurta"
    assert sum(1 for item in body["items"] if not item["qualifying"]) == 1


@pytest.mark.asyncio
async def test_the_history_filters_by_date(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    """A date filter narrows the timeline."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)
        await session.commit()

        result = await session.execute(
            select(Customer).where(Customer.source_customer_id == "cus-001")
        )
        customer = result.scalar_one()

    token = await _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    # Nadia's three orders are dated 2025-06-02, 2026-10-20 and 2026-10-30.
    recent = await client.get(
        f"/api/v1/customers/{customer.id}/history",
        params={"since": "2026-10-01T00:00:00+00:00"},
        headers=headers,
    )
    assert recent.status_code == 200, recent.text
    assert len(recent.json()["items"]) == 2

    old = await client.get(
        f"/api/v1/customers/{customer.id}/history",
        params={"until": "2025-12-31T00:00:00+00:00"},
        headers=headers,
    )
    assert old.status_code == 200, old.text
    assert len(old.json()["items"]) == 1


@pytest.mark.asyncio
async def test_the_history_filters_by_product(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    """The product filter keeps the orders that contained the product."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)
        await session.commit()

        result = await session.execute(select(Product).where(Product.name == "Scarf"))
        scarf = result.scalar_one()

        result = await session.execute(
            select(Customer).where(Customer.source_customer_id == "cus-002")
        )
        customer = result.scalar_one()

    token = await _login(client)
    response = await client.get(
        f"/api/v1/customers/{customer.id}/history",
        params={"product_id": str(scarf.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["items"][0]["product_name"] == "Scarf"


@pytest.mark.asyncio
async def test_the_figures_reflect_a_correction_in_the_source(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    """CG-09: the figures are recomputed at read time, so a correction shows up."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)
        await session.commit()

        result = await session.execute(
            select(CustomerOrder).where(CustomerOrder.source_order_id == "ord-002")
        )
        order = result.scalar_one()
        order.total_amount = Decimal("1.00")
        await session.commit()

        result = await session.execute(
            select(Customer).where(Customer.source_customer_id == "cus-001")
        )
        customer = result.scalar_one()

    token = await _login(client)
    response = await client.get(
        f"/api/v1/customers/{customer.id}/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["total_spend"] == "2401.00"


@pytest.mark.asyncio
async def test_the_history_of_another_tenants_customer_is_not_found(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    """A customer id from another business is a 404, not someone else's history."""
    business_one, business_two = businesses

    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)
        await session.commit()

    async with _tenant_session(tenant_session_factory, business_two.id) as session:
        other_customer = Customer(
            business_id=business_two.id,
            source_customer_id="cus-001",
            name="Someone Else",
        )
        session.add(other_customer)
        await session.commit()

    # The owner belongs to business one, so business two's customer is not theirs.
    token = await _login(client)
    response = await client.get(
        f"/api/v1/customers/{other_customer.id}/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_staff_can_link_an_identity_to_a_customer(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    """The staff "Link customer" action (CG-03, CG-10)."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)
        await session.commit()

        result = await session.execute(
            select(Customer).where(Customer.source_customer_id == "cus-001")
        )
        customer = result.scalar_one()

    token = await _login(client)
    response = await client.post(
        f"/api/v1/customers/{customer.id}/link-identity",
        json={"channel": "messenger", "channel_user_id": "page-scoped-id-123"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["channel"] == "messenger"
    assert body["customer_id"] == str(customer.id)
    assert body["method"] == "staff_link"


@pytest.mark.asyncio
async def test_linking_the_same_identity_twice_is_idempotent(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    """Re-linking the same identity to the same customer changes nothing."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)
        await session.commit()

        result = await session.execute(
            select(Customer).where(Customer.source_customer_id == "cus-001")
        )
        customer = result.scalar_one()

    token = await _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    body = {"channel": "messenger", "channel_user_id": "page-scoped-id-123"}

    first = await client.post(
        f"/api/v1/customers/{customer.id}/link-identity", json=body, headers=headers
    )
    second = await client.post(
        f"/api/v1/customers/{customer.id}/link-identity", json=body, headers=headers
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.asyncio
async def test_an_unauthenticated_caller_gets_nothing(
    client: AsyncClient, businesses, users_and_memberships
):
    """No token, no customer data."""
    business_one, _ = businesses
    response = await client.get("/api/v1/customer-genome/repeat-buyers")
    assert response.status_code == 401
