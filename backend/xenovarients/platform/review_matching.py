"""Match inbound customer replies to review requests."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.messaging import InboundMessageEvent
from xenovarients.models.review import (
    ConsentState,
    ReviewPermission,
    ReviewReply,
    ReviewRequest,
    ReviewRequestState,
)


@dataclass(frozen=True)
class ReviewMatch:
    """The request selected for an inbound reply, if any."""

    request: ReviewRequest | None
    needs_assignment: bool = False


async def match_review_reply(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    event: InboundMessageEvent,
) -> ReviewMatch:
    """Match by reference token first, then by the customer's reply channel."""
    content = event.content or ""
    requests = list(
        (
            await session.execute(
                select(ReviewRequest).where(
                    ReviewRequest.business_id == business_id,
                    ReviewRequest.state == ReviewRequestState.sent.value,
                )
            )
        )
        .scalars()
        .all()
    )
    token_matches = [request for request in requests if request.reference_token in content]
    if len(token_matches) == 1:
        return await _link(session, event, token_matches[0])

    if event.resolved_customer_id is not None:
        thread_matches = [
            request
            for request in requests
            if request.customer_id == event.resolved_customer_id
            and request.sent_channel == event.channel
        ]
        if len(thread_matches) == 1:
            return await _link(session, event, thread_matches[0])
        if len(thread_matches) > 1:
            for request in thread_matches:
                request.state = ReviewRequestState.needs_assignment.value
                request.state_reason = "multiple_review_threads"
            return ReviewMatch(request=None, needs_assignment=True)

    return ReviewMatch(request=None, needs_assignment=bool(token_matches))


async def _link(
    session: AsyncSession,
    event: InboundMessageEvent,
    request: ReviewRequest,
) -> ReviewMatch:
    event.review_request_id = request.id
    request.state = ReviewRequestState.replied.value
    request.state_reason = None
    existing = await session.scalar(
        select(ReviewReply).where(ReviewReply.inbound_message_id == event.id)
    )
    if existing is None and event.content:
        reply = ReviewReply(
            business_id=event.business_id,
            review_request_id=request.id,
            inbound_message_id=event.id,
            customer_id=request.customer_id,
            order_id=request.order_id,
            content=event.content,
            message_id=event.message_id or event.provider_event_id,
            channel=event.channel,
            received_at=event.received_at,
        )
        session.add(reply)
        await session.flush()
        session.add(
            ReviewPermission(
                business_id=event.business_id,
                review_request_id=request.id,
                review_reply_id=reply.id,
                customer_id=request.customer_id,
                state=ConsentState.pending.value,
                consent_method="manual",
            )
        )
    return ReviewMatch(request=request)
