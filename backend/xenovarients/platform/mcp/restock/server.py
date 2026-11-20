"""Read-only Restock tools: waiting lists, detected restocks, batch preview, eligibility.

``confirm_batch`` is the one restock action that sends messages, and it is not here. A
tool can say exactly what a confirmation *would* do; the confirmation itself stays on the
owner-only, idempotent HTTP endpoint.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy import func, select

from xenovarients.models.customer import Customer
from xenovarients.models.messaging import (
    ContactPermission,
    InboundMessageEvent,
    MessagingIdentityLink,
)
from xenovarients.models.outbound import MessageTemplate
from xenovarients.models.restock import RestockEvent
from xenovarients.platform import eligibility, identity, restock
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

server = build_server(
    name="restock",
    title="XenoDesk Restock",
    instructions=(
        "Read-only answers about waiting lists and detected restocks, including a preview "
        "of what confirming a restock batch would send and whether one customer may be "
        "contacted on a channel. Nothing here sends or stores anything."
    ),
)


@read_only(server)
async def list_waiting_lists(
    ctx: Context,
    product_id: str | None = None,
    variant_id: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Waiting lists grouped by product and variant, newest request first.

    Each group carries its waiting customers with the contact value they left, so the
    demand behind a restock is visible rather than summarised away.
    """
    principal = await authenticate(ctx)
    product = parse_uuid(product_id, kind="product_id") if product_id else None
    variant = parse_uuid(variant_id, kind="variant_id") if variant_id else None

    async with tenant_session(principal.business_id) as session:
        groups, has_more = await restock.waiting_list(
            session,
            business_id=principal.business_id,
            product_id=product,
            variant_id=variant,
            limit=limit,
        )

    return result(
        groups=[
            {
                "product_id": str(group.product_id),
                "product_name": group.product_name,
                "variant_id": str(group.variant_id),
                "variant_name": group.variant_name,
                "stock_on_hand": group.stock_on_hand,
                "is_available": group.is_available,
                "waiting_count": group.waiting_count,
                "entries": [
                    {
                        "interest_id": str(entry.interest_id),
                        "customer_id": str(entry.customer_id),
                        "customer_name": entry.customer_name,
                        "contact_channel": entry.contact_channel,
                        "contact_value": entry.contact_value,
                        "requested_at": iso(entry.requested_at),
                        "quantity": entry.quantity,
                    }
                    for entry in group.entries
                ],
            }
            for group in groups
        ],
        has_more=has_more,
    )


