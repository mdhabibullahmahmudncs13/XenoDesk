"""Review reply matching (RV-07)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from xenovarients.models.customer import Customer, CustomerOrder
from xenovarients.models.messaging import InboundMessageEvent
from xenovarients.models.review import ReviewReply, ReviewRequest, ReviewRequestState
from xenovarients.models.tenancy import Business
from xenovarients.platform.review_matching import match_review_reply

pytestmark = pytest.mark.integration


async def _request(
    session, business: Business, customer: Customer, *, channel: str
) -> ReviewRequest:
    order = CustomerOrder(
        business_id=business.id,
        customer_id=customer.id,
        source_order_id=f"reply-order-{uuid.uuid4().hex}",
        ordered_at=datetime.now(UTC),
        status="completed",
        qualifying=True,
    )
    session.add(order)
    await session.flush()
    request = ReviewRequest(
        business_id=business.id,
        order_id=order.id,
        customer_id=customer.id,
        delivery_confirmed_at=datetime.now(UTC),
        due_at=datetime.now(UTC),
        state=ReviewRequestState.sent.value,
        reference_token=f"review-{uuid.uuid4().hex}",
        sent_channel=channel,
    )
    session.add(request)
    await session.flush()
    return request


@pytest.mark.asyncio
async def test_reply_token_links_the_review_request(session, businesses, bind):
    business, _ = businesses
    await bind(business.id)
    customer = Customer(
        business_id=business.id,
        source_customer_id=f"reply-customer-{uuid.uuid4().hex}",
        name="Ayesha",
    )
    session.add(customer)
    await session.flush()
    request = await _request(session, business, customer, channel="email")
    event = InboundMessageEvent(
        business_id=business.id,
        provider_event_id=f"reply-event-{uuid.uuid4().hex}",
        channel="email",
        content=f"Here is my review: {request.reference_token}",
        received_at=datetime.now(UTC),
    )
    session.add(event)
    await session.flush()

    result = await match_review_reply(session, business_id=business.id, event=event)
    await session.commit()

    assert result.request is not None
    assert event.review_request_id == request.id
    assert request.state == ReviewRequestState.replied.value
    reply = await session.scalar(
        select(ReviewReply).where(ReviewReply.inbound_message_id == event.id)
    )
    assert reply is not None
    assert reply.content == event.content

    reply.content = "edited"
    with pytest.raises(SQLAlchemyError):
        await session.flush()
    await session.rollback()


@pytest.mark.asyncio
async def test_unambiguous_customer_thread_links_without_token(session, businesses, bind):
    business, _ = businesses
    await bind(business.id)
    customer = Customer(
        business_id=business.id,
        source_customer_id=f"thread-customer-{uuid.uuid4().hex}",
        name="Ayesha",
    )
    session.add(customer)
    await session.flush()
    request = await _request(session, business, customer, channel="email")
    event = InboundMessageEvent(
        business_id=business.id,
        provider_event_id=f"thread-event-{uuid.uuid4().hex}",
        channel="email",
        content="The product is lovely.",
        received_at=datetime.now(UTC),
        resolved_customer_id=customer.id,
    )
    session.add(event)
    await session.flush()

    result = await match_review_reply(session, business_id=business.id, event=event)
    await session.commit()

    assert result.request is not None
    assert result.request.id == request.id


@pytest.mark.asyncio
async def test_ambiguous_threads_need_manual_assignment(session, businesses, bind):
    business, _ = businesses
    await bind(business.id)
    customer = Customer(
        business_id=business.id,
        source_customer_id=f"ambiguous-customer-{uuid.uuid4().hex}",
        name="Ayesha",
    )
    session.add(customer)
    await session.flush()
    await _request(session, business, customer, channel="email")
    await _request(session, business, customer, channel="email")
    event = InboundMessageEvent(
        business_id=business.id,
        provider_event_id=f"ambiguous-event-{uuid.uuid4().hex}",
        channel="email",
        content="The product is lovely.",
        received_at=datetime.now(UTC),
        resolved_customer_id=customer.id,
    )
    session.add(event)
    await session.flush()

    result = await match_review_reply(session, business_id=business.id, event=event)
    await session.commit()

    assert result.needs_assignment is True
    states = (
        await session.scalars(
            select(ReviewRequest.state).where(ReviewRequest.customer_id == customer.id)
        )
    ).all()
    assert states == [ReviewRequestState.needs_assignment.value] * 2
