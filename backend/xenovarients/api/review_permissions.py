"""Review publication consent endpoints."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.api.deps import Principal, get_tenant_session, require_admin
from xenovarients.api.errors import BadRequest, NotFound
from xenovarients.models.review import ReviewPermission, ReviewRequest
from xenovarients.platform.audit import AuditAction, record
from xenovarients.platform.reviews import create_review_card, set_review_permission

router = APIRouter(
    prefix="/api/v1/creator-commerce/reviews",
    tags=["creator-commerce"],
)


class PermissionIn(BaseModel):
    state: str
    consent_method: str = "manual"
    review_reply_id: uuid.UUID | None = None


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    review_request_id: uuid.UUID
    state: str
    consent_method: str
    answered_at: datetime | None
    revoked_at: datetime | None


class CardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    review_request_id: uuid.UUID
    display_text: str
    display_label: str
    is_anonymous: bool
    template_version: str
    state: str


@router.post("/{review_id}/permission")
async def update_permission(
    review_id: uuid.UUID,
    body: PermissionIn,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
) -> PermissionOut:
    request = await session.scalar(
        select(ReviewRequest).where(
            ReviewRequest.business_id == principal.business_id,
            ReviewRequest.id == review_id,
        )
    )
    if request is None:
        raise NotFound("No such review request.")

    try:
        permission = await set_review_permission(
            session,
            business_id=principal.business_id,
            request=request,
            state=body.state,
            consent_method=body.consent_method,
            review_reply_id=body.review_reply_id,
        )
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc

    await record(
        session,
        business_id=principal.business_id,
        action=(
            AuditAction.consent_revoked
            if body.state == "revoked"
            else AuditAction.consent_changed
        ),
        target_type="review_permission",
        target_id=str(permission.id),
        actor_user_id=principal.user_id,
        after={"state": permission.state, "method": permission.consent_method},
    )
    await session.commit()
    return PermissionOut.model_validate(permission, from_attributes=True)


@router.get("/{review_id}/permission")
async def get_permission(
    review_id: uuid.UUID,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
) -> PermissionOut:
    permission = await session.scalar(
        select(ReviewPermission)
        .join(ReviewRequest, ReviewRequest.id == ReviewPermission.review_request_id)
        .where(
            ReviewPermission.business_id == principal.business_id,
            ReviewRequest.id == review_id,
        )
    )
    if permission is None:
        raise NotFound("No review permission exists.")
    return PermissionOut.model_validate(permission, from_attributes=True)


@router.post("/{review_id}/card")
async def create_card(
    review_id: uuid.UUID,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
) -> CardOut:
    request = await session.scalar(
        select(ReviewRequest).where(
            ReviewRequest.business_id == principal.business_id,
            ReviewRequest.id == review_id,
        )
    )
    if request is None:
        raise NotFound("No such review request.")
    try:
        card = await create_review_card(
            session, business_id=principal.business_id, request=request
        )
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc
    await session.commit()
    return CardOut.model_validate(card, from_attributes=True)
