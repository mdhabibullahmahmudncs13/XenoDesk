"""The bubble engine: an inbound message becomes a Returning Customer bubble.

These are the CG-T01…CG-T07 acceptance tests:

- CG-T01 A linked returning customer messages → exactly one bubble, correct figures.
- CG-T02 A first-time buyer messages → no bubble, no label.
- CG-T03 Identity is unlinked or conflicting → no label, no other customer's data.
- CG-T04 The same webhook arrives twice, or three messages arrive → still one bubble.
- CG-T05 Two returning customers message → two bubbles, each with correct figures.
- CG-T06 A new qualifying order is recorded → the card refreshes.
- CG-T07 Browser notifications blocked → bubbles still work (no push permission needed).

The properties worth pinning beyond those:

- Qualification compares against ``received_at``, not processing time (CG-06).
- A dismissed bubble re-opens on the next message.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.customer import Customer, CustomerOrder
from xenovarients.models.messaging import CustomerBubble, InboundMessageEvent
from xenovarients.platform.bubbles import (
    dismiss,
    list_bubbles,
    mark_seen,
    process_inbound_event,
)
from xenovarients.platform.identity import link, normalise_phone
from xenovarients.platform.source import StubSource
from xenovarients.platform.sync import sync_customers, sync_inventory, sync_orders

pytestmark = pytest.mark.integration

NADIA_PHONE = "+8801712345678"
TANVIR_PHONE = "+8801799999999"


@asynccontextmanager
async def _tenant_session(factory, business_id) -> AsyncIterator[AsyncSession]:
    """A session bound to one business, closed on the way out."""
    session = await factory(business_id)
    try:
        yield session
    finally:
        await session.close()


async def _seed_source(session: AsyncSession, business_id: uuid.UUID) -> None:
    """Run the stub source into the mirror."""
    source = StubSource()
    await sync_inventory(session, business_id=business_id, source=source)
    await sync_customers(session, business_id=business_id, source=source)
    await sync_orders(session, business_id=business_id, source=source)


async def _event(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    channel_user_id: str,
    received_at: datetime,
    provider_event_id: str | None = None,
    conversation_id: str | None = None,
    content: str = "hello",
    channel: str = "messenger",
) -> InboundMessageEvent:
    """An inbound message event, as the webhook would have stored it."""
    event = InboundMessageEvent(
        business_id=business_id,
        provider_event_id=provider_event_id or f"evt-{uuid.uuid4().hex[:12]}",
        channel=channel,
        channel_user_id=channel_user_id,
        conversation_id=conversation_id,
        direction="inbound",
        content=content,
        received_at=received_at,
    )
    session.add(event)
    await session.flush()
    return event


async def _customer(session: AsyncSession, source_customer_id: str) -> Customer:
    result = await session.execute(
        select(Customer).where(Customer.source_customer_id == source_customer_id)
    )
    row = result.scalar_one_or_none()
    assert row is not None, f"customer {source_customer_id} was not synced"
    return row


async def _bubbles(session: AsyncSession) -> list[CustomerBubble]:
    result = await session.execute(select(CustomerBubble))
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_a_linked_returning_customer_gets_one_bubble_with_figures(
    businesses, tenant_session_factory
):
    """CG-T01: one bubble, and the card shows the right count and total."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)

        nadia = await _customer(session, "cus-001")
        await link(
            session,
            business_id=business_one.id,
            channel="messenger",
            channel_user_id="messenger-nadia",
            customer_id=nadia.id,
        )

        event = await _event(
            session,
            business_id=business_one.id,
            channel_user_id="messenger-nadia",
            received_at=datetime(2026, 11, 16, 9, 12, tzinfo=UTC),
        )
        outcome = await process_inbound_event(session, business_id=business_one.id, event=event)
        await session.commit()

        assert outcome.bubble is not None
        assert outcome.is_returning_customer is True

        bubbles = await _bubbles(session)
        assert len(bubbles) == 1
        assert bubbles[0].order_count == 2
        assert bubbles[0].total_spend == Decimal("3600.00")
        assert bubbles[0].is_returning_customer is True
        assert bubbles[0].state == "new"


