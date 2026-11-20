"""The bubble engine: an inbound message becomes a Returning Customer bubble.

**A bubble is created only when the customer had a qualifying order *before* the
message** (CG-06). The comparison uses ``received_at`` — the provider's timestamp —
not the processing time. A webhook that arrives late must not make a first-time
buyer look like a returning one.

**One bubble per customer and conversation** (CG-08). A repeated message updates the
existing bubble's activity rather than creating a second one, and a message from a
*dismissed* customer re-opens it.

**No confident match means no figures** (CG-10). When identity resolution conflicts
or finds nothing, the bubble says so and offers "Link customer" — it never shows
another customer's numbers.

**The figures are recomputed from the authoritative history** (CG-09), so a new
qualifying order refreshes the card without the bubble engine keeping a counter.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.customer import Customer, CustomerOrder
from xenovarients.models.messaging import BubbleState, CustomerBubble, InboundMessageEvent
from xenovarients.platform.genome import customer_figures
from xenovarients.platform.identity import Resolution, ResolveOutcome, resolve

# The bubble's preview shows a short excerpt, not the whole message.
PREVIEW_LENGTH = 120


@dataclass(frozen=True)
class BubbleOutcome:
    """What processing one inbound message did."""

    bubble: CustomerBubble | None
    customer_id: uuid.UUID | None = None
    is_returning_customer: bool = False
    link_customer_offered: bool = False
    conflict_id: uuid.UUID | None = None
    reason: str | None = None


async def process_inbound_event(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    event: InboundMessageEvent,
    redis: Any | None = None,
) -> BubbleOutcome:
    """Turn one inbound message into a bubble, if it qualifies.

    Returns a ``BubbleOutcome`` describing what happened. A message that does not
    qualify produces no bubble and no exception — a first-time buyer messaging is
    a normal thing, not an error.
    """
    if event.direction != "inbound":
        return BubbleOutcome(bubble=None, reason="not_inbound")

    if event.channel_user_id is None:
        return BubbleOutcome(bubble=None, reason="no_channel_identity")

    resolution = await resolve(
        session,
        business_id=business_id,
        channel=event.channel,
        channel_user_id=event.channel_user_id,
    )
    event.resolved_customer_id = resolution.customer_id

    if resolution.outcome == ResolveOutcome.conflict:
        # A conflict is shown to staff, never resolved by guessing (CG-10).
        return BubbleOutcome(
            bubble=None,
            customer_id=None,
            link_customer_offered=True,
            conflict_id=resolution.conflict_id,
            reason="identity_conflict",
        )

    if resolution.outcome != ResolveOutcome.matched or resolution.customer_id is None:
        # No confident match: no figures, and staff are offered the link action.
        return BubbleOutcome(bubble=None, link_customer_offered=True, reason="no_match")

    customer_id = resolution.customer_id

    # CG-06: the qualifying orders must predate the *message*, not the processing.
    qualifying = await _qualifying_orders_before(
        session, business_id=business_id, customer_id=customer_id, before=event.received_at
    )

    if not qualifying:
        # A first-time buyer: no bubble, no label (CG-T02).
        return BubbleOutcome(bubble=None, customer_id=customer_id, reason="not_returning")

    bubble = await _upsert_bubble(
        session,
        business_id=business_id,
        customer_id=customer_id,
        event=event,
        qualifying_count=len(qualifying),
    )

    if redis is not None:
        await _publish(session, business_id=business_id, bubble=bubble, redis=redis)

    return BubbleOutcome(
        bubble=bubble,
        customer_id=customer_id,
        is_returning_customer=True,
    )


async def _qualifying_orders_before(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    customer_id: uuid.UUID,
    before: datetime,
) -> list[CustomerOrder]:
    """The customer's qualifying orders that predate the message."""
    result = await session.execute(
        select(CustomerOrder).where(
            CustomerOrder.business_id == business_id,
            CustomerOrder.customer_id == customer_id,
            CustomerOrder.qualifying.is_(True),
            CustomerOrder.ordered_at < before,
        )
    )
    return list(result.scalars().all())


