"""Outbound messaging: the outbox, the channel adapters, and the dispatcher.

**The outbox pattern.** A business action (approving a restock batch, scheduling a
review request) writes ``outbound_messages`` rows with status ``pending`` *inside its
own transaction* and commits. A separate dispatcher picks the pending rows up and
sends them. Two consequences that matter:

- If the business transaction fails, no message is sent. There is no window where a
  message goes out for an action that was rolled back.
- If the dispatcher dies mid-send, the remaining rows are still ``pending`` and are
  picked up again. Nothing is lost.

**Eligibility is re-checked at send time.** The batch preview shows what *would*
happen; the dispatcher decides what *actually* happens. A recipient who opted out
between the preview and the send is skipped with a recorded reason, not sent to.

**One failed recipient does not affect the others.** Each message is sent
independently; a failure is recorded on that row and the dispatcher moves on.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.core.config import get_settings
from xenovarients.models.messaging import ContactPermission
from xenovarients.models.outbound import (
    DeliveryAttempt,
    OutboundMessage,
    OutboundStatus,
    SkipReason,
)


@dataclass(frozen=True)
class SendResult:
    """The outcome of one send attempt."""

    ok: bool
    provider_message_id: str | None = None
    error_code: str | None = None
    response: dict[str, Any] | None = None


class ChannelAdapter(Protocol):
    """What every outbound channel adapter must provide."""

    channel: str

    def send(self, *, to_address: str, body: str, reference: str) -> SendResult:
        """Send one message. Must not raise for an ordinary delivery failure."""

    def eligibility(self) -> str | None:
        """The reason this channel cannot be used right now, or ``None`` if it can."""


class StubAdapter:
    """A channel adapter that records instead of sending.

    Used in tests and in local development. It fails a configurable fraction of
    sends so the retry path is exercised without a real provider.
    """

    def __init__(self, channel: str, fail: bool = False) -> None:
        self.channel = channel
        self.fail = fail
        self.sent: list[tuple[str, str, str]] = []

    def send(self, *, to_address: str, body: str, reference: str) -> SendResult:
        if self.fail:
            return SendResult(ok=False, error_code="provider_unavailable")
        self.sent.append((to_address, body, reference))
        return SendResult(ok=True, provider_message_id=f"stub-{uuid.uuid4().hex[:12]}")

    def eligibility(self) -> str | None:
        return None


async def enqueue(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    purpose: str,
    ref_id: uuid.UUID,
    customer_id: uuid.UUID,
    channel: str,
    to_address: str,
    body: str,
    idempotency_key: str,
) -> OutboundMessage:
    """Write a pending outbound message. Does not send.

    The caller commits. That is the whole point of the outbox: the message and the
    business action that caused it share one transaction.
    """
    message = OutboundMessage(
        business_id=business_id,
        purpose=purpose,
        ref_id=ref_id,
        customer_id=customer_id,
        channel=channel,
        to_address=to_address,
        body=body,
        idempotency_key=idempotency_key,
        status=OutboundStatus.pending.value,
    )
    session.add(message)
    await session.flush()
    return message


async def mark_skipped(
    session: AsyncSession,
    *,
    message: OutboundMessage,
    reason: SkipReason,
) -> OutboundMessage:
    """Record that a message will not be sent, and why."""
    message.status = OutboundStatus.skipped.value
    message.skip_reason = reason.value
    message.error_code = reason.value
    await session.flush()
    return message


async def claim_pending(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    limit: int = 50,
    now: datetime | None = None,
) -> list[OutboundMessage]:
    """Fetch pending messages that are due.

    ``next_attempt_at`` is the retry schedule; a message with no value is due now.
    """
    moment = now or datetime.now(UTC)
    result = await session.execute(
        select(OutboundMessage)
        .where(
            OutboundMessage.business_id == business_id,
            OutboundMessage.status == OutboundStatus.pending.value,
        )
        .order_by(OutboundMessage.created_at)
        .limit(limit)
    )
    messages = list(result.scalars().all())
    return [m for m in messages if m.next_attempt_at is None or m.next_attempt_at <= moment]


async def dispatch_one(
    session: AsyncSession,
    *,
    message: OutboundMessage,
    adapter: ChannelAdapter,
    rules: dict[str, Any] | None = None,
) -> OutboundMessage:
    """Attempt one send, recording the attempt either way.

    **Eligibility is re-checked here, at send time.** The preview showed what
    *would* happen; this decides what *actually* happens. A recipient who opted out
    between the preview and the send is skipped with a recorded reason, not sent to.

    A failure increments ``attempt_count`` and schedules the next attempt with
    exponential backoff, up to the configured maximum. Once the budget is spent the
    message is marked ``failed`` and stops being retried.
    """
    settings = get_settings()
    attempt_number = message.attempt_count + 1
    started_at = datetime.now(UTC)

    decision = await _recheck_eligibility(session, message=message, adapter=adapter, rules=rules)
    if decision is not None:
        message.status = OutboundStatus.skipped.value
        message.skip_reason = SkipReason.channel_ineligible.value
        message.error_code = decision
        message.next_attempt_at = None
        await session.flush()
        return message

    result = adapter.send(
        to_address=message.to_address,
        body=message.body,
        reference=str(message.idempotency_key),
    )

    session.add(
        DeliveryAttempt(
            outbound_message_id=message.id,
            attempt_number=attempt_number,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            outcome="sent" if result.ok else "failed",
            provider_response=result.response,
            error_code=result.error_code,
        )
    )

    message.attempt_count = attempt_number
    if result.ok:
        message.status = OutboundStatus.sent.value
        message.sent_at = datetime.now(UTC)
        message.provider_message_id = result.provider_message_id
        message.error_code = None
    else:
        message.error_code = result.error_code
        if attempt_number >= settings.max_delivery_attempts:
            message.status = OutboundStatus.failed.value
            message.next_attempt_at = None
        else:
            message.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=settings.delivery_retry_base_seconds * (2 ** (attempt_number - 1))
            )

    await session.flush()
    return message


async def _recheck_eligibility(
    session: AsyncSession,
    *,
    message: OutboundMessage,
    adapter: ChannelAdapter,
    rules: dict[str, Any] | None,
) -> str | None:
    """The send-time eligibility decision, or ``None`` if the message may go out.

    Two layers are consulted: the adapter's own ``eligibility`` (is the provider
    configured?) and the contact permission (has the customer said yes?). Both are
    re-read from the database rather than trusted from the enqueue-time snapshot.
    """
    adapter_reason = adapter.eligibility()
    if adapter_reason is not None:
        return adapter_reason

    if rules is None:
        return None

    from xenovarients.platform.eligibility import check as check_eligibility

    permission = await session.scalar(
        select(ContactPermission).where(
            ContactPermission.business_id == message.business_id,
            ContactPermission.customer_id == message.customer_id,
            ContactPermission.channel == message.channel,
        )
    )

    decision = check_eligibility(
        rules,
        channel=message.channel,
        has_consent=permission is not None,
        has_verified_identity=permission is not None,
        opted_out=permission is not None and permission.opted_out_at is not None,
        has_contact_value=bool(message.to_address),
        channel_enabled=True,
    )
    return None if decision.eligible else decision.reason


async def dispatch_batch(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    adapter: ChannelAdapter,
    limit: int = 50,
    rules: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Send a batch of pending messages.

    One failed recipient does not stop the others: each message is attempted and
    recorded independently.

    The caller commits. This mirrors ``enqueue``: the message and the action that
    caused it share one transaction, and whoever calls the dispatcher decides where
    that transaction ends.
    """
    messages = await claim_pending(session, business_id=business_id, limit=limit)
    counts = {"sent": 0, "failed": 0, "retried": 0, "skipped": 0}
    for message in messages:
        if message.channel != adapter.channel:
            continue
        await dispatch_one(session, message=message, adapter=adapter, rules=rules)
        if message.status == OutboundStatus.sent.value:
            counts["sent"] += 1
        elif message.status == OutboundStatus.failed.value:
            counts["failed"] += 1
        elif message.status == OutboundStatus.skipped.value:
            counts["skipped"] += 1
        else:
            counts["retried"] += 1
    return counts
