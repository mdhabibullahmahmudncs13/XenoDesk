"""Read-only Customer Genome tools: history, repeat buyers, bubbles and identity.

The two identity tools are deliberately previews. The API's ``POST /link-identity``
writes a link, and ``identity.resolve`` records a conflict row when the ladder is
ambiguous — both belong to a human-confirmed action. Here the same rules are applied
and the *outcome* is reported, with nothing written (``persisted: false``).
"""

import uuid
from datetime import datetime
from typing import Any, cast

from mcp.server.mcpserver import Context
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.customer import Customer
from xenovarients.models.messaging import CustomerBubble, IdentityMethod, MessagingIdentityLink
from xenovarients.platform import bubbles, genome, identity
from xenovarients.platform.mcp.shared import (
    authenticate,
    build_server,
    iso,
    not_found,
    parse_uuid,
    read_only,
    result,
    tenant_session,
)

CHANNELS = frozenset({"email", "sms", "messenger", "whatsapp"})

server = build_server(
    name="customer_genome",
    title="XenoDesk Customer Genome",
    instructions=(
        "Read-only answers about a business's customers: order history, repeat buyers, "
        "returning-customer bubbles, and identity resolution. Nothing here changes data. "
        "Authenticate with a Bearer token and X-Business-Id."
    ),
)


