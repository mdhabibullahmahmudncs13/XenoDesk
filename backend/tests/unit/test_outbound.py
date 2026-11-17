"""The outbox: enqueue, dispatch, retry, and per-recipient isolation.

The outbox's whole value is in the awkward cases — a send that fails, a retry that
must not duplicate, one recipient's failure not stopping the rest. Those are what
these tests pin down.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from xenovarients.models.outbound import (
    DeliveryAttempt,
    OutboundMessage,
    OutboundStatus,
    SkipReason,
)
from xenovarients.platform.eligibility import load_rules
from xenovarients.platform.identity import grant_permission, revoke_permission
from xenovarients.platform.outbound import (
    StubAdapter,
    claim_pending,
    dispatch_batch,
    dispatch_one,
    enqueue,
    mark_skipped,
)

pytestmark = pytest.mark.integration


async def _enqueue(
    session, business_id, customer_id, *, channel="email", key=None
) -> OutboundMessage:
    return await enqueue(
        session,
        business_id=business_id,
        purpose="review_request",
        ref_id=uuid.uuid4(),
        customer_id=customer_id,
        channel=channel,
        to_address="customer@example.com",
        body="May we ask for a review?",
        idempotency_key=key or f"key-{uuid.uuid4().hex[:12]}",
    )


@pytest.mark.asyncio
async def test_enqueue_writes_a_pending_message(session, businesses, bind, customer_factory):
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one, email_normalised="a@example.com")

    message = await _enqueue(session, business_one.id, customer.id)
    await session.commit()

    assert message.status == OutboundStatus.pending.value
    assert message.attempt_count == 0
    assert message.next_attempt_at is None


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_on_the_key(session, businesses, bind, customer_factory):
    """A repeated confirm must not create a second message."""
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one, email_normalised="b@example.com")
    key = f"key-{uuid.uuid4().hex[:12]}"

    await _enqueue(session, business_one.id, customer.id, key=key)
    await session.commit()

    with pytest.raises(IntegrityError):
        await _enqueue(session, business_one.id, customer.id, key=key)
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
async def test_dispatch_sends_and_records_the_attempt(session, businesses, bind, customer_factory):
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one, email_normalised="c@example.com")
    message = await _enqueue(session, business_one.id, customer.id)
    await session.commit()

    adapter = StubAdapter("email")
    await dispatch_one(session, message=message, adapter=adapter)
    await session.commit()

    assert message.status == OutboundStatus.sent.value
    assert message.attempt_count == 1
    assert message.sent_at is not None
    assert message.next_attempt_at is None
    assert adapter.sent == [
        ("customer@example.com", "May we ask for a review?", message.idempotency_key)
    ]

    attempts = list(
        (
            await session.execute(
                select(DeliveryAttempt).where(DeliveryAttempt.outbound_message_id == message.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(attempts) == 1
    assert attempts[0].outcome == "sent"


@pytest.mark.asyncio
async def test_a_failed_send_schedules_a_backoff(session, businesses, bind, customer_factory):
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one, email_normalised="d@example.com")
    message = await _enqueue(session, business_one.id, customer.id)
    await session.commit()

    adapter = StubAdapter("email", fail=True)
    await dispatch_one(session, message=message, adapter=adapter)
    await session.commit()

    assert message.status == OutboundStatus.pending.value
    assert message.attempt_count == 1
    assert message.error_code == "provider_unavailable"
    assert message.next_attempt_at is not None
    assert message.next_attempt_at > datetime.now(UTC)


@pytest.mark.asyncio
async def test_a_message_not_yet_due_is_not_claimed(session, businesses, bind, customer_factory):
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one, email_normalised="e@example.com")
    message = await _enqueue(session, business_one.id, customer.id)
    message.next_attempt_at = datetime.now(UTC) + timedelta(hours=1)
    await session.commit()

    assert await claim_pending(session, business_id=business_one.id) == []


@pytest.mark.asyncio
async def test_a_due_message_is_claimed(session, businesses, bind, customer_factory):
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one, email_normalised="f@example.com")
    message = await _enqueue(session, business_one.id, customer.id)
    message.next_attempt_at = datetime.now(UTC) - timedelta(minutes=1)
    await session.commit()

    claimed = await claim_pending(session, business_id=business_one.id)
    assert [m.id for m in claimed] == [message.id]


@pytest.mark.asyncio
async def test_the_retry_budget_is_bounded(session, businesses, bind, customer_factory):
    """After the configured maximum the message fails and stops being retried."""
    from xenovarients.core.config import get_settings

    settings = get_settings()
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one, email_normalised="g@example.com")
    message = await _enqueue(session, business_one.id, customer.id)
    await session.commit()

    adapter = StubAdapter("email", fail=True)
    for _ in range(settings.max_delivery_attempts):
        await dispatch_one(session, message=message, adapter=adapter)
    await session.commit()

    assert message.status == OutboundStatus.failed.value
    assert message.attempt_count == settings.max_delivery_attempts
    assert message.next_attempt_at is None

    attempts = list(
        (
            await session.execute(
                select(DeliveryAttempt).where(DeliveryAttempt.outbound_message_id == message.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(attempts) == settings.max_delivery_attempts
    assert all(a.outcome == "failed" for a in attempts)


@pytest.mark.asyncio
async def test_one_failed_recipient_does_not_stop_the_others(
    session, businesses, bind, customer_factory
):
    """The dispatcher moves on after a failure — a bad address is not a bad batch."""
    business_one, _ = businesses
    await bind(business_one.id)
    first = await customer_factory(business_one, email_normalised="h@example.com")
    second = await customer_factory(business_one, email_normalised="i@example.com")

    good = await _enqueue(session, business_one.id, first.id)
    bad = await _enqueue(session, business_one.id, second.id)
    await session.commit()

    class OneBadAdapter:
        channel = "email"

        def send(self, *, to_address, body, reference):
            from xenovarients.platform.outbound import SendResult

            if to_address == "customer@example.com" and reference == bad.idempotency_key:
                return SendResult(ok=False, error_code="provider_unavailable")
            return SendResult(ok=True, provider_message_id="ok-1")

        def eligibility(self):
            return None

    counts = await dispatch_batch(session, business_id=business_one.id, adapter=OneBadAdapter())

    assert counts["sent"] == 1
    assert counts["retried"] == 1
    assert good.status == OutboundStatus.sent.value
    assert bad.status == OutboundStatus.pending.value


@pytest.mark.asyncio
async def test_dispatch_batch_skips_other_channels(session, businesses, bind, customer_factory):
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one, email_normalised="j@example.com")
    message = await _enqueue(session, business_one.id, customer.id, channel="sms")
    await session.commit()

    adapter = StubAdapter("email")
    counts = await dispatch_batch(session, business_id=business_one.id, adapter=adapter)

    assert counts["sent"] == 0
    assert adapter.sent == []
    assert message.status == OutboundStatus.pending.value


@pytest.mark.asyncio
async def test_mark_skipped_records_the_reason(session, businesses, bind, customer_factory):
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one, email_normalised="k@example.com")
    message = await _enqueue(session, business_one.id, customer.id)
    await session.commit()

    await mark_skipped(session, message=message, reason=SkipReason.opted_out)
    await session.commit()

    assert message.status == OutboundStatus.skipped.value
    assert message.skip_reason == SkipReason.opted_out.value


@pytest.mark.asyncio
async def test_a_recipient_who_opts_out_is_skipped_at_send_time(
    session, businesses, bind, customer_factory
):
    """The preview showed them as eligible; they opted out before the send fired.

    This is the whole point of re-checking at send time: the send path must not
    trust the schedule-time snapshot.
    """
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one, email_normalised="l@example.com")
    await grant_permission(
        session,
        business_id=business_one.id,
        customer_id=customer.id,
        channel="email",
        contact_value="l@example.com",
        source="import",
        purposes=["review_request"],
    )
    message = await _enqueue(session, business_one.id, customer.id)
    await session.commit()

    # The customer opts out after the preview, before the dispatcher runs.
    await revoke_permission(
        session, business_id=business_one.id, customer_id=customer.id, channel="email"
    )
    await session.commit()

    adapter = StubAdapter("email")
    await dispatch_one(session, message=message, adapter=adapter, rules=load_rules())
    await session.commit()

    assert message.status == OutboundStatus.skipped.value
    assert message.skip_reason == SkipReason.channel_ineligible.value
    assert adapter.sent == []


@pytest.mark.asyncio
async def test_a_consented_recipient_is_sent(session, businesses, bind, customer_factory):
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one, email_normalised="m@example.com")
    await grant_permission(
        session,
        business_id=business_one.id,
        customer_id=customer.id,
        channel="email",
        contact_value="m@example.com",
        source="import",
        purposes=["review_request"],
    )
    message = await _enqueue(session, business_one.id, customer.id)
    await session.commit()

    adapter = StubAdapter("email")
    await dispatch_one(session, message=message, adapter=adapter, rules=load_rules())
    await session.commit()

    assert message.status == OutboundStatus.sent.value
    assert len(adapter.sent) == 1


@pytest.mark.asyncio
async def test_a_recipient_without_consent_is_skipped(session, businesses, bind, customer_factory):
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one, email_normalised="n@example.com")
    message = await _enqueue(session, business_one.id, customer.id)
    await session.commit()

    adapter = StubAdapter("email")
    await dispatch_one(session, message=message, adapter=adapter, rules=load_rules())
    await session.commit()

    assert message.status == OutboundStatus.skipped.value
    assert adapter.sent == []


@pytest.mark.asyncio
async def test_an_unconfigured_channel_is_skipped_not_retried(
    session, businesses, bind, customer_factory
):
    """A provider with no credentials is not a delivery failure — it never fires."""
    business_one, _ = businesses
    await bind(business_one.id)
    customer = await customer_factory(business_one, email_normalised="o@example.com")
    await grant_permission(
        session,
        business_id=business_one.id,
        customer_id=customer.id,
        channel="email",
        contact_value="o@example.com",
        source="import",
    )
    message = await _enqueue(session, business_one.id, customer.id)
    await session.commit()

    class UnconfiguredAdapter:
        channel = "email"

        def send(self, *, to_address, body, reference):
            raise AssertionError("must not send on an ineligible channel")

        def eligibility(self):
            return "email_provider_not_configured"

    await dispatch_one(session, message=message, adapter=UnconfiguredAdapter())
    await session.commit()

    assert message.status == OutboundStatus.skipped.value
    assert message.error_code == "email_provider_not_configured"
    assert message.next_attempt_at is None