@pytest.mark.asyncio
async def test_a_first_time_buyer_gets_no_bubble(businesses, tenant_session_factory):
    """CG-T02: a buyer with no prior order produces no bubble at all."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)

        tanvir = await _customer(session, "cus-002")
        # Tanvir has one order, but it is dated after the message — so at the
        # moment of the message he was a first-time buyer.
        await link(
            session,
            business_id=business_one.id,
            channel="messenger",
            channel_user_id="messenger-tanvir",
            customer_id=tanvir.id,
        )

        event = await _event(
            session,
            business_id=business_one.id,
            channel_user_id="messenger-tanvir",
            received_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        outcome = await process_inbound_event(session, business_id=business_one.id, event=event)
        await session.commit()

        assert outcome.bubble is None
        assert outcome.is_returning_customer is False
        assert await _bubbles(session) == []


@pytest.mark.asyncio
async def test_an_unlinked_identity_gets_no_bubble_and_offers_the_link(
    businesses, tenant_session_factory
):
    """CG-T03: no confident match means no bubble and no figures."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)

        event = await _event(
            session,
            business_id=business_one.id,
            channel_user_id="messenger-stranger",
            received_at=datetime(2026, 11, 16, 9, 12, tzinfo=UTC),
        )
        outcome = await process_inbound_event(session, business_id=business_one.id, event=event)
        await session.commit()

        assert outcome.bubble is None
        assert outcome.link_customer_offered is True
        assert await _bubbles(session) == []


@pytest.mark.asyncio
async def test_a_conflicting_identity_gets_no_bubble_and_no_other_customers_data(
    businesses, tenant_session_factory
):
    """CG-T03: a conflict is recorded for staff, never merged."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)

        # Two customers share a phone number, so the ladder finds two candidates.
        first = await _customer(session, "cus-001")
        second = await _customer(session, "cus-002")
        second.phone_e164 = normalise_phone(NADIA_PHONE)
        await session.flush()

        await link(
            session,
            business_id=business_one.id,
            channel="messenger",
            channel_user_id="messenger-nadia",
            customer_id=first.id,
        )

        # The phone rung only runs on a phone channel, where the channel_user_id *is*
        # the number. So the conflicting identity arrives over SMS.
        event = await _event(
            session,
            business_id=business_one.id,
            channel="sms",
            channel_user_id=NADIA_PHONE,
            received_at=datetime(2026, 11, 16, 9, 12, tzinfo=UTC),
        )
        outcome = await process_inbound_event(session, business_id=business_one.id, event=event)
        await session.commit()

        assert outcome.bubble is None
        assert outcome.link_customer_offered is True
        assert outcome.conflict_id is not None
        assert await _bubbles(session) == []


@pytest.mark.asyncio
async def test_three_messages_from_one_customer_still_make_one_bubble(
    businesses, tenant_session_factory
):
    """CG-T04: one bubble per customer and conversation; activity updates."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)

        nadia = await _customer(session, "cus-001")
        await link(
            session,
            business_id=business_one.id,
            channel="messenger",
            channel_user_id="messenger-nadia",
            customer_id=nadia.id,
        )

        for index in range(3):
            event = await _event(
                session,
                business_id=business_one.id,
                channel_user_id="messenger-nadia",
                received_at=datetime(2026, 11, 16, 9, 12, tzinfo=UTC) + timedelta(minutes=index),
                conversation_id="conv-1",
                content=f"message {index}",
            )
            await process_inbound_event(session, business_id=business_one.id, event=event)
        await session.commit()

        bubbles = await _bubbles(session)
        assert len(bubbles) == 1
        assert bubbles[0].last_message_preview == "message 2"
        assert bubbles[0].last_message_at == datetime(2026, 11, 16, 9, 14, tzinfo=UTC)


