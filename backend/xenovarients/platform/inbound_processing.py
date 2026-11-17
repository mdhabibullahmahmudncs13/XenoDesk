"""Processing the inbound queue: stored events become bubbles.

The webhook endpoint stores the event and acknowledges. Processing happens after,
so a slow resolution never makes a provider time out.

**Every unprocessed event is processed exactly once per run**, and the event's
``processed_at`` marks it done. A crash mid-processing leaves the event unprocessed,
so the next run picks it up again — the bubble's unique constraint makes that
harmless.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.messaging import InboundMessageEvent
from xenovarients.platform.bubbles import BubbleOutcome, process_inbound_event


@dataclass(frozen=True)
class ProcessingReport:
    """What one processing pass did."""

    processed: int
    bubbles_created: int
    qualified: int


async def process_pending_events(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    limit: int = 50,
    redis: Any | None = None,
) -> ProcessingReport:
    """Process the inbound events that have not been processed yet."""
    result = await session.execute(
        select(InboundMessageEvent)
        .where(
            InboundMessageEvent.business_id == business_id,
            InboundMessageEvent.processed_at.is_(None),
        )
        .order_by(InboundMessageEvent.received_at)
        .limit(limit)
    )
    events = list(result.scalars().all())

    processed = 0
    bubbles_created = 0
    qualified = 0

    for event in events:
        outcome = await process_inbound_event(
            session, business_id=business_id, event=event, redis=redis
        )
        event.processed_at = datetime.now(UTC)
        processed += 1
        if outcome.bubble is not None:
            bubbles_created += 1
            qualified += 1

    await session.flush()
    return ProcessingReport(
        processed=processed,
        bubbles_created=bubbles_created,
        qualified=qualified,
    )


async def process_one_event(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    event: InboundMessageEvent,
    redis: Any | None = None,
) -> BubbleOutcome:
    """Process one event and mark it done. Used by the job handler."""
    outcome = await process_inbound_event(
        session, business_id=business_id, event=event, redis=redis
    )
    event.processed_at = datetime.now(UTC)
    await session.flush()
    return outcome


__all__ = ["ProcessingReport", "process_one_event", "process_pending_events"]
