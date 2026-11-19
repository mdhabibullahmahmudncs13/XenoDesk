"""Restore Product endpoints: waiting list, batch preview, confirmation, history.

The confirmation is the only endpoint in this module that results in a message, and it
requires the Owner role plus an ``Idempotency-Key`` (RP-07, RP-08). Everything else
reads or records an interest a staff member entered.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.api.deps import (
    Principal,
    get_principal,
    get_tenant_session,
    require_admin,
    require_owner,
)
from xenovarients.api.errors import BadRequest, Conflict, NotFound
from xenovarients.models.customer import Customer, Product, ProductVariant
from xenovarients.models.outbound import MessageTemplate
from xenovarients.models.restock import RestockEvent
from xenovarients.platform import restock

router = APIRouter(prefix="/api/v1/customer-genome", tags=["customer-genome"])

CHANNELS = {"email", "sms", "messenger", "whatsapp"}


class WaitingEntryOut(BaseModel):
    """One customer waiting for one variant (RP-02)."""

    interest_id: str
    customer_id: str
    customer_name: str | None = None
    contact_channel: str
    contact_value: str
    requested_at: str
    quantity: int | None = None


class WaitingGroupOut(BaseModel):
    """One variant's waiting list (RP-03)."""

    product_id: str
    product_name: str
    variant_id: str
    variant_name: str
    stock_on_hand: int
    is_available: bool
    waiting_count: int
    entries: list[WaitingEntryOut] = []


class WaitingListOut(BaseModel):
    items: list[WaitingGroupOut]
    has_more: bool = False


def _entry_out(entry: restock.WaitingEntry) -> WaitingEntryOut:
    return WaitingEntryOut(
        interest_id=str(entry.interest_id),
        customer_id=str(entry.customer_id),
        customer_name=entry.customer_name,
        contact_channel=entry.contact_channel,
        contact_value=entry.contact_value,
        requested_at=entry.requested_at.isoformat(),
        quantity=entry.quantity,
    )