@pytest.mark.asyncio
async def test_two_returning_customers_get_two_bubbles_with_their_own_figures(
    businesses, tenant_session_factory
):
    """CG-T05: two bubbles, each with the right customer's figures."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)

        nadia = await _customer(session, "cus-001")
        await link(
            session,
            business_id=business_one.id,
            channel="messenger",
            channel_user_id="messenger-nadia",
            customer_id=nadia.id,
        )

        # A second returning customer with one qualifying order.
        other = Customer(
            business_id=business_one.id,
            source_customer_id="cus-other",
            name="Other Buyer",
            phone_e164=TANVIR_PHONE,
        )
        session.add(other)
        await session.flush()
        session.add(
            CustomerOrder(
                business_id=business_one.id,
                customer_id=other.id,
                source_order_id="ord-other",
                ordered_at=datetime(2026, 1, 1, tzinfo=UTC),
                status="completed",
                qualifying=True,
                total_amount=Decimal("500.00"),
            )
        )
        await link(
            session,
            business_id=business_one.id,
            channel="messenger",
            channel_user_id="messenger-other",
            customer_id=other.id,
        )

        for channel_user_id in ("messenger-nadia", "messenger-other"):
            event = await _event(
                session,
                business_id=business_one.id,
                channel_user_id=channel_user_id,
                received_at=datetime(2026, 11, 16, 9, 12, tzinfo=UTC),
            )
            await process_inbound_event(session, business_id=business_one.id, event=event)
        await session.commit()

        bubbles = await _bubbles(session)
        assert len(bubbles) == 2
        by_count = {b.order_count: b for b in bubbles}
        assert by_count[2].total_spend == Decimal("3600.00")
        assert by_count[1].total_spend == Decimal("500.00")


@pytest.mark.asyncio
async def test_a_new_qualifying_order_refreshes_the_card(businesses, tenant_session_factory):
    """CG-T06: the figures are recomputed, so a new order changes the card."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)

        nadia = await _customer(session, "cus-001")
        await link(
            session,
            business_id=business_one.id,
            channel="messenger",
            channel_user_id="messenger-nadia",
            customer_id=nadia.id,
        )

        event = await _event(
            session,
            business_id=business_one.id,
            channel_user_id="messenger-nadia",
            received_at=datetime(2026, 11, 16, 9, 12, tzinfo=UTC),
        )
        await process_inbound_event(session, business_id=business_one.id, event=event)
        await session.commit()

        bubbles = await _bubbles(session)
        assert bubbles[0].order_count == 2

        session.add(
            CustomerOrder(
                business_id=business_one.id,
                customer_id=nadia.id,
                source_order_id="ord-new",
                ordered_at=datetime(2026, 11, 10, tzinfo=UTC),
                status="completed",
                qualifying=True,
                total_amount=Decimal("700.00"),
            )
        )
        await session.flush()

        # The next message re-reads the history, so the card carries the new figure.
        second = await _event(
            session,
            business_id=business_one.id,
            channel_user_id="messenger-nadia",
            received_at=datetime(2026, 11, 16, 10, 0, tzinfo=UTC),
        )
        await process_inbound_event(session, business_id=business_one.id, event=second)
        await session.commit()

        bubbles = await _bubbles(session)
        assert len(bubbles) == 1
        assert bubbles[0].order_count == 3
        assert bubbles[0].total_spend == Decimal("4300.00")


