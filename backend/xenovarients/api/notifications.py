"""The notification endpoints: the bell badge count and the list."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.api.deps import Principal, get_principal, get_tenant_session
from xenovarients.api.pagination import Page
from xenovarients.models.platform import Notification
from xenovarients.platform.notifications import (
    list_notifications,
    mark_all_read,
    mark_read,
    unread_count,
)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    """A notification as the client sees it."""

    id: str
    kind: str
    title: str
    body: str | None = None
    payload: dict[str, Any] = {}
    is_read: bool = False
    created_at: str


def _serialize(notification: Notification) -> NotificationOut:
    return NotificationOut(
        id=str(notification.id),
        kind=notification.kind,
        title=notification.title,
        body=notification.body,
        payload=notification.payload or {},
        is_read=notification.is_read,
        created_at=notification.created_at.isoformat(),
    )


@router.get("")
async def list_notifications_endpoint(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
    limit: int = Query(default=50, ge=1, le=200),
    unread_only: bool = Query(default=False),
) -> Page[NotificationOut]:
    """The notification list, newest first."""
    rows = await list_notifications(
        session,
        business_id=principal.business_id,
        user_id=principal.user_id,
        limit=limit,
        unread_only=unread_only,
    )
    return Page[NotificationOut](
        items=[_serialize(row) for row in rows],
        has_more=False,
    )


@router.get("/unread-count")
async def unread_count_endpoint(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, int]:
    """The bell badge count."""
    count = await unread_count(
        session, business_id=principal.business_id, user_id=principal.user_id
    )
    return {"count": count}


@router.post("/{notification_id}/read")
async def mark_read_endpoint(
    notification_id: str,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, bool]:
    """Mark one notification read."""
    changed = await mark_read(
        session,
        business_id=principal.business_id,
        notification_id=uuid.UUID(notification_id),
        user_id=principal.user_id,
    )
    await session.commit()
    return {"marked_read": changed}


@router.post("/read-all")
async def mark_all_read_endpoint(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, int]:
    """Mark every visible notification read."""
    count = await mark_all_read(
        session, business_id=principal.business_id, user_id=principal.user_id
    )
    await session.commit()
    return {"marked_read": count}