@router.get("/product-interests")
async def list_product_interests(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
    product_id: uuid.UUID | None = Query(default=None),
    variant_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> WaitingListOut:
    """The waiting lists, grouped by product and variant — variants are never mixed."""
    groups, has_more = await restock.waiting_list(
        session,
        business_id=principal.business_id,
        product_id=product_id,
        variant_id=variant_id,
        limit=limit,
    )
    return WaitingListOut(
        items=[
            WaitingGroupOut(
                product_id=str(group.product_id),
                product_name=group.product_name,
                variant_id=str(group.variant_id),
                variant_name=group.variant_name,
                stock_on_hand=group.stock_on_hand,
                is_available=group.is_available,
                waiting_count=group.waiting_count,
                entries=[_entry_out(entry) for entry in group.entries],
            )
            for group in groups
        ],
        has_more=has_more,
    )


class InterestIn(BaseModel):
    """The staff "Add to waiting list" action (RP-02)."""

    customer_id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID
    contact_channel: str = "email"
    contact_value: str | None = None
    quantity: int | None = None


@router.post("/product-interests", status_code=201)
async def add_product_interest(
    body: InterestIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> WaitingEntryOut:
    """Add a customer to a variant's waiting list."""
    if body.contact_channel not in CHANNELS:
        raise BadRequest(f"Unknown channel '{body.contact_channel}'.")

    customer = await session.scalar(
        select(Customer).where(
            Customer.business_id == principal.business_id,
            Customer.id == body.customer_id,
        )
    )
    if customer is None:
        raise NotFound("No such customer.")

    product = await session.scalar(
        select(Product).where(
            Product.business_id == principal.business_id,
            Product.id == body.product_id,
        )
    )
    if product is None:
        raise NotFound("No such product.")

    variant = await session.scalar(
        select(ProductVariant).where(
            ProductVariant.business_id == principal.business_id,
            ProductVariant.id == body.variant_id,
        )
    )
    if variant is None or variant.product_id != product.id:
        raise BadRequest("That variant does not belong to that product.")

    value = body.contact_value or _default_contact(customer, body.contact_channel)
    if not value:
        raise BadRequest("The customer has no address on this channel; pass contact_value.")

    row = await restock.add_interest(
        session,
        business_id=principal.business_id,
        customer_id=customer.id,
        product_id=product.id,
        variant_id=variant.id,
        contact_channel=body.contact_channel,
        contact_value=value,
        quantity=body.quantity,
        created_by_user_id=principal.user_id,
    )
    await session.commit()

    return WaitingEntryOut(
        interest_id=str(row.id),
        customer_id=str(row.customer_id),
        customer_name=customer.name,
        contact_channel=row.contact_channel,
        contact_value=row.contact_value,
        requested_at=row.requested_at.isoformat(),
        quantity=row.quantity,
    )


class RestockEventOut(BaseModel):
    """One detected restock, with its waiting demand (RP-04, RP-09)."""

    id: str
    product_id: str
    product_name: str
    variant_id: str
    variant_name: str
    detected_at: str
    stock_after: int
    waiting_count: int
    batch_count: int
    last_batch_at: str | None = None
    preview_url: str


class RestockEventsOut(BaseModel):
    items: list[RestockEventOut] = []


@router.get("/restocks")
async def list_restock_events(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
    product_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> RestockEventsOut:
    """Restock events for this business. A restock is a notification, not a send."""
    events = await restock.restock_events(
        session,
        business_id=principal.business_id,
        product_id=product_id,
        limit=limit,
    )
    return RestockEventsOut(
        items=[
            RestockEventOut(
                id=str(event.event_id),
                product_id=str(event.product_id),
                product_name=event.product_name,
                variant_id=str(event.variant_id),
                variant_name=event.variant_name,
                detected_at=event.detected_at.isoformat(),
                stock_after=event.stock_after,
                waiting_count=event.waiting_count,
                batch_count=event.batch_count,
                last_batch_at=(
                    event.last_batch_at.isoformat() if event.last_batch_at else None
                ),
                preview_url=f"/customer-genome/restock-events/{event.event_id}/preview",
            )
            for event in events
        ]
    )


class TemplateOut(BaseModel):
    """The restock message template the owner edits (RP-05)."""

    id: str | None = None
    body: str
    version: int
    is_default: bool = False
    merge_fields: list[str] = []


class TemplateIn(BaseModel):
    body: str


@router.get("/restock-template")
async def get_restock_template(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> TemplateOut:
    """The active restock template, or the default body when none is saved.

    Reading never creates the template: the preview renders the default until the
    owner saves their own words.
    """
    template = await restock.active_template(session, business_id=principal.business_id)
    if template is None:
        return TemplateOut(
            id=None,
            body=restock.DEFAULT_TEMPLATE_BODY,
            version=0,
            is_default=True,
            merge_fields=list(restock.MERGE_FIELDS),
        )
    return TemplateOut(
        id=str(template.id),
        body=template.body,
        version=template.version,
        is_default=False,
        merge_fields=list(restock.MERGE_FIELDS),
    )


@router.put("/restock-template")
async def save_restock_template(
    body: TemplateIn,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
) -> TemplateOut:
    """Save a new template version. Owner and Admin only."""
    text = body.body.strip()
    if not text:
        raise BadRequest("The template body cannot be empty.")
    try:
        template = await restock.set_template(
            session, business_id=principal.business_id, body=text
        )
    except restock.ReservationLanguageRejected as exc:
        raise BadRequest(str(exc)) from exc
    await session.commit()
    return TemplateOut(
        id=str(template.id),
        body=template.body,
        version=template.version,
        is_default=False,
        merge_fields=list(restock.MERGE_FIELDS),
    )


class PreviewRecipientOut(BaseModel):
    """One recipient, with the channel chosen and the reason if skipped (RP-06)."""

    customer_id: str
    customer_name: str | None = None
    channel: str
    contact_value: str
    message: str
    eligible: bool
    skip_reason: str | None = None


class PreviewOut(BaseModel):
    """The batch preview the owner confirms (RP-05, RP-07, RP-09)."""

    restock_event_id: str
    waiting_count: int
    eligible_count: int
    skipped_count: int
    stock_after: int
    stock_warning: dict[str, Any] | None = None
    recipients: list[PreviewRecipientOut] = []


@router.get("/restocks/{event_id}/preview")
async def preview_restock(
    event_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
    template_id: uuid.UUID | None = Query(default=None),
) -> PreviewOut:
    """What confirming this event would send. Writes nothing.

    Without ``template_id`` the active template is used, or the default body when the
    owner has not saved one yet.
    """
    event = await _event_or_404(session, principal.business_id, event_id)
    if template_id is not None:
        template = await _template_or_404(session, principal.business_id, template_id)
    else:
        template = await restock.template_for_preview(
            session, business_id=principal.business_id
        )

    try:
        batch_preview = await restock.preview(
            session, business_id=principal.business_id, event=event, template=template
        )
    except restock.ReservationLanguageRejected as exc:
        raise BadRequest(str(exc)) from exc

    return PreviewOut(
        restock_event_id=str(event.id),
        waiting_count=batch_preview.waiting_count,
        eligible_count=batch_preview.eligible_count,
        skipped_count=batch_preview.skipped_count,
        stock_after=batch_preview.stock_after,
        stock_warning=batch_preview.stock_warning,
        recipients=[
            PreviewRecipientOut(
                customer_id=str(recipient.customer_id),
                customer_name=recipient.customer_name,
                channel=recipient.channel,
                contact_value=recipient.contact_value,
                message=recipient.body,
                eligible=recipient.eligible,
                skip_reason=recipient.skip_reason,
            )
            for recipient in batch_preview.recipients
        ],
    )


class ConfirmIn(BaseModel):
    """The owner's confirmation of a previewed batch (RP-07)."""

    template_id: uuid.UUID
    template_version: int | None = None
    channel_overrides: dict[str, str] | None = None


class SkippedOut(BaseModel):
    customer_id: str
    reason: str


class ConfirmOut(BaseModel):
    batch_id: str
    queued: int
    duplicates: int = 0
    skipped: list[SkippedOut] = []
    stock_warning: dict[str, Any] | None = None


@router.post("/restocks/{event_id}/notifications", status_code=201)
async def confirm_restock_batch(
    event_id: uuid.UUID,
    body: ConfirmIn,
    request: Request,
    principal: Principal = Depends(require_owner),
    session: AsyncSession = Depends(get_tenant_session),
) -> ConfirmOut:
    """Queue the batch. Owner only, and only with an Idempotency-Key."""
    key = getattr(request.state, "idempotency_key", None)
    if not key:
        raise BadRequest("This endpoint requires an Idempotency-Key header.")

    event = await _event_or_404(session, principal.business_id, event_id)
    template = await _template_or_404(session, principal.business_id, body.template_id)
    if body.template_version is not None and body.template_version != template.version:
        raise Conflict("The template changed after the preview. Preview again.")

    overrides = body.channel_overrides or {}
    unknown = set(overrides.values()) - CHANNELS
    if unknown:
        raise BadRequest(f"Unknown channel in channel_overrides: {', '.join(sorted(unknown))}.")

    try:
        batch_preview = await restock.preview(
            session,
            business_id=principal.business_id,
            event=event,
            template=template,
            channel_overrides=overrides,
        )
    except restock.ReservationLanguageRejected as exc:
        raise BadRequest(str(exc)) from exc

    confirmation = await restock.confirm_batch(
        session,
        business_id=principal.business_id,
        event=event,
        template=template,
        batch_preview=batch_preview,
        approved_by_user_id=principal.user_id,
        idempotency_key=restock.batch_key(business_id=principal.business_id, request_key=key),
    )
    await session.commit()

    return ConfirmOut(
        batch_id=str(confirmation.batch.id),
        queued=confirmation.queued,
        duplicates=confirmation.duplicates,
        skipped=[
            SkippedOut(customer_id=str(customer_id), reason=reason)
            for customer_id, reason in confirmation.skipped
        ],
        stock_warning=confirmation.stock_warning,
    )


class DeliveryItemOut(BaseModel):
    """One recipient's delivery state (RP-10)."""

    customer_id: str
    channel: str
    status: str
    skip_reason: str | None = None
    error_code: str | None = None
    attempt_count: int
    provider_message_id: str | None = None
    sent_at: str | None = None
    delivered_at: str | None = None


class DeliveryHistoryOut(BaseModel):
    items: list[DeliveryItemOut] = []


@router.get("/restocks/{event_id}/notifications")
async def restock_delivery_history(
    event_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> DeliveryHistoryOut:
    """Per recipient: pending, sent, delivered, failed or skipped with the reason."""
    await _event_or_404(session, principal.business_id, event_id)
    messages = await restock.delivery_history(
        session, business_id=principal.business_id, event_id=event_id
    )
    return DeliveryHistoryOut(
        items=[
            DeliveryItemOut(
                customer_id=str(message.customer_id),
                channel=message.channel,
                status=message.status,
                skip_reason=message.skip_reason,
                error_code=message.error_code,
                attempt_count=message.attempt_count,
                provider_message_id=message.provider_message_id,
                sent_at=message.sent_at.isoformat() if message.sent_at else None,
                delivered_at=message.delivered_at.isoformat() if message.delivered_at else None,
            )
            for message in messages
        ]
    )


def _default_contact(customer: Customer, channel: str) -> str | None:
    """The customer's own address for this channel, when the body carries none."""
    if channel == "email":
        return customer.email_normalised
    if channel == "sms":
        return customer.phone_e164
    return None


async def _event_or_404(
    session: AsyncSession, business_id: uuid.UUID, event_id: uuid.UUID
) -> RestockEvent:
    event = await session.scalar(
        select(RestockEvent).where(
            RestockEvent.business_id == business_id,
            RestockEvent.id == event_id,
        )
    )
    if event is None:
        raise NotFound("No such restock event.")
    return event


async def _template_or_404(
    session: AsyncSession, business_id: uuid.UUID, template_id: uuid.UUID
) -> MessageTemplate:
    template = await session.scalar(
        select(MessageTemplate).where(
            MessageTemplate.business_id == business_id,
            MessageTemplate.id == template_id,
            MessageTemplate.is_active.is_(True),
        )
    )
    if template is None:
        raise NotFound("No such message template.")
    return template