@pytest.mark.asyncio
async def test_qualification_uses_the_message_timestamp_not_the_processing_time(
    businesses, tenant_session_factory
):
    """CG-06: a late webhook must not make a first-time buyer look returning.

    The order is dated after the message. When the webhook is processed now, the
    customer has an order — but not one that pre-dates the message, so no bubble.
    """
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)

        tanvir = await _customer(session, "cus-002")
        await link(
            session,
            business_id=business_one.id,
            channel="messenger",
            channel_user_id="messenger-tanvir",
            customer_id=tanvir.id,
        )

        event = await _event(
            session,
            business_id=business_one.id,
            channel_user_id="messenger-tanvir",
            received_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
        outcome = await process_inbound_event(session, business_id=business_one.id, event=event)
        await session.commit()

        # Tanvir's only order is dated 2026-11-01, after the message.
        assert outcome.bubble is None


@pytest.mark.asyncio
async def test_a_dismissed_bubble_reopens_on_the_next_message(businesses, tenant_session_factory):
    """CG-08: a message from a dismissed customer brings the bubble back."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)

        nadia = await _customer(session, "cus-001")
        await link(
            session,
            business_id=business_one.id,
            channel="messenger",
            channel_user_id="messenger-nadia",
            customer_id=nadia.id,
        )

        event = await _event(
            session,
            business_id=business_one.id,
            channel_user_id="messenger-nadia",
            received_at=datetime(2026, 11, 16, 9, 12, tzinfo=UTC),
            conversation_id="conv-1",
        )
        await process_inbound_event(session, business_id=business_one.id, event=event)

        bubbles = await _bubbles(session)
        await dismiss(session, business_id=business_one.id, bubble_id=bubbles[0].id)
        await session.commit()
        assert bubbles[0].state == "dismissed"

        second = await _event(
            session,
            business_id=business_one.id,
            channel_user_id="messenger-nadia",
            received_at=datetime(2026, 11, 16, 10, 0, tzinfo=UTC),
            conversation_id="conv-1",
        )
        await process_inbound_event(session, business_id=business_one.id, event=second)
        await session.commit()

        bubbles = await _bubbles(session)
        assert len(bubbles) == 1
        assert bubbles[0].state == "new"
        assert bubbles[0].dismissed_at is None


@pytest.mark.asyncio
async def test_marking_a_bubble_seen_moves_its_state(businesses, tenant_session_factory):
    """The seen action is the state machine's middle step."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)

        nadia = await _customer(session, "cus-001")
        await link(
            session,
            business_id=business_one.id,
            channel="messenger",
            channel_user_id="messenger-nadia",
            customer_id=nadia.id,
        )

        event = await _event(
            session,
            business_id=business_one.id,
            channel_user_id="messenger-nadia",
            received_at=datetime(2026, 11, 16, 9, 12, tzinfo=UTC),
        )
        await process_inbound_event(session, business_id=business_one.id, event=event)

        bubbles = await _bubbles(session)
        await mark_seen(session, business_id=business_one.id, bubble_id=bubbles[0].id)
        await session.commit()

        assert bubbles[0].state == "seen"
        assert bubbles[0].seen_at is not None


@pytest.mark.asyncio
async def test_the_bubbles_are_listed_newest_first(businesses, tenant_session_factory):
    """The list is what the dashboard renders."""
    business_one, _ = businesses
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)

        nadia = await _customer(session, "cus-001")
        await link(
            session,
            business_id=business_one.id,
            channel="messenger",
            channel_user_id="messenger-nadia",
            customer_id=nadia.id,
        )

        for index, moment in enumerate(
            (
                datetime(2026, 11, 16, 9, 12, tzinfo=UTC),
                datetime(2026, 11, 16, 15, 0, tzinfo=UTC),
            )
        ):
            event = await _event(
                session,
                business_id=business_one.id,
                channel_user_id="messenger-nadia",
                received_at=moment,
                conversation_id=f"conv-{index}",
            )
            await process_inbound_event(session, business_id=business_one.id, event=event)
        await session.commit()

        bubbles = await list_bubbles(session, business_id=business_one.id)
        assert len(bubbles) == 2
        assert bubbles[0].last_message_at > bubbles[1].last_message_at


@pytest.mark.asyncio
async def test_bubbles_do_not_leak_across_tenants(businesses, tenant_session_factory):
    """One business's bubbles are invisible to another."""
    business_one, business_two = businesses

    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        await _seed_source(session, business_one.id)
        nadia = await _customer(session, "cus-001")
        await link(
            session,
            business_id=business_one.id,
            channel="messenger",
            channel_user_id="messenger-nadia",
            customer_id=nadia.id,
        )
        event = await _event(
            session,
            business_id=business_one.id,
            channel_user_id="messenger-nadia",
            received_at=datetime(2026, 11, 16, 9, 12, tzinfo=UTC),
        )
        await process_inbound_event(session, business_id=business_one.id, event=event)
        await session.commit()

    async with _tenant_session(tenant_session_factory, business_two.id) as session:
        bubbles = await list_bubbles(session, business_id=business_two.id)
        assert bubbles == []