@read_only(server)
async def list_restock_events(
    ctx: Context,
    product_id: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Detected restocks, newest first, with the waiting demand for each.

    A restock event means nothing has been sent. ``batch_count`` says whether an owner
    has already confirmed a batch for it.
    """
    principal = await authenticate(ctx)
    product = parse_uuid(product_id, kind="product_id") if product_id else None

    async with tenant_session(principal.business_id) as session:
        events = await restock.restock_events(
            session,
            business_id=principal.business_id,
            product_id=product,
            limit=limit,
        )

    return result(
        events=[
            {
                "event_id": str(event.event_id),
                "product_id": str(event.product_id),
                "product_name": event.product_name,
                "variant_id": str(event.variant_id),
                "variant_name": event.variant_name,
                "detected_at": iso(event.detected_at),
                "stock_after": event.stock_after,
                "waiting_count": event.waiting_count,
                "batch_count": event.batch_count,
                "last_batch_at": iso(event.last_batch_at),
            }
            for event in events
        ],
        truncated=len(events) == limit,
    )


@read_only(server)
async def preview_batch(
    ctx: Context,
    event_id: str,
    template_id: str | None = None,
) -> dict[str, Any]:
    """What confirming this restock event would send, and who would be skipped.

    Renders the template per recipient and evaluates eligibility exactly as the send
    path does — but ``preview`` writes nothing and no message is queued.
    """
    principal = await authenticate(ctx)
    identifier = parse_uuid(event_id, kind="event_id")

    async with tenant_session(principal.business_id) as session:
        event = await session.scalar(
            select(RestockEvent).where(
                RestockEvent.business_id == principal.business_id,
                RestockEvent.id == identifier,
            )
        )
        if event is None:
            return not_found("restock event", identifier)

        if template_id is not None:
            template = await session.scalar(
                select(MessageTemplate).where(
                    MessageTemplate.business_id == principal.business_id,
                    MessageTemplate.id == parse_uuid(template_id, kind="template_id"),
                    MessageTemplate.is_active.is_(True),
                )
            )
            if template is None:
                return not_found("message template", template_id)
        else:
            template = await restock.template_for_preview(
                session, business_id=principal.business_id
            )

        try:
            preview = await restock.preview(
                session,
                business_id=principal.business_id,
                event=event,
                template=template,
            )
        except restock.ReservationLanguageRejected as exc:
            return result(
                event_id=str(identifier),
                previewable=False,
                reason="reservation_language_rejected",
                detail=str(exc),
            )

        return result(
            event_id=str(identifier),
            previewable=True,
            template_version=template.version,
            waiting_count=preview.waiting_count,
            eligible_count=preview.eligible_count,
            skipped_count=preview.skipped_count,
            stock_after=preview.stock_after,
            stock_warning=preview.stock_warning,
            recipients=[
                {
                    "customer_id": str(recipient.customer_id),
                    "customer_name": recipient.customer_name,
                    "channel": recipient.channel,
                    "contact_value": recipient.contact_value,
                    "message": recipient.body,
                    "eligible": recipient.eligible,
                    "skip_reason": recipient.skip_reason,
                }
                for recipient in preview.recipients
            ],
            queued=0,
        )


@read_only(server)
async def check_eligibility(
    ctx: Context,
    customer_id: str,
    channel: str,
    purpose: str | None = None,
) -> dict[str, Any]:
    """Whether this app may contact one customer on one channel right now.

    The answer is the send path's own rule engine, with the facts it uses listed as
    ``evidence`` so a "no" is explainable. Messenger/WhatsApp stay ineligible once
    their free-reply window has closed, unless a verified template exists.
    """
    principal = await authenticate(ctx)
    identifier = parse_uuid(customer_id, kind="customer_id")
    rules = eligibility.load_rules()

    if channel not in rules.get("channels", {}):
        return result(
            eligible=False,
            channel=channel,
            reason="channel_not_enabled",
            reason_text=eligibility.reason_text(rules, "channel_not_enabled"),
        )

    async with tenant_session(principal.business_id) as session:
        customer = await session.scalar(
            select(Customer).where(
                Customer.business_id == principal.business_id,
                Customer.id == identifier,
            )
        )
        if customer is None:
            return not_found("customer", identifier)

        permission = await session.scalar(
            select(ContactPermission).where(
                ContactPermission.business_id == principal.business_id,
                ContactPermission.customer_id == identifier,
                ContactPermission.channel == channel,
            )
        )
        link = await session.scalar(
            select(MessagingIdentityLink).where(
                MessagingIdentityLink.business_id == principal.business_id,
                MessagingIdentityLink.customer_id == identifier,
                MessagingIdentityLink.channel == channel,
            )
        )
        has_consent = await identity.check_permission(
            session,
            business_id=principal.business_id,
            customer_id=identifier,
            channel=channel,
            purpose=purpose,
        )
        window_hours = rules["channels"][channel].get("free_reply_window_hours")
        within_window = True
        if window_hours:
            last_inbound = await session.scalar(
                select(func.max(InboundMessageEvent.received_at)).where(
                    InboundMessageEvent.business_id == principal.business_id,
                    InboundMessageEvent.resolved_customer_id == identifier,
                    InboundMessageEvent.channel == channel,
                )
            )
            within_window = bool(
                last_inbound is not None
                and last_inbound >= datetime.now(UTC) - timedelta(hours=int(window_hours))
            )

        # Read while the session is open: the rollback on exit expires loaded rows.
        contact_value = _contact_value(customer, permission, link, channel)
        opted_out = permission is not None and permission.opted_out_at is not None
        has_link = link is not None

    decision = eligibility.check(
        rules,
        channel=channel,
        has_consent=has_consent,
        has_verified_identity=has_link,
        opted_out=opted_out,
        has_contact_value=bool(contact_value),
        channel_enabled=bool(rules.get("defaults", {}).get(channel, False)),
        within_free_reply_window=within_window,
        requires_template=bool(rules["channels"][channel].get("requires_approved_template")),
        # No approved business-initiated template is stored yet, so a channel that needs
        # one stays ineligible — the same assumption the batch preview makes.
        has_approved_template=False,
    )

    return result(
        eligible=decision.eligible,
        channel=channel,
        customer_id=str(identifier),
        reason=decision.reason,
        reason_text=eligibility.reason_text(rules, decision.reason) if decision.reason else None,
        contact_value=contact_value if contact_value else None,
        evidence={
            "has_consent": has_consent,
            "has_verified_identity": has_link,
            "opted_out": opted_out,
            "channel_enabled": bool(rules.get("defaults", {}).get(channel, False)),
            "within_free_reply_window": within_window,
            "has_approved_template": False,
            "has_contact_value": bool(contact_value),
        },
    )


def _contact_value(
    customer: Customer,
    permission: ContactPermission | None,
    link: MessagingIdentityLink | None,
    channel: str,
) -> str | None:
    """The address the send path would use, from the most specific source."""
    if link is not None and link.channel_user_id:
        return link.channel_user_id
    if permission is not None and permission.contact_value:
        return permission.contact_value
    if channel == "email":
        return customer.email_normalised
    if channel in {"sms", "whatsapp"}:
        return customer.phone_e164
    return None

