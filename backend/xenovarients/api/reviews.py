"""Creator Commerce review settings."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.api.deps import Principal, get_tenant_session, require_admin
from xenovarients.api.errors import BadRequest, NotFound
from xenovarients.models.customer import Customer
from xenovarients.models.outbound import MessageTemplate
from xenovarients.models.review import (
    ReviewCard,
    ReviewPermission,
    ReviewReply,
    ReviewRequest,
    ReviewSettings,
)
from xenovarients.platform.audit import AuditAction, record
from xenovarients.platform.reviews import review_library

router = APIRouter(
    prefix="/api/v1/creator-commerce/reviews",
    tags=["creator-commerce"],
)

DEFAULT_CHANNEL_ORDER = ["email", "sms"]
CHANNELS = {"email", "sms", "messenger", "whatsapp"}


def _validate_time(value: str) -> str:
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise ValueError("time must use HH:MM format") from exc
    return value


class ReviewSettingsOut(BaseModel):
    id: uuid.UUID
    delay_days: int
    send_window_start: str
    send_window_end: str
    reply_window_days: int
    channel_order: list[str]
    template_id: uuid.UUID | None


class ReviewSettingsPatch(BaseModel):
    delay_days: int | None = Field(default=None, ge=0, le=365)
    send_window_start: str | None = None
    send_window_end: str | None = None
    reply_window_days: int | None = Field(default=None, ge=1, le=365)
    channel_order: list[str] | None = None
    template_id: uuid.UUID | None = None


class ReviewLibraryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    review_request_id: uuid.UUID
    reply_id: uuid.UUID
    customer_id: uuid.UUID
    order_id: uuid.UUID | None
    content: str
    channel: str
    received_at: datetime
    consent_state: str | None


class ReviewLibraryOut(BaseModel):
    items: list[ReviewLibraryItem]
    has_more: bool


class ReviewDetailOut(ReviewLibraryItem):
    cards: list[dict[str, object]]


class ReviewExportItem(BaseModel):
    review_request_id: uuid.UUID
    reply_id: uuid.UUID
    content: str
    customer_id: uuid.UUID | None
    customer_name: str | None
    consent_state: str


class ReviewExportOut(BaseModel):
    items: list[ReviewExportItem]
    revoked_count: int


def _output(settings: ReviewSettings) -> ReviewSettingsOut:
    return ReviewSettingsOut(
        id=settings.id,
        delay_days=settings.delay_days,
        send_window_start=settings.send_window_start,
        send_window_end=settings.send_window_end,
        reply_window_days=settings.reply_window_days,
        channel_order=settings.channel_order or DEFAULT_CHANNEL_ORDER,
        template_id=settings.template_id,
    )


async def _get_or_create(
    session: AsyncSession, business_id: uuid.UUID
) -> ReviewSettings:
    settings = await session.scalar(
        select(ReviewSettings).where(ReviewSettings.business_id == business_id)
    )
    if settings is None:
        settings = ReviewSettings(
            business_id=business_id,
            channel_order=DEFAULT_CHANNEL_ORDER.copy(),
        )
        session.add(settings)
        await session.flush()
    return settings


@router.get("/settings")
async def get_review_settings(
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
) -> ReviewSettingsOut:
    settings = await _get_or_create(session, principal.business_id)
    await session.commit()
    return _output(settings)


@router.patch("/settings")
async def patch_review_settings(
    body: ReviewSettingsPatch,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
) -> ReviewSettingsOut:
    settings = await _get_or_create(session, principal.business_id)
    before = _output(settings).model_dump(mode="json")

    changes = body.model_dump(exclude_unset=True)
    for field in ("send_window_start", "send_window_end"):
        if field in changes:
            try:
                _validate_time(changes[field])
            except ValueError as exc:
                raise BadRequest(str(exc)) from exc
    if "channel_order" in changes:
        channels = changes["channel_order"]
        if not channels or len(channels) != len(set(channels)):
            raise BadRequest("channel_order must contain unique channels.")
        unknown = set(channels) - CHANNELS
        if unknown:
            raise BadRequest(f"Unknown channel(s): {', '.join(sorted(unknown))}.")

    if "template_id" in changes and changes["template_id"] is not None:
        template = await session.scalar(
            select(MessageTemplate).where(
                MessageTemplate.business_id == principal.business_id,
                MessageTemplate.id == changes["template_id"],
            )
        )
        if template is None:
            raise BadRequest("The selected review template does not belong to this business.")

    for field, value in changes.items():
        setattr(settings, field, value)

    if settings.send_window_start >= settings.send_window_end:
        raise BadRequest("send_window_start must be earlier than send_window_end.")

    after = _output(settings).model_dump(mode="json")
    await record(
        session,
        business_id=principal.business_id,
        action=AuditAction.settings_changed,
        target_type="review_settings",
        target_id=str(settings.id),
        actor_user_id=principal.user_id,
        before=before,
        after=after,
    )
    await session.commit()
    return _output(settings)


@router.get("/library")
async def list_review_library(
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
    product_id: uuid.UUID | None = Query(default=None),
    customer_id: uuid.UUID | None = Query(default=None),
    consent_state: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> ReviewLibraryOut:
    """Browse captured reviews with tenant-safe product, date, and consent filters."""
    rows, has_more = await review_library(
        session,
        business_id=principal.business_id,
        product_id=product_id,
        customer_id=customer_id,
        consent_state=consent_state,
        since=since,
        until=until,
        limit=limit,
    )
    return ReviewLibraryOut(
        items=[
            ReviewLibraryItem(
                review_request_id=row.review_request_id,
                reply_id=row.reply_id,
                customer_id=row.customer_id,
                order_id=row.order_id,
                content=row.content,
                channel=row.channel,
                received_at=row.received_at,
                consent_state=row.consent_state,
            )
            for row in rows
        ],
        has_more=has_more,
    )


@router.get("/export")
async def export_reviews(
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
) -> ReviewExportOut:
    """Export only reviews with current publication consent."""
    base = (
        select(ReviewReply, ReviewPermission, Customer.name)
        .join(ReviewRequest, ReviewRequest.id == ReviewReply.review_request_id)
        .join(ReviewPermission, ReviewPermission.review_request_id == ReviewRequest.id)
        .join(Customer, Customer.id == ReviewReply.customer_id)
        .where(
            ReviewReply.business_id == principal.business_id,
            ReviewRequest.business_id == principal.business_id,
        )
    )
    rows = (await session.execute(base)).all()
    revoked_count = sum(
        permission.state == "revoked" for _, permission, _ in rows
    )
    items = [
        ReviewExportItem(
            review_request_id=reply.review_request_id,
            reply_id=reply.id,
            content=reply.content,
            customer_id=(
                None if permission.state == "anonymous" else reply.customer_id
            ),
            customer_name=None if permission.state == "anonymous" else customer_name,
            consent_state=permission.state,
        )
        for reply, permission, customer_name in rows
        if permission.state in {"approved", "anonymous"}
    ]
    await record(
        session,
        business_id=principal.business_id,
        action=AuditAction.export_created,
        target_type="review_export",
        target_id=str(uuid.uuid4()),
        actor_user_id=principal.user_id,
        after={"item_count": len(items), "revoked_count": revoked_count},
    )
    await session.commit()
    return ReviewExportOut(items=items, revoked_count=revoked_count)


@router.get("/{review_id}")
async def get_review_detail(
    review_id: uuid.UUID,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
) -> ReviewDetailOut:
    """Return one review and its generated cards."""
    row = await session.execute(
        select(ReviewReply, ReviewPermission.state)
        .join(ReviewRequest, ReviewRequest.id == ReviewReply.review_request_id)
        .outerjoin(
            ReviewPermission,
            ReviewPermission.review_request_id == ReviewRequest.id,
        )
        .where(
            ReviewReply.business_id == principal.business_id,
            ReviewRequest.business_id == principal.business_id,
            ReviewRequest.id == review_id,
        )
    )
    result = row.one_or_none()
    if result is None:
        raise NotFound("No such review.")
    reply, state = result
    cards = (
        await session.execute(
            select(ReviewCard)
            .where(
                ReviewCard.business_id == principal.business_id,
                ReviewCard.review_request_id == review_id,
            )
            .order_by(ReviewCard.version.desc())
        )
    ).scalars()
    return ReviewDetailOut(
        review_request_id=reply.review_request_id,
        reply_id=reply.id,
        customer_id=reply.customer_id,
        order_id=reply.order_id,
        content=reply.content,
        channel=reply.channel,
        received_at=reply.received_at,
        consent_state=state,
        cards=[
            {
                "id": card.id,
                "version": card.version,
                "display_text": card.display_text,
                "display_label": card.display_label,
                "is_anonymous": card.is_anonymous,
                "template_version": card.template_version,
                "state": card.state,
            }
            for card in cards
        ],
    )