async def _upsert_bubble(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    customer_id: uuid.UUID,
    event: InboundMessageEvent,
    qualifying_count: int,
) -> CustomerBubble:
    """Create or update the bubble for this customer and conversation."""
    conversation_id = event.conversation_id or event.channel_user_id or "default"

    result = await session.execute(
        select(CustomerBubble).where(
            CustomerBubble.business_id == business_id,
            CustomerBubble.customer_id == customer_id,
            CustomerBubble.conversation_id == conversation_id,
        )
    )
    bubble = result.scalar_one_or_none()

    figures = await customer_figures(
        session, business_id=business_id, customer_id=customer_id, as_of=event.received_at
    )

    if bubble is None:
        bubble = CustomerBubble(
            business_id=business_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            channel=event.channel,
        )
        session.add(bubble)
        bubble.state = BubbleState.new.value

    # A message from a dismissed customer re-opens the bubble (CG-08).
    if bubble.state == BubbleState.dismissed.value:
        bubble.state = BubbleState.new.value
        bubble.dismissed_at = None
        bubble.seen_at = None

    bubble.is_returning_customer = True
    bubble.order_count = figures.order_count
    bubble.total_spend = figures.total_spend
    bubble.currency = figures.currency
    bubble.last_purchase_at = figures.last_purchase_at
    bubble.data_as_of = figures.data_as_of
    bubble.last_message_at = event.received_at
    bubble.last_message_preview = _preview(event.content)
    bubble.link_customer_offered = False
    await session.flush()
    return bubble


def _preview(content: str | None) -> str | None:
    """A short excerpt of the message, for the bubble."""
    if not content:
        return None
    text = content.strip()
    if len(text) <= PREVIEW_LENGTH:
        return text
    return text[: PREVIEW_LENGTH - 1] + "…"


async def _publish(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    bubble: CustomerBubble,
    redis: Any,
) -> None:
    """Publish the bubble event to the business's subscribers."""
    from xenovarients.platform.realtime import Event, publish

    customer = await session.get(Customer, bubble.customer_id)
    name = customer.name if customer is not None else None

    await publish(
        redis,
        business_id,
        Event(
            type="bubble.created",
            data={
                "bubble_id": str(bubble.id),
                "customer_id": str(bubble.customer_id),
                "customer_name": name,
                "conversation_id": bubble.conversation_id,
                "channel": bubble.channel,
                "is_returning_customer": bubble.is_returning_customer,
                "order_count": bubble.order_count,
                "total_spend": str(bubble.total_spend),
                "currency": bubble.currency,
                "last_purchase_at": (
                    bubble.last_purchase_at.isoformat() if bubble.last_purchase_at else None
                ),
                "data_as_of": bubble.data_as_of.isoformat(),
                "last_message_at": bubble.last_message_at.isoformat(),
                "state": bubble.state,
            },
        ),
    )


async def list_bubbles(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    state: str | None = None,
    limit: int = 25,
    returning_only: bool = False,
) -> list[CustomerBubble]:
    """The bubbles for one business, newest activity first."""
    conditions = [CustomerBubble.business_id == business_id]
    if state is not None:
        conditions.append(CustomerBubble.state == state)
    if returning_only:
        conditions.append(CustomerBubble.is_returning_customer.is_(True))

    result = await session.execute(
        select(CustomerBubble)
        .where(*conditions)
        .order_by(CustomerBubble.last_message_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def mark_seen(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    bubble_id: uuid.UUID,
) -> CustomerBubble | None:
    """Mark a bubble seen."""
    bubble = await _get(session, business_id=business_id, bubble_id=bubble_id)
    if bubble is None:
        return None
    if bubble.state == BubbleState.new.value:
        bubble.state = BubbleState.seen.value
        bubble.seen_at = datetime.now(UTC)
    await session.flush()
    return bubble


async def dismiss(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    bubble_id: uuid.UUID,
) -> CustomerBubble | None:
    """Dismiss a bubble. A later message from the same customer re-opens it."""
    bubble = await _get(session, business_id=business_id, bubble_id=bubble_id)
    if bubble is None:
        return None
    bubble.state = BubbleState.dismissed.value
    bubble.dismissed_at = datetime.now(UTC)
    await session.flush()
    return bubble


async def _get(
    session: AsyncSession, *, business_id: uuid.UUID, bubble_id: uuid.UUID
) -> CustomerBubble | None:
    result = await session.execute(
        select(CustomerBubble).where(
            CustomerBubble.business_id == business_id,
            CustomerBubble.id == bubble_id,
        )
    )
    return result.scalar_one_or_none()


__all__ = [
    "BubbleOutcome",
    "Resolution",
    "dismiss",
    "list_bubbles",
    "mark_seen",
    "process_inbound_event",
]
