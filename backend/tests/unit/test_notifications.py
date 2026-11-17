"""In-app notifications: the bell badge count and the read state."""

import pytest

from xenovarients.models.platform import NotificationKind
from xenovarients.platform.notifications import (
    list_notifications,
    mark_all_read,
    mark_read,
    notify,
    unread_count,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_a_notification_is_created_unread(session, businesses, bind):
    business_one, _ = businesses
    await bind(business_one.id)

    notification = await notify(
        session,
        business_id=business_one.id,
        kind=NotificationKind.restock,
        title="Variant X is back in stock",
        body="Three people are waiting.",
    )
    await session.commit()

    assert notification.is_read is False
    count = await unread_count(session, business_id=business_one.id)
    assert count == 1


@pytest.mark.asyncio
async def test_a_notification_creates_no_outbound_message(session, businesses, bind):
    """A restock event notifies the owner; it does not contact the customer.

    The customer is only contacted through the review and restock flows, which
    have their own consent checks. A notification that also sent a message would
    bypass those checks.
    """
    from sqlalchemy import func, select

    from xenovarients.models.outbound import OutboundMessage

    business_one, _ = businesses
    await bind(business_one.id)

    await notify(
        session,
        business_id=business_one.id,
        kind=NotificationKind.restock,
        title="Variant X is back in stock",
    )
    await session.commit()

    messages = await session.scalar(
        select(func.count(OutboundMessage.id)).where(OutboundMessage.business_id == business_one.id)
    )
    assert messages == 0


@pytest.mark.asyncio
async def test_marking_a_notification_read_clears_the_badge(session, businesses, bind):
    business_one, _ = businesses
    await bind(business_one.id)
    notification = await notify(
        session,
        business_id=business_one.id,
        kind=NotificationKind.restock,
        title="Something happened",
    )
    await session.commit()

    assert (
        await mark_read(session, business_id=business_one.id, notification_id=notification.id)
        is True
    )
    await session.commit()

    count = await unread_count(session, business_id=business_one.id)
    assert count == 0


@pytest.mark.asyncio
async def test_marking_all_read_clears_the_badge(session, businesses, bind):
    business_one, _ = businesses
    await bind(business_one.id)
    for _ in range(3):
        await notify(
            session,
            business_id=business_one.id,
            kind=NotificationKind.restock,
            title="Something happened",
        )
    await session.commit()

    changed = await mark_all_read(session, business_id=business_one.id)
    await session.commit()

    assert changed == 3
    assert await unread_count(session, business_id=business_one.id) == 0


@pytest.mark.asyncio
async def test_a_personal_notification_counts_only_for_its_recipient(
    session, businesses, users_and_memberships, bind
):
    owner, _staff, _owner_membership, _staff_membership = users_and_memberships
    business_one, _ = businesses
    await bind(business_one.id)

    await notify(
        session,
        business_id=business_one.id,
        kind=NotificationKind.chat_cost,
        title="Chat cost warning",
        user_id=owner.id,
    )
    await session.commit()

    assert await unread_count(session, business_id=business_one.id, user_id=owner.id) == 1
    # Another member sees only the business-wide notifications, not this one.
    assert await unread_count(session, business_id=business_one.id, user_id=_staff.id) == 0


@pytest.mark.asyncio
async def test_notifications_do_not_leak_across_businesses(session, businesses, bind):
    business_one, business_two = businesses
    await bind(business_one.id)
    await notify(
        session,
        business_id=business_one.id,
        kind=NotificationKind.restock,
        title="Business one news",
    )
    await session.commit()

    await bind(business_two.id)
    assert await unread_count(session, business_id=business_two.id) == 0
    rows = await list_notifications(session, business_id=business_two.id)
    assert rows == []


@pytest.mark.asyncio
async def test_the_list_is_newest_first(session, businesses, bind):
    business_one, _ = businesses
    await bind(business_one.id)
    for index in range(3):
        await notify(
            session,
            business_id=business_one.id,
            kind=NotificationKind.restock,
            title=f"Event {index}",
        )
        await session.commit()

    rows = await list_notifications(session, business_id=business_one.id)
    assert [row.title for row in rows] == ["Event 2", "Event 1", "Event 0"]
