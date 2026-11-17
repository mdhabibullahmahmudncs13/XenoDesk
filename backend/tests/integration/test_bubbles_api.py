"""The Returning Customer Bubbles endpoints (CG-05…CG-08, CG-11).

The platform layer is covered in ``test_bubbles.py``. These tests cover the HTTP
surface: what the dashboard card carries, and the ``seen``/``dismiss`` actions.

The properties worth pinning:

- The card carries the figures and a link to the history.
- ``seen`` and ``dismissed`` are the two states a client can ask for.
- A bubble from another business is not found.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.customer import Customer
from xenovarients.models.messaging import InboundMessageEvent
from xenovarients.platform.bubbles import process_inbound_event
from xenovarients.platform.identity import link
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


async def _seed_bubble(session: AsyncSession, business_id: uuid.UUID) -> uuid.UUID:
    """Sync the stub source and message from a linked returning customer."""
    source = StubSource()
    await sync_inventory(session, business_id=business_id, source=source)
    await sync_customers(session, business_id=business_id, source=source)
    await sync_orders(session, business_id=business_id, source=source)

    result = await session.execute(select(Customer).where(Customer.source_customer_id == "cus-001"))
    customer = result.scalar_one()
    await link(
        session,
        business_id=business_id,
        channel="messenger",
        channel_user_id="messenger-nadia",
        customer_id=customer.id,
    )

    event = InboundMessageEvent(
        business_id=business_id,
        provider_event_id=f"evt-{uuid.uuid4().hex[:12]}",
        channel="messenger",
        channel_user_id="messenger-nadia",
        conversation_id="conv-1",
        direction="inbound",
        content="Is my order ready?",
        received_at=datetime(2026, 11, 16, 9, 12, tzinfo=UTC),
    )
    session.add(event)
    await session.flush()

    outcome = await process_inbound_event(session, business_id=business_id, event=event)
    assert outcome.bubble is not None
    await session.commit()
    return outcome.bubble.id


@pytest.mark.asyncio
async def test_the_bubbles_endpoint_carries_the_card(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    """The dashboard card: who, how many orders, how much, and where to look."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        bubble_id = await _seed_bubble(session, business_one.id)

    token = await _login(client)
    response = await client.get(
        "/api/v1/customer-genome/returning-bubbles",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert len(body["items"]) == 1
    card = body["items"][0]
    assert card["id"] == str(bubble_id)
    assert card["customer"]["name"] == "Nadia Rahman"
    assert card["customer"]["initials"] == "NR"
    assert card["is_returning_customer"] is True
    assert card["previous_order_count"] == 2
    assert card["total_purchase_amount"] == "3600.00"
    assert card["currency"] == "BDT"
    assert card["state"] == "new"
    assert card["last_message_preview"] == "Is my order ready?"
    assert card["history_url"] == f"/customers/{card['customer']['id']}/history"


@pytest.mark.asyncio
async def test_the_bubbles_endpoint_filters_by_state(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    """The dashboard filters by what the owner has not dealt with yet."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        bubble_id = await _seed_bubble(session, business_one.id)

    token = await _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    await client.patch(
        f"/api/v1/customer-genome/returning-bubbles/{bubble_id}",
        json={"state": "dismissed"},
        headers=headers,
    )

    dismissed = await client.get(
        "/api/v1/customer-genome/returning-bubbles",
        params={"state": "dismissed"},
        headers=headers,
    )
    assert dismissed.status_code == 200, dismissed.text
    assert len(dismissed.json()["items"]) == 1

    new = await client.get(
        "/api/v1/customer-genome/returning-bubbles",
        params={"state": "new"},
        headers=headers,
    )
    assert new.json()["items"] == []


@pytest.mark.asyncio
async def test_a_bubble_can_be_marked_seen(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    """The 'seen' action moves the bubble out of the unread list."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        bubble_id = await _seed_bubble(session, business_one.id)

    token = await _login(client)
    response = await client.patch(
        f"/api/v1/customer-genome/returning-bubbles/{bubble_id}",
        json={"state": "seen"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "seen"


@pytest.mark.asyncio
async def test_a_bubble_can_be_dismissed(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    """The 'dismiss' action, and it persists."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        bubble_id = await _seed_bubble(session, business_one.id)

    token = await _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    dismissed = await client.patch(
        f"/api/v1/customer-genome/returning-bubbles/{bubble_id}",
        json={"state": "dismissed"},
        headers=headers,
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["state"] == "dismissed"

    fetched = await client.get(
        f"/api/v1/customer-genome/returning-bubbles/{bubble_id}", headers=headers
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["state"] == "dismissed"


@pytest.mark.asyncio
async def test_an_unknown_bubble_is_not_found(
    client: AsyncClient, businesses, users_and_memberships
):
    """A bubble id that does not exist is a 404."""
    token = await _login(client)
    response = await client.get(
        f"/api/v1/customer-genome/returning-bubbles/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_bubble_from_another_tenant_is_not_found(
    client: AsyncClient, businesses, users_and_memberships, tenant_session_factory
):
    """Business two's bubble is invisible to business one's owner."""
    business_one, business_two = businesses

    async with _tenant_session(tenant_session_factory, business_two.id) as session:
        bubble_id = await _seed_bubble(session, business_two.id)

    token = await _login(client)
    response = await client.get(
        f"/api/v1/customer-genome/returning-bubbles/{bubble_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_an_unauthenticated_caller_gets_no_bubbles(
    client: AsyncClient, businesses, users_and_memberships
):
    """No token, no bubbles."""
    response = await client.get("/api/v1/customer-genome/returning-bubbles")
    assert response.status_code == 401
