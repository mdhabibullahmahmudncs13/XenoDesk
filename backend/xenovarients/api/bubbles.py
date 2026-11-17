"""The Returning Customer Bubbles endpoints.

A bubble is one customer's conversation that is worth an owner's attention. The list
carries the figures; the ``seen`` and ``dismiss`` actions move the bubble through
its states.

**A bubble with no confident identity match carries no figures at all** (CG-10) —
no name, no order count, no spend — and says that "Link customer" is offered.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.api.deps import Principal, get_principal, get_tenant_session
from xenovarients.api.errors import NotFound
from xenovarients.models.customer import Customer
from xenovarients.models.messaging import CustomerBubble
from xenovarients.platform.bubbles import dismiss, list_bubbles, mark_seen

router = APIRouter(prefix="/api/v1/customer-genome", tags=["customer-genome"])


class BubbleCustomerOut(BaseModel):
    id: str
    name: str | None = None
    initials: str | None = None


class BubbleOut(BaseModel):
    """One bubble, as the dashboard card shows it."""

    id: str
    customer: BubbleCustomerOut
    is_returning_customer: bool
    conversation_id: str
    channel: str
    state: str
    previous_order_count: int
    total_purchase_amount: str
    currency: str
    last_purchase_at: str | None = None
    last_purchase_date: str | None = None
    last_message_at: str
    last_message_preview: str | None = None
    data_as_of: str
    link_customer_offered: bool = False
    history_url: str | None = None


class BubblesOut(BaseModel):
    items: list[BubbleOut]
    data_as_of: str


def _initials(name: str | None) -> str | None:
    """The customer's initials, for the bubble's avatar."""
    if not name:
        return None
    parts = [part for part in name.split() if part]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][:1] + parts[-1][:1]).upper()


def _serialize(bubble: CustomerBubble, customer: Customer | None) -> BubbleOut:
    name = customer.name if customer is not None else None
    return BubbleOut(
        id=str(bubble.id),
        customer=BubbleCustomerOut(
            id=str(bubble.customer_id),
            name=name,
            initials=_initials(name),
        ),
        is_returning_customer=bubble.is_returning_customer,
        conversation_id=bubble.conversation_id,
        channel=bubble.channel,
        state=bubble.state,
        previous_order_count=bubble.order_count,
        total_purchase_amount=str(bubble.total_spend),
        currency=bubble.currency,
        last_purchase_at=(bubble.last_purchase_at.isoformat() if bubble.last_purchase_at else None),
        last_purchase_date=(
            bubble.last_purchase_at.date().isoformat() if bubble.last_purchase_at else None
        ),
        last_message_at=bubble.last_message_at.isoformat(),
        last_message_preview=bubble.last_message_preview,
        data_as_of=bubble.data_as_of.isoformat(),
        link_customer_offered=bubble.link_customer_offered,
        history_url=(
            f"/customers/{bubble.customer_id}/history" if bubble.is_returning_customer else None
        ),
    )


@router.get("/returning-bubbles")
async def list_returning_bubbles(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
    state: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> BubblesOut:
    """The bubbles for this business, newest activity first."""
    bubbles = await list_bubbles(
        session,
        business_id=principal.business_id,
        state=state,
        limit=limit,
    )

    items: list[BubbleOut] = []
    for bubble in bubbles:
        customer = await session.scalar(
            select(Customer).where(
                Customer.business_id == principal.business_id,
                Customer.id == bubble.customer_id,
            )
        )
        items.append(_serialize(bubble, customer))

    return BubblesOut(
        items=items,
        data_as_of=datetime.now(UTC).isoformat(),
    )


@router.get("/returning-bubbles/{bubble_id}")
async def get_returning_bubble(
    bubble_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> BubbleOut:
    """One bubble's detail."""
    bubble = await session.scalar(
        select(CustomerBubble).where(
            CustomerBubble.business_id == principal.business_id,
            CustomerBubble.id == bubble_id,
        )
    )
    if bubble is None:
        raise NotFound("No such bubble.")

    customer = await session.scalar(
        select(Customer).where(
            Customer.business_id == principal.business_id,
            Customer.id == bubble.customer_id,
        )
    )
    return _serialize(bubble, customer)


class BubbleStateIn(BaseModel):
    """The state change a client is asking for."""

    state: str


@router.patch("/returning-bubbles/{bubble_id}")
async def update_returning_bubble(
    bubble_id: uuid.UUID,
    body: BubbleStateIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> BubbleOut:
    """Move a bubble to ``seen`` or ``dismissed``.

    A dismissed bubble re-opens on the next message from that customer.
    """
    if body.state not in {"seen", "dismissed", "new"}:
        raise NotFound(f"Unknown bubble state '{body.state}'.")

    if body.state == "dismissed":
        bubble = await dismiss(session, business_id=principal.business_id, bubble_id=bubble_id)
    else:
        bubble = await mark_seen(session, business_id=principal.business_id, bubble_id=bubble_id)
    if bubble is None:
        raise NotFound("No such bubble.")
    await session.commit()

    customer = await session.scalar(
        select(Customer).where(
            Customer.business_id == principal.business_id,
            Customer.id == bubble.customer_id,
        )
    )
    return _serialize(bubble, customer)
