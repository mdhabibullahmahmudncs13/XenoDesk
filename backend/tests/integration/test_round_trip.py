"""The full inbound → outbound round trip, with a stub adapter.

The shared services are only worth anything if they compose. This test drives the
whole path a real message takes:

    provider webhook → inbound event → identity resolution → consent check →
    outbox row → dispatcher → delivery attempt

The stub adapter stands in for the provider so nothing leaves the machine, but
every other layer is the real one — the real signature verification, the real
identity ladder, the real eligibility re-check at send time.

The properties worth pinning:

- The message actually goes out, exactly once.
- A recipient who opted out between enqueue and dispatch is skipped, not sent to.
- The retry budget is enforced, and every attempt is visible in
  ``delivery_attempts``.
- One failing recipient does not stop the others.
"""

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.core.config import get_settings
from xenovarients.models.customer import Customer
from xenovarients.models.messaging import InboundMessageEvent
from xenovarients.models.outbound import DeliveryAttempt, OutboundMessage, OutboundStatus
from xenovarients.platform.identity import grant_permission, resolve, revoke_permission
from xenovarients.platform.outbound import StubAdapter, dispatch_one, enqueue

pytestmark = pytest.mark.integration

SECRET = "webhook-secret-for-tests"
PHONE = "+8801712345678"
OTHER_PHONE = "+8801799999999"


@asynccontextmanager
async def _tenant_session(factory, business_id) -> AsyncIterator[AsyncSession]:
    """A session bound to one business, closed on the way out."""
    session = await factory(business_id)
    try:
        yield session
    finally:
        await session.close()


def _sign(body: bytes, secret: str = SECRET) -> dict[str, str]:
    ts = int(time.time())
    signature = hmac.new(
        secret.encode(), f"{ts}.{body.decode()}".encode(), hashlib.sha256
    ).hexdigest()
    return {"X-Signature": f"sha256={signature}", "X-Timestamp": str(ts)}


def _payload(event_id: str, content: str = "hello") -> bytes:
    return json.dumps(
        {
            "event_id": event_id,
            "channel_user_id": PHONE,
            "content": content,
            "received_at": "2026-11-16T09:12:00+00:00",
        }
    ).encode()


async def _seed_customer(session, business, *, phone: str = PHONE) -> Customer:
    customer = Customer(
        business_id=business.id,
        source_customer_id=f"src-c-{uuid.uuid4().hex[:10]}",
        name="Nadia",
        phone_e164=phone,
    )
    session.add(customer)
    await session.flush()
    return customer


async def _message(session: AsyncSession, message_id: uuid.UUID) -> OutboundMessage:
    """The outbound message row, or a failure that says so."""
    row = await session.get(OutboundMessage, message_id)
    assert row is not None, f"outbound message {message_id} is missing"
    return row


