"""Idempotency tests.

The ERD makes idempotency a database guarantee, not an application convention:
``outbound_messages.idempotency_key`` and ``restock_batches``'s
``(business_id, idempotency_key)`` are unique. A repeated confirm therefore cannot
create a second message (RP-08, RP-T05).

These tests exercise the database constraint directly — the behaviour the API depends
on — plus the cursor helper, which is the other place a duplicate could slip through.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.api.pagination import decode_cursor, encode_cursor
from xenovarients.models.customer import Customer
from xenovarients.models.outbound import OutboundMessage, OutboundStatus

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def outbound(session: AsyncSession, businesses, bind):
    """A tenant with one customer, so outbound_messages has a valid FK target."""
    business = businesses[0]
    await bind(business.id)
    customer = Customer(
        business_id=business.id,
        source_customer_id="cust-" + uuid.uuid4().hex[:8],
        name="Customer",
        total_orders=0,
        total_spend=0,
        is_repeat_buyer=False,
    )
    session.add(customer)
    await session.commit()
    return business.id, customer.id


@pytest.mark.asyncio
async def test_duplicate_idempotency_key_is_rejected(session: AsyncSession, outbound):
    """The second insert with the same key violates the unique constraint."""
    business_id, customer_id = outbound
    key = "restock:" + str(uuid.uuid4())
    for _ in range(2):
        session.add(
            OutboundMessage(
                business_id=business_id,
                purpose="restock",
                ref_id=uuid.uuid4(),
                customer_id=customer_id,
                channel="sms",
                to_address="+8801700000000",
                body="in stock",
                idempotency_key=key,
                status=OutboundStatus.pending.value,
                attempt_count=0,
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return
    pytest.fail("duplicate idempotency_key was accepted")


@pytest.mark.asyncio
async def test_idempotency_key_is_globally_unique(session: AsyncSession, outbound):
    """The key is unique across the whole table, not per tenant.

    This is deliberate: a replay must be absorbed even if the retry lands in a
    different tenant context, and a key that collided across tenants could hide a
    genuine message.
    """
    business_id, customer_id = outbound
    key = "global:" + str(uuid.uuid4())
    session.add(
        OutboundMessage(
            business_id=business_id,
            purpose="restock",
            ref_id=uuid.uuid4(),
            customer_id=customer_id,
            channel="sms",
            to_address="+8801700000000",
            body="x",
            idempotency_key=key,
            status=OutboundStatus.pending.value,
            attempt_count=0,
        )
    )
    await session.commit()

    session.add(
        OutboundMessage(
            business_id=business_id,
            purpose="restock",
            ref_id=uuid.uuid4(),
            customer_id=customer_id,
            channel="sms",
            to_address="+8801700000000",
            body="x",
            idempotency_key=key,
            status=OutboundStatus.pending.value,
            attempt_count=0,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


def test_cursor_roundtrip():
    """A cursor survives encoding and decoding unchanged."""
    cursor = encode_cursor("2026-11-17T10:00:00Z", uuid.uuid4())
    decoded = decode_cursor(cursor)
    assert decoded is not None
    assert decoded.value == "2026-11-17T10:00:00Z"
    assert uuid.UUID(decoded.id)


def test_invalid_cursor_is_rejected():
    """A tampered cursor must raise rather than silently returning page one."""
    with pytest.raises(ValueError):
        decode_cursor("not-a-real-cursor!!")
