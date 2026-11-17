"""In-app notifications.

**A notification is not an outbound message.** A restock event creates a
notification in the dashboard and *no* message to the customer. The customer is
contacted only through the review and restock flows, which have their own consent
checks. A notification that also sent a message would bypass those checks.

**No browser push** (CG-11). The bell badge count is the only surface, so the
service does exactly one thing: create, count, mark read.
"""

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.platform import Notification, NotificationKind


def _rowcount(result: Any) -> int:
    """The number of rows an UPDATE touched.

    The ORM ``Result`` does not expose ``rowcount``; the driver-level cursor does.
    """
    cursor = getattr(result, "rowcount", None)
    if cursor is not None:
        return int(cursor)
    raw = getattr(result, "_result", None)
    if raw is not None and getattr(raw, "rowcount", None) is not None:
        return int(raw.rowcount)
    return 0


async def notify(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    kind: NotificationKind | str,
    title: str,
    body: str | None = None,
    payload: dict[str, Any] | None = None,
    user_id: uuid.UUID | None = None,
) -> Notification:
    """Create a notification.

    ``user_id`` is optional: a notification with no user is visible to everyone in
    the business (a restock event, an ad sync). One addressed to a user is
    personal (a chat cost warning).
    """
    kind_value = kind.value if isinstance(kind, NotificationKind) else kind
    notification = Notification(
        business_id=business_id,
        user_id=user_id,
        kind=kind_value,
        title=title,
        body=body,
        payload=payload or {},
        is_read=False,
    )
    session.add(notification)
    await session.flush()
    return notification


async def unread_count(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> int:
    """The bell badge count.

    A business-wide notification counts for every member; a personal one counts
    only for its recipient. When a user is given, the count is the sum of the
    business-wide notifications and their own personal ones.
    """
    business_wide = select(func.count(Notification.id)).where(
        Notification.business_id == business_id,
        Notification.is_read.is_(False),
        Notification.user_id.is_(None),
    )
    if user_id is None:
        count = await session.scalar(business_wide)
        return int(count or 0)

    personal = select(func.count(Notification.id)).where(
        Notification.business_id == business_id,
        Notification.is_read.is_(False),
        Notification.user_id == user_id,
    )
    business_total = await session.scalar(business_wide)
    personal_total = await session.scalar(personal)
    return int(business_total or 0) + int(personal_total or 0)


async def mark_read(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    notification_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> bool:
    """Mark one notification read. Returns whether anything changed.

    A personal notification can only be marked read by its recipient; a
    business-wide one can be marked read by any member.
    """
    conditions = [
        Notification.business_id == business_id,
        Notification.id == notification_id,
    ]
    if user_id is not None:
        conditions.append((Notification.user_id == user_id) | (Notification.user_id.is_(None)))

    result = await session.execute(update(Notification).where(*conditions).values(is_read=True))
    await session.flush()
    return bool(_rowcount(result))


async def mark_all_read(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> int:
    """Mark every visible notification read. Returns how many changed."""
    conditions = [
        Notification.business_id == business_id,
        Notification.is_read.is_(False),
    ]
    if user_id is not None:
        conditions.append((Notification.user_id == user_id) | (Notification.user_id.is_(None)))

    result = await session.execute(update(Notification).where(*conditions).values(is_read=True))
    await session.flush()
    return _rowcount(result)


async def list_notifications(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    limit: int = 50,
    unread_only: bool = False,
) -> list[Notification]:
    """The notification list, newest first."""
    conditions = [Notification.business_id == business_id]
    if user_id is not None:
        conditions.append((Notification.user_id == user_id) | (Notification.user_id.is_(None)))
    if unread_only:
        conditions.append(Notification.is_read.is_(False))

    result = await session.execute(
        select(Notification)
        .where(*conditions)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
