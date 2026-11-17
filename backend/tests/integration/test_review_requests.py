"""Review request scheduling and send-time eligibility (RV-02, RV-04, RV-05)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from xenovarients.models.customer import Customer, CustomerOrder
from xenovarients.models.messaging import ContactPermission
from xenovarients.models.outbound import MessageTemplate, OutboundMessage
from xenovarients.models.review import ReviewRequestState, ReviewSettings
from xenovarients.models.tenancy import Business
from xenovarients.platform.reviews import process_review_request, schedule_review_request

pytestmark = pytest.mark.integration


async def _order(session, business: Business, *, status: str = "completed") -> CustomerOrder:
    customer = Customer(
        business_id=business.id,
        source_customer_id=f"review-customer-{uuid.uuid4().hex}",
        name="Ayesha",
        email_normalised="ayesha@example.com",
    )
    session.add(customer)
    await session.flush()
    row = CustomerOrder(
        business_id=business.id,
        customer_id=customer.id,
        source_order_id=f"review-order-{uuid.uuid4().hex}",
        ordered_at=datetime.now(UTC) - timedelta(days=10),
        status=status,
        delivered_at=datetime(2026, 11, 17, 12, 0, tzinfo=UTC),
        qualifying=True,
    )
    session.add(row)
    await session.flush()
    return row


@pytest.mark.asyncio
async def test_due_review_request_is_idempotent(session, businesses, bind):
    business, _ = businesses
    await bind(business.id)
    order = await _order(session, business)

    first = await schedule_review_request(session, business=business, order=order)
    second = await schedule_review_request(session, business=business, order=order)
    await session.commit()

    assert first is not None
    assert second is not None
    assert first.id == second.id


@pytest.mark.asyncio
async def test_cancelled_order_is_not_sent_at_due_time(session, businesses, bind):
    business, _ = businesses
    await bind(business.id)
    order = await _order(session, business, status="cancelled")
    request = await schedule_review_request(session, business=business, order=order)
    assert request is not None

    await process_review_request(
        session,
        business_id=business.id,
        request_id=request.id,
    )
    await session.commit()

    assert request.state == ReviewRequestState.cancelled.value
    assert request.state_reason == "order_invalid"
    assert (
        await session.scalar(
            select(OutboundMessage).where(OutboundMessage.ref_id == request.id)
        )
        is None
    )


@pytest.mark.asyncio
async def test_eligible_review_request_enters_outbox(session, businesses, bind):
    business, _ = businesses
    await bind(business.id)
    order = await _order(session, business)
    session.add(
        ReviewSettings(
            business_id=business.id,
            channel_order=["email"],
        )
    )
    template = MessageTemplate(
        business_id=business.id,
        key="review_request",
        locale="en",
        body="Tell us what you think.",
        version=1,
    )
    session.add(template)
    await session.flush()
    settings = await session.scalar(
        select(ReviewSettings).where(ReviewSettings.business_id == business.id)
    )
    settings.template_id = template.id
    session.add(
        ContactPermission(
            business_id=business.id,
            customer_id=order.customer_id,
            channel="email",
            contact_value="ayesha@example.com",
            eligible=True,
            source="staff",
            purposes=["review_request"],
        )
    )
    request = await schedule_review_request(session, business=business, order=order)
    assert request is not None
    await process_review_request(session, business_id=business.id, request_id=request.id)
    await session.commit()

    message = await session.scalar(
        select(OutboundMessage).where(OutboundMessage.ref_id == request.id)
    )
    assert message is not None
    assert message.status == "pending"
    assert request.state == ReviewRequestState.sent.value
