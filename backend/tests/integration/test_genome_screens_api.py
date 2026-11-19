"""The Customer Genome screens' API surface (CG-01, CG-03, RP-02, RP-04, RP-05, RP-09).

These pin the reads the screens depend on beyond the original module endpoints:

- the customer directory searches every customer and flags repeat buyers;
- the product catalogue carries the variants a waiting-list entry needs;
- restock events carry the waiting demand and whether a batch was confirmed;
- the restock template defaults, versions on change, and refuses reservation language;
- a preview works before the owner has saved a template, without writing one.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.customer import Customer, Product, ProductVariant
from xenovarients.models.outbound import MessageTemplate
from xenovarients.models.restock import ProductInterest, RestockEvent

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


async def _seed(session: AsyncSession, business_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Two customers, one product+variant, two interests and one restock event."""
    first = Customer(
        business_id=business_id,
        source_customer_id=f"src-{uuid.uuid4().hex[:8]}",
        name="Ayesha",
        email_normalised="ayesha@example.com",
        phone_e164="+8801700000001",
    )
    second = Customer(
        business_id=business_id,
        source_customer_id=f"src-{uuid.uuid4().hex[:8]}",
        name="Tanvir",
        email_normalised="tanvir@example.com",
        phone_e164="+8801700000002",
    )
    session.add_all([first, second])
    await session.flush()

    product = Product(
        business_id=business_id,
        source_product_id=f"prod-{uuid.uuid4().hex[:8]}",
        name="Kurta",
    )
    session.add(product)
    await session.flush()

    variant = ProductVariant(
        business_id=business_id,
        product_id=product.id,
        source_variant_id=f"var-{uuid.uuid4().hex[:8]}",
        name="Red / M",
        is_available=True,
        stock_on_hand=5,
    )
    session.add(variant)
    await session.flush()

    session.add_all(
        [
            ProductInterest(
                business_id=business_id,
                customer_id=first.id,
                product_id=product.id,
                variant_id=variant.id,
                requested_at=datetime.now(UTC),
                contact_channel="email",
                contact_value=first.email_normalised,
                source="staff",
            ),
            ProductInterest(
                business_id=business_id,
                customer_id=second.id,
                product_id=product.id,
                variant_id=variant.id,
                requested_at=datetime.now(UTC),
                contact_channel="email",
                contact_value=second.email_normalised,
                source="staff",
            ),
        ]
    )
    event = RestockEvent(
        business_id=business_id,
        product_id=product.id,
        variant_id=variant.id,
        detected_at=datetime.now(UTC),
        stock_after=5,
        source="poll",
        source_ref=f"var@{uuid.uuid4().hex[:8]}",
    )
    session.add(event)
    await session.flush()
    return {"event": event.id, "product": product.id, "variant": variant.id}


@pytest.mark.asyncio
async def test_the_directory_searches_every_customer_by_name_and_phone(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed(session, business_one.id)
        await session.commit()

    token = await _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    all_customers = await client.get(
        "/api/v1/customer-genome/customers", headers=headers
    )
    assert all_customers.status_code == 200, all_customers.text
    assert {item["name"] for item in all_customers.json()["items"]} == {"Ayesha", "Tanvir"}

    by_name = await client.get(
        "/api/v1/customer-genome/customers?q=ayesha", headers=headers
    )
    assert [item["name"] for item in by_name.json()["items"]] == ["Ayesha"]
    assert by_name.json()["items"][0]["is_repeat_buyer"] is False

    by_phone = await client.get(
        "/api/v1/customer-genome/customers?q=8801700000002", headers=headers
    )
    assert [item["name"] for item in by_phone.json()["items"]] == ["Tanvir"]


@pytest.mark.asyncio
async def test_the_catalogue_lists_variants_for_the_waiting_list_form(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed(session, business_one.id)
        await session.commit()

    token = await _login(client)
    response = await client.get(
        "/api/v1/customer-genome/products", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text
    product = response.json()["items"][0]
    assert product["name"] == "Kurta"
    assert [variant["name"] for variant in product["variants"]] == ["Red / M"]
    assert product["variants"][0]["stock_on_hand"] == 5


@pytest.mark.asyncio
async def test_restock_events_report_waiting_demand_and_batch_state(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed(session, business_one.id)
        await session.commit()

    token = await _login(client)
    response = await client.get(
        "/api/v1/customer-genome/restocks", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text
    events = response.json()["items"]
    assert len(events) == 1
    assert events[0]["product_name"] == "Kurta"
    assert events[0]["waiting_count"] == 2
    assert events[0]["batch_count"] == 0
    assert events[0]["preview_url"].startswith("/customer-genome/restock-events/")


@pytest.mark.asyncio
async def test_the_template_defaults_then_versions_on_change(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    business_one, _ = businesses
    token = await _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    default = await client.get(
        "/api/v1/customer-genome/restock-template", headers=headers
    )
    assert default.status_code == 200, default.text
    assert default.json()["is_default"] is True
    assert default.json()["id"] is None

    first = await client.put(
        "/api/v1/customer-genome/restock-template",
        json={"body": "Hi {{customer_name}}, {{product_name}} is back at {{business_name}}."},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 1
    assert first.json()["is_default"] is False

    second = await client.put(
        "/api/v1/customer-genome/restock-template",
        json={"body": "Hello {{customer_name}}, {{product_name}} is available again."},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["version"] == 2

    async with _tenant_session(tenant_session_factory, business_one.id) as check:
        rows = (
            await check.execute(
                select(MessageTemplate).where(MessageTemplate.business_id == business_one.id)
            )
        ).scalars().all()
    assert sum(1 for row in rows if row.is_active) == 1

    refused = await client.put(
        "/api/v1/customer-genome/restock-template",
        json={"body": "Your {{product_name}} is guaranteed. It is reserved for you."},
        headers=headers,
    )
    assert refused.status_code == 400, refused.text


@pytest.mark.asyncio
async def test_a_preview_works_before_a_template_is_saved_and_writes_none(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as tenant_session:
        seeded = await _seed(tenant_session, business_one.id)
        await tenant_session.commit()

    token = await _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get(
        f"/api/v1/customer-genome/restocks/{seeded['event']}/preview", headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["waiting_count"] == 2
    assert "Kurta" in body["recipients"][0]["message"]
    assert "Business One" in body["recipients"][0]["message"]

    async with _tenant_session(tenant_session_factory, business_one.id) as check:
        templates = (
            await check.execute(
                select(MessageTemplate).where(MessageTemplate.business_id == business_one.id)
            )
        ).scalars().all()
    assert templates == []
