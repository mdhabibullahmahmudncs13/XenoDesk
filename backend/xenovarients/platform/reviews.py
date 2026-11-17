"""Review request scheduling and delivery-confirmed order handling."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.customer import Customer, CustomerOrder, OrderStatus
from xenovarients.models.messaging import ContactPermission
from xenovarients.models.outbound import MessageTemplate, OutboundPurpose
from xenovarients.models.review import (
    ConsentState,
    ReviewCard,
    ReviewPermission,
    ReviewReply,
    ReviewRequest,
    ReviewRequestState,
    ReviewSettings,
)
from xenovarients.models.tenancy import Business
from xenovarients.platform.eligibility import check, load_rules
from xenovarients.platform.outbound import enqueue
from xenovarients.platform.scheduler import schedule

CONSENT_METHODS = {"reply_yes", "reply_anonymous", "reply_no", "manual"}
CARD_TEMPLATES = {"v1"}


async def create_review_card(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    request: ReviewRequest,
    template_version: str = "v1",
) -> ReviewCard:
    """Create a labelled card from an approved or anonymous verbatim reply."""
    if template_version not in CARD_TEMPLATES:
        raise ValueError("Unknown review card template.")
    permission = await session.scalar(
        select(ReviewPermission).where(
            ReviewPermission.business_id == business_id,
            ReviewPermission.review_request_id == request.id,
        )
    )
    if permission is None or permission.state not in {
        ConsentState.approved.value,
        ConsentState.anonymous.value,
    }:
        raise ValueError("Review consent is required before creating a card.")
    reply = await session.get(ReviewReply, permission.review_reply_id)
    if reply is None:
        raise ValueError("The review reply does not exist.")
    version = (
        await session.scalar(
            select(ReviewCard.version)
            .where(
                ReviewCard.business_id == business_id,
                ReviewCard.review_request_id == request.id,
            )
            .order_by(ReviewCard.version.desc())
            .limit(1)
        )
        or 0
    ) + 1
    card = ReviewCard(
        business_id=business_id,
        review_request_id=request.id,
        review_reply_id=reply.id,
        version=version,
        display_text=reply.content,
        display_label="Customer review",
        is_anonymous=permission.state == ConsentState.anonymous.value,
        template_version=template_version,
    )
    session.add(card)
    await session.flush()
    return card


async def set_review_permission(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    request: ReviewRequest,
    state: str,
    consent_method: str,
    review_reply_id: uuid.UUID | None = None,
) -> ReviewPermission:
    """Create or transition the consent record without deleting its history."""
    if state not in {item.value for item in ConsentState}:
        raise ValueError(f"Unknown consent state '{state}'.")
    if consent_method not in CONSENT_METHODS:
        raise ValueError(f"Unknown consent method '{consent_method}'.")

    permission = await session.scalar(
        select(ReviewPermission).where(
            ReviewPermission.business_id == business_id,
            ReviewPermission.review_request_id == request.id,
        )
    )
    if permission is None:
        permission = ReviewPermission(
            business_id=business_id,
            review_request_id=request.id,
            review_reply_id=review_reply_id,
            customer_id=request.customer_id,
            state=ConsentState.pending.value,
            consent_method=consent_method,
        )
        session.add(permission)
        await session.flush()

    current = permission.state
    allowed = {
        ConsentState.pending.value: {
            ConsentState.approved.value,
            ConsentState.anonymous.value,
            ConsentState.declined.value,
        },
        ConsentState.approved.value: {ConsentState.revoked.value},
        ConsentState.anonymous.value: {ConsentState.revoked.value},
        ConsentState.declined.value: set(),
        ConsentState.revoked.value: set(),
    }
    if state != current and state not in allowed[current]:
        raise ValueError(f"Cannot change consent from '{current}' to '{state}'.")

    now = datetime.now(UTC)
    permission.state = state
    permission.consent_method = consent_method
    permission.answered_at = now if state != ConsentState.pending.value else None
    permission.revoked_at = now if state == ConsentState.revoked.value else None
    if review_reply_id is not None:
        permission.review_reply_id = review_reply_id
    return permission


async def schedule_review_request(
    session: AsyncSession,
    *,
    business: Business,
    order: CustomerOrder,
) -> ReviewRequest | None:
    """Create the one review request for a delivered order and its scheduled job."""
    if order.delivered_at is None:
        return None

    existing = await session.scalar(
        select(ReviewRequest).where(
            ReviewRequest.business_id == business.id,
            ReviewRequest.order_id == order.id,
        )
    )
    if existing is not None:
        return existing

    settings = await session.scalar(
        select(ReviewSettings).where(ReviewSettings.business_id == business.id)
    )
    if settings is None:
        settings = ReviewSettings(
            business_id=business.id,
            channel_order=["email", "sms"],
        )
        session.add(settings)
        await session.flush()

    due_at = _due_at(
        delivery_confirmed_at=order.delivered_at,
        timezone=business.timezone,
        delay_days=settings.delay_days,
        send_window_start=settings.send_window_start,
        send_window_end=settings.send_window_end,
    )
    request = ReviewRequest(
        business_id=business.id,
        order_id=order.id,
        customer_id=order.customer_id,
        delivery_confirmed_at=order.delivered_at,
        due_at=due_at,
        state=ReviewRequestState.scheduled.value,
        reference_token=secrets.token_urlsafe(32),
    )
    session.add(request)
    await session.flush()
    await schedule(
        session,
        business_id=business.id,
        job_type="review_request",
        run_at=due_at,
        idempotency_key=f"review-request:{order.id}",
        payload={"business_id": str(business.id), "review_request_id": str(request.id)},
    )
    return request


async def process_review_request(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    request_id: uuid.UUID,
) -> ReviewRequest:
    """Re-check a due request and enqueue it, or record why it cannot be sent."""
    request = await session.scalar(
        select(ReviewRequest).where(
            ReviewRequest.business_id == business_id,
            ReviewRequest.id == request_id,
        )
    )
    if request is None:
        raise ValueError(f"Review request {request_id} does not exist.")
    if request.state != ReviewRequestState.scheduled.value:
        return request

    order = await session.scalar(
        select(CustomerOrder).where(
            CustomerOrder.business_id == business_id,
            CustomerOrder.id == request.order_id,
        )
    )
    if order is None:
        request.state = ReviewRequestState.cancelled.value
        request.state_reason = "order_missing"
        return request

    if (
        order.status in {
            OrderStatus.cancelled.value,
            OrderStatus.returned.value,
            OrderStatus.refunded.value,
        }
        or order.is_cancelled
        or order.is_returned
        or order.is_refunded
    ):
        request.state = ReviewRequestState.cancelled.value
        request.state_reason = "order_invalid"
        return request

    customer = await session.scalar(
        select(Customer).where(
            Customer.business_id == business_id,
            Customer.id == request.customer_id,
        )
    )
    settings = await session.scalar(
        select(ReviewSettings).where(ReviewSettings.business_id == business_id)
    )
    template = (
        await session.scalar(
            select(MessageTemplate).where(
                MessageTemplate.business_id == business_id,
                MessageTemplate.id == settings.template_id,
                MessageTemplate.is_active.is_(True),
            )
        )
        if settings is not None and settings.template_id is not None
        else None
    )
    if customer is None or template is None:
        request.state = ReviewRequestState.skipped.value
        request.state_reason = "no_template" if template is None else "customer_missing"
        return request

    rules = load_rules()
    channel_order = (settings.channel_order if settings else None) or ["email", "sms"]
    for channel in channel_order:
        permission = await session.scalar(
            select(ContactPermission).where(
                ContactPermission.business_id == business_id,
                ContactPermission.customer_id == customer.id,
                ContactPermission.channel == channel,
            )
        )
        contact_value = (
            permission.contact_value
            if permission is not None
            else customer.email_normalised
            if channel == "email"
            else customer.phone_e164
            if channel == "sms"
            else None
        )
        decision = check(
            rules,
            channel=channel,
            has_consent=(
                permission is not None
                and permission.eligible
                and (
                    not permission.purposes
                    or OutboundPurpose.review_request.value in permission.purposes
                )
            ),
            has_verified_identity=False,
            opted_out=permission is not None and permission.opted_out_at is not None,
            has_contact_value=bool(contact_value),
            channel_enabled=bool(rules.get("defaults", {}).get(channel, False)),
        )
        if not decision.eligible:
            continue
        key = hashlib.sha256(f"{business_id}:{request.id}:{channel}".encode()).hexdigest()
        await enqueue(
            session,
            business_id=business_id,
            purpose=OutboundPurpose.review_request.value,
            ref_id=request.id,
            customer_id=customer.id,
            channel=channel,
            to_address=contact_value,
            body=template.body,
            idempotency_key=key,
        )
        request.state = ReviewRequestState.sent.value
        request.sent_channel = channel
        request.sent_at = datetime.now(request.due_at.tzinfo)
        return request

    request.state = ReviewRequestState.skipped.value
    request.state_reason = "no_permission"
    return request


def _due_at(
    *,
    delivery_confirmed_at: datetime,
    timezone: str,
    delay_days: int,
    send_window_start: str,
    send_window_end: str,
) -> datetime:
    """Return the first valid send-window instant after the review delay."""
    local_zone = ZoneInfo(timezone)
    local_delivery = delivery_confirmed_at.astimezone(local_zone)
    candidate = local_delivery + timedelta(days=delay_days)
    start = _parse_time(send_window_start)
    end = _parse_time(send_window_end)

    if candidate.timetz().replace(tzinfo=None) < start:
        candidate = candidate.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
    elif candidate.timetz().replace(tzinfo=None) >= end:
        candidate = (candidate + timedelta(days=1)).replace(
            hour=start.hour, minute=start.minute, second=0, microsecond=0
        )
    return candidate.astimezone(delivery_confirmed_at.tzinfo)


def _parse_time(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour=hour, minute=minute)