@pytest.mark.asyncio
async def test_a_message_goes_in_by_webhook_and_out_by_the_dispatcher(
    client: AsyncClient, businesses, tenant_session_factory
):
    """The whole path, end to end, with the real layers and a stub provider."""
    business_one, _ = businesses

    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        customer = await _seed_customer(session, business_one)
        await grant_permission(
            session,
            business_id=business_one.id,
            customer_id=customer.id,
            channel="sms",
            contact_value=PHONE,
            source="opt_in",
            purposes=["restock"],
        )
        await session.commit()

    # 1. Inbound: the provider's webhook lands.
    body = _payload(f"evt-{uuid.uuid4().hex[:8]}")
    received = await client.post(
        f"/webhooks/messaging/generic/{business_one.id}", content=body, headers=_sign(body)
    )
    assert received.status_code == 202, received.text
    assert received.json()["stored"] == 1

    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        events = list((await session.execute(select(InboundMessageEvent))).scalars())
        assert len(events) == 1
        event = events[0]
        assert event.channel_user_id == PHONE

        # 2. Identity: the inbound identity resolves to a customer.
        resolution = await resolve(
            session,
            business_id=business_one.id,
            channel="sms",
            channel_user_id=PHONE,
        )
        assert resolution.outcome.value == "matched"
        assert resolution.customer_id == customer.id

        # 3. Outbox: the message is written as pending, not sent.
        message = await enqueue(
            session,
            business_id=business_one.id,
            purpose="restock",
            ref_id=uuid.uuid4(),
            customer_id=customer.id,
            channel="sms",
            to_address=PHONE,
            body="Your size is back in stock.",
            idempotency_key=f"idem-{uuid.uuid4().hex[:12]}",
        )
        await session.commit()
        message_id = message.id

    # 4. Dispatch: a separate transaction picks up the pending row and sends it.
    adapter = StubAdapter("sms")
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        row = await _message(session, message_id)
        assert row.status == OutboundStatus.pending.value
        await dispatch_one(session, message=row, adapter=adapter)
        await session.commit()

    assert len(adapter.sent) == 1
    assert adapter.sent[0][0] == PHONE
    assert adapter.sent[0][1] == "Your size is back in stock."

    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        row = await _message(session, message_id)
        assert row.status == OutboundStatus.sent.value
        assert row.attempt_count == 1
        attempts = list(
            (
                await session.execute(
                    select(DeliveryAttempt).where(DeliveryAttempt.outbound_message_id == message_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(attempts) == 1
        assert attempts[0].outcome == "sent"


@pytest.mark.asyncio
async def test_a_recipient_who_opts_out_after_enqueue_is_skipped_not_sent(
    client: AsyncClient, businesses, tenant_session_factory
):
    """The preview showed what would happen; the dispatcher decides what does.

    Opting out between the preview and the send must stop the send, not merely
    change what the dashboard says.
    """
    business_one, _ = businesses

    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        customer = await _seed_customer(session, business_one)
        await grant_permission(
            session,
            business_id=business_one.id,
            customer_id=customer.id,
            channel="sms",
            contact_value=PHONE,
            source="opt_in",
            purposes=["restock"],
        )
        message = await enqueue(
            session,
            business_id=business_one.id,
            purpose="restock",
            ref_id=uuid.uuid4(),
            customer_id=customer.id,
            channel="sms",
            to_address=PHONE,
            body="Back in stock.",
            idempotency_key=f"idem-{uuid.uuid4().hex[:12]}",
        )
        await session.commit()

        # The customer opts out before the dispatcher gets there.
        assert await revoke_permission(
            session,
            business_id=business_one.id,
            customer_id=customer.id,
            channel="sms",
        )
        await session.commit()

        rules = _sms_rules()
        adapter = StubAdapter("sms")
        await dispatch_one(session, message=message, adapter=adapter, rules=rules)
        await session.commit()

    assert adapter.sent == []
    assert message.status == OutboundStatus.skipped.value
    assert message.error_code == "opted_out"


@pytest.mark.asyncio
async def test_the_retry_budget_is_enforced_and_every_attempt_is_recorded(
    businesses, tenant_session_factory
):
    """A permanently failing message stops retrying, and the attempts are visible.

    The budget is what stops a broken provider from being hit forever, so the
    number of ``delivery_attempts`` rows must equal the budget exactly — not more,
    not fewer.
    """
    business_one, _ = businesses
    settings = get_settings()
    budget = settings.max_delivery_attempts

    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        customer = await _seed_customer(session, business_one)
        await grant_permission(
            session,
            business_id=business_one.id,
            customer_id=customer.id,
            channel="sms",
            contact_value=PHONE,
            source="opt_in",
            purposes=["restock"],
        )
        message = await enqueue(
            session,
            business_id=business_one.id,
            purpose="restock",
            ref_id=uuid.uuid4(),
            customer_id=customer.id,
            channel="sms",
            to_address=PHONE,
            body="Back in stock.",
            idempotency_key=f"idem-{uuid.uuid4().hex[:12]}",
        )
        await session.commit()
        message_id = message.id

        failing = StubAdapter("sms", fail=True)
        for _ in range(budget):
            row = await _message(session, message_id)
            await dispatch_one(session, message=row, adapter=failing)
            await session.commit()

        row = await _message(session, message_id)
        assert row.status == OutboundStatus.failed.value
        assert row.attempt_count == budget
        assert row.next_attempt_at is None, "a spent budget must not schedule another attempt"

        attempts = list(
            (
                await session.execute(
                    select(DeliveryAttempt).where(DeliveryAttempt.outbound_message_id == message_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(attempts) == budget
        assert [a.attempt_number for a in attempts] == list(range(1, budget + 1))
        assert all(a.outcome == "failed" for a in attempts)
        assert all(a.error_code == "provider_unavailable" for a in attempts)


@pytest.mark.asyncio
async def test_one_failing_recipient_does_not_stop_the_others(businesses, tenant_session_factory):
    """A batch is attempted recipient by recipient; a failure is one row's problem."""
    business_one, _ = businesses

    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        first = await _seed_customer(session, business_one, phone=PHONE)
        second = await _seed_customer(session, business_one, phone=OTHER_PHONE)
        for customer, contact in ((first, PHONE), (second, OTHER_PHONE)):
            await grant_permission(
                session,
                business_id=business_one.id,
                customer_id=customer.id,
                channel="sms",
                contact_value=contact,
                source="opt_in",
                purposes=["restock"],
            )
        await session.commit()

    # A batch where one address is invalid: the adapter refuses that one only.
    class PartiallyFailingAdapter:
        channel = "sms"

        def __init__(self) -> None:
            self.sent: list[tuple[str, str, str]] = []

        def send(self, *, to_address: str, body: str, reference: str):
            from xenovarients.platform.outbound import SendResult

            if to_address == OTHER_PHONE:
                return SendResult(ok=False, error_code="provider_unavailable")
            self.sent.append((to_address, body, reference))
            return SendResult(ok=True, provider_message_id="stub-1")

        def eligibility(self) -> str | None:
            return None

    adapter = PartiallyFailingAdapter()
    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        good = await enqueue(
            session,
            business_id=business_one.id,
            purpose="restock",
            ref_id=uuid.uuid4(),
            customer_id=first.id,
            channel="sms",
            to_address=PHONE,
            body="Back in stock.",
            idempotency_key=f"idem-{uuid.uuid4().hex[:12]}",
        )
        bad = await enqueue(
            session,
            business_id=business_one.id,
            purpose="restock",
            ref_id=uuid.uuid4(),
            customer_id=second.id,
            channel="sms",
            to_address=OTHER_PHONE,
            body="Back in stock.",
            idempotency_key=f"idem-{uuid.uuid4().hex[:12]}",
        )
        await session.commit()

        await dispatch_one(session, message=good, adapter=adapter)
        await dispatch_one(session, message=bad, adapter=adapter)
        await session.commit()

        assert good.status == OutboundStatus.sent.value
        assert bad.status != OutboundStatus.sent.value
        assert bad.attempt_count == 1
        assert bad.next_attempt_at is not None, "a failure must schedule a retry"

    assert len(adapter.sent) == 1


@pytest.mark.asyncio
async def test_a_replayed_webhook_does_not_send_a_second_message(
    client: AsyncClient, businesses, tenant_session_factory
):
    """The provider retrying must not produce a second delivery."""
    business_one, _ = businesses

    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        customer = await _seed_customer(session, business_one)
        await grant_permission(
            session,
            business_id=business_one.id,
            customer_id=customer.id,
            channel="sms",
            contact_value=PHONE,
            source="opt_in",
            purposes=["restock"],
        )
        await session.commit()

    body = _payload(f"evt-{uuid.uuid4().hex[:8]}")
    headers = _sign(body)
    first = await client.post(
        f"/webhooks/messaging/generic/{business_one.id}", content=body, headers=headers
    )
    assert first.json()["duplicate"] is False
    second = await client.post(
        f"/webhooks/messaging/generic/{business_one.id}", content=body, headers=headers
    )
    assert second.json()["duplicate"] is True

    async with _tenant_session(tenant_session_factory, business_one.id) as session:
        events = list((await session.execute(select(InboundMessageEvent))).scalars())
        assert len(events) == 1


def _sms_rules() -> dict[str, Any]:
    """The eligibility rules for SMS, read from the shipped config."""
    from xenovarients.platform.eligibility import load_rules

    return load_rules()