@read_only(server)
async def get_customer_history(
    ctx: Context,
    customer_id: str,
    limit: int = 25,
    cursor: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    product_id: str | None = None,
) -> dict[str, Any]:
    """A customer's order timeline, newest first, with date and product filters.

    Reads the same derived history as the customer page. ``cursor`` is the value from a
    previous call's ``next_cursor``.
    """
    principal = await authenticate(ctx)
    identifier = parse_uuid(customer_id, kind="customer_id")
    product = parse_uuid(product_id, kind="product_id") if product_id else None

    async with tenant_session(principal.business_id) as session:
        exists = await session.scalar(
            select(Customer.id).where(
                Customer.business_id == principal.business_id,
                Customer.id == identifier,
            )
        )
        if exists is None:
            return not_found("customer", identifier)

        page = await genome.customer_history(
            session,
            business_id=principal.business_id,
            customer_id=identifier,
            limit=min(max(limit, 1), 100),
            cursor=cursor,
            since=since,
            until=until,
            product_id=product,
        )
        figures = await genome.customer_figures(
            session, business_id=principal.business_id, customer_id=identifier
        )

    return result(
        customer_id=str(identifier),
        figures={
            "order_count": figures.order_count,
            "total_spend": str(figures.total_spend),
            "currency": figures.currency,
            "last_purchase_at": iso(figures.last_purchase_at),
            "data_as_of": iso(figures.data_as_of),
            "is_returning_customer": figures.is_returning_customer,
            "is_repeat_buyer": figures.is_repeat_buyer,
        },
        orders=[
            {
                "order_id": entry.order_id,
                "source_order_id": entry.source_order_id,
                "ordered_at": iso(entry.ordered_at),
                "status": entry.status,
                "qualifying": entry.qualifying,
                "total_amount": str(entry.total_amount),
                "refund_amount": str(entry.refund_amount),
                "currency": entry.currency,
                "items": list(entry.items),
            }
            for entry in page.entries
        ],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@read_only(server)
async def list_repeat_buyers(
    ctx: Context,
    limit: int = 25,
    cursor: str | None = None,
    name_contains: str | None = None,
    since: datetime | None = None,
) -> dict[str, Any]:
    """Customers with two or more qualifying orders, newest purchase first.

    The count is recomputed from the orders, never read from a cached counter.
    """
    principal = await authenticate(ctx)
    async with tenant_session(principal.business_id) as session:
        buyers, next_cursor = await genome.repeat_buyers(
            session,
            business_id=principal.business_id,
            limit=min(max(limit, 1), 100),
            cursor=cursor,
            name_contains=name_contains,
            since=since,
        )

    return result(
        threshold=genome.repeat_buyer_threshold(),
        buyers=[
            {
                "customer_id": str(buyer.customer_id),
                "name": buyer.name,
                "phone_e164": buyer.phone_e164,
                "email_normalised": buyer.email_normalised,
                "order_count": buyer.order_count,
                "total_spend": str(buyer.total_spend),
                "currency": buyer.currency,
                "last_purchase_at": iso(buyer.last_purchase_at),
            }
            for buyer in buyers
        ],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )


@read_only(server)
async def get_returning_bubbles(
    ctx: Context,
    state: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """The bubbles flagged as returning customers, newest activity first.

    A bubble that is not flagged carries no figures at all (CG-10), so it is not in this
    list rather than being shown with zeros.
    """
    principal = await authenticate(ctx)
    async with tenant_session(principal.business_id) as session:
        rows = await bubbles.list_bubbles(
            session,
            business_id=principal.business_id,
            state=state,
            limit=min(max(limit, 1), 100),
            returning_only=True,
        )

    return result(
        bubbles=[_bubble_payload(row) for row in rows],
        count=len(rows),
    )


def _bubble_payload(row: CustomerBubble) -> dict[str, Any]:
    return {
        "bubble_id": str(row.id),
        "customer_id": str(row.customer_id),
        "conversation_id": row.conversation_id,
        "channel": row.channel,
        "state": row.state,
        "order_count": row.order_count,
        "total_spend": str(row.total_spend),
        "currency": row.currency,
        "last_purchase_at": iso(row.last_purchase_at),
        "last_message_at": iso(row.last_message_at),
        "last_message_preview": row.last_message_preview,
        "data_as_of": iso(row.data_as_of),
    }


@read_only(server)
async def link_identity(
    ctx: Context,
    customer_id: str,
    channel: str,
    channel_user_id: str,
    method: str = IdentityMethod.staff_link.value,
) -> dict[str, Any]:
    """Validate linking a messaging identity to a customer — without linking it.

    Returns whether the link would succeed, the existing link when there is one, and the
    reason it would be refused. ``persisted`` is always false: the link itself is created
    by the owner-confirmed ``POST /customers/{id}/link-identity`` endpoint.
    """
    principal = await authenticate(ctx)
    if channel not in CHANNELS:
        return result(
            applied=False,
            persisted=False,
            would_link=False,
            reason="unknown_channel",
            detail=f"channel must be one of: {', '.join(sorted(CHANNELS))}.",
        )
    methods = {item.value for item in IdentityMethod}
    if method not in methods:
        return result(
            applied=False,
            persisted=False,
            would_link=False,
            reason="unknown_method",
            detail=f"method must be one of: {', '.join(sorted(methods))}.",
        )

    identifier = parse_uuid(customer_id, kind="customer_id")
    async with tenant_session(principal.business_id) as session:
        customer = await session.scalar(
            select(Customer.id).where(
                Customer.business_id == principal.business_id,
                Customer.id == identifier,
            )
        )
        if customer is None:
            return not_found("customer", identifier)

        existing = await _link(session, principal.business_id, channel, channel_user_id)
        # Built inside the session: the rollback on exit expires loaded rows.
        current = (
            {
                "link_id": str(existing.id),
                "customer_id": str(existing.customer_id),
                "channel": existing.channel,
                "channel_user_id": existing.channel_user_id,
                "method": existing.method,
            }
            if existing is not None
            else None
        )
        existing_customer_id = existing.customer_id if existing is not None else None

    if existing_customer_id == identifier:
        would_link = True
        reason = "already_linked"
    elif existing_customer_id is not None:
        would_link = False
        reason = "identity_already_linked"
    else:
        would_link = True
        reason = "would_link"

    return result(
        applied=False,
        persisted=False,
        would_link=would_link,
        reason=reason,
        customer_id=str(identifier),
        channel=channel,
        channel_user_id=channel_user_id,
        method=method,
        existing_link=current,
        detail=(
            "Already linked to this customer; re-linking is a no-op."
            if reason == "already_linked"
            else "This identity is linked to a different customer; a human must resolve it."
            if reason == "identity_already_linked"
            else "No link exists yet. Confirm in the app to create it."
        ),
    )


@read_only(server)
async def resolve_customer(
    ctx: Context,
    channel: str,
    channel_user_id: str,
    phone: str | None = None,
    email: str | None = None,
) -> dict[str, Any]:
    """Walk the identity ladder (link → phone → email → staff link) without writing.

    An ambiguous rung returns every candidate and ``outcome: "conflict"``. Unlike the
    API path, the conflict is **not** recorded here — ``persisted_conflicts`` is false.
    """
    principal = await authenticate(ctx)
    if channel not in CHANNELS:
        return result(
            outcome="no_match",
            reason="unknown_channel",
            detail=f"channel must be one of: {', '.join(sorted(CHANNELS))}.",
            persisted_conflicts=False,
        )

    async with tenant_session(principal.business_id) as session:
        link = await _link(session, principal.business_id, channel, channel_user_id)
        if link is not None:
            return result(
                outcome="matched",
                method=IdentityMethod.verified_link.value,
                customer_id=str(link.customer_id),
                candidates=[],
                persisted_conflicts=False,
            )

        raw_phone = phone or (channel_user_id if channel in {"sms", "whatsapp"} else "")
        phone_e164 = identity.normalise_phone(raw_phone) if raw_phone else ""
        if phone_e164:
            candidates = await _candidates(session, principal.business_id, phone_e164=phone_e164)
            if len(candidates) == 1:
                return result(
                    outcome="matched",
                    method=IdentityMethod.phone.value,
                    customer_id=str(candidates[0]),
                    candidates=[],
                    persisted_conflicts=False,
                )
            if len(candidates) > 1:
                return result(
                    outcome="conflict",
                    method=IdentityMethod.phone.value,
                    reason="multiple_phone_matches",
                    customer_id=None,
                    candidates=[str(item) for item in candidates],
                    persisted_conflicts=False,
                )

        email_normalised = identity.normalise_email(email) if email else ""
        if email_normalised:
            candidates = await _candidates(
                session, principal.business_id, email_normalised=email_normalised
            )
            if len(candidates) == 1:
                return result(
                    outcome="matched",
                    method=IdentityMethod.email.value,
                    customer_id=str(candidates[0]),
                    candidates=[],
                    persisted_conflicts=False,
                )
            if len(candidates) > 1:
                return result(
                    outcome="conflict",
                    method=IdentityMethod.email.value,
                    reason="multiple_email_matches",
                    customer_id=None,
                    candidates=[str(item) for item in candidates],
                    persisted_conflicts=False,
                )

        staff_link = await _link(session, principal.business_id, channel, channel_user_id)
        if staff_link is not None:
            return result(
                outcome="matched",
                method=IdentityMethod.staff_link.value,
                customer_id=str(staff_link.customer_id),
                candidates=[],
                persisted_conflicts=False,
            )

    return result(
        outcome="no_match",
        method=None,
        customer_id=None,
        candidates=[],
        persisted_conflicts=False,
    )


async def _link(
    session: AsyncSession, business_id: uuid.UUID, channel: str, channel_user_id: str
) -> MessagingIdentityLink | None:
    return cast(
        MessagingIdentityLink | None,
        await session.scalar(
            select(MessagingIdentityLink).where(
                MessagingIdentityLink.business_id == business_id,
                MessagingIdentityLink.channel == channel,
                MessagingIdentityLink.channel_user_id == channel_user_id,
            )
        ),
    )


async def _candidates(
    session: AsyncSession,
    business_id: uuid.UUID,
    *,
    phone_e164: str = "",
    email_normalised: str = "",
) -> list[uuid.UUID]:
    stmt = select(Customer.id).where(Customer.business_id == business_id)
    if phone_e164:
        stmt = stmt.where(Customer.phone_e164 == phone_e164)
    if email_normalised:
        stmt = stmt.where(Customer.email_normalised == email_normalised)
    return list((await session.execute(stmt)).scalars().all())

