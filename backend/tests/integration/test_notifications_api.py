"""The notifications API: the bell badge count and the read state.

These endpoints are the only surface CG-11 allows — a dashboard notification, not a
browser push. The contract worth pinning: the badge count is the caller's, and a
notification from one business never appears in another's.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.platform import NotificationKind
from xenovarients.platform.notifications import notify

pytestmark = pytest.mark.integration


async def _login(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "correct-horse-battery"},
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


@pytest.mark.asyncio
async def test_the_badge_count_requires_authentication(client: AsyncClient):
    response = await client.get("/api/v1/notifications/unread-count")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_the_badge_count_starts_at_zero(client: AsyncClient, users_and_memberships):
    token = await _login(client)
    response = await client.get(
        "/api/v1/notifications/unread-count", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"count": 0}


@pytest.mark.asyncio
async def test_a_notification_raises_the_badge_count(
    client: AsyncClient, session: AsyncSession, users_and_memberships, bind
):
    owner, _staff, _m1, _m2 = users_and_memberships
    business = _m1.business_id
    await bind(business)
    await notify(
        session,
        business_id=business,
        kind=NotificationKind.restock,
        title="Variant X is back in stock",
    )
    await session.commit()

    token = await _login(client)
    response = await client.get(
        "/api/v1/notifications/unread-count", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["count"] == 1


@pytest.mark.asyncio
async def test_the_list_shows_the_notification(
    client: AsyncClient, session: AsyncSession, users_and_memberships, bind
):
    owner, _staff, _m1, _m2 = users_and_memberships
    business = _m1.business_id
    await bind(business)
    await notify(
        session,
        business_id=business,
        kind=NotificationKind.restock,
        title="Variant X is back in stock",
        body="Three people are waiting.",
    )
    await session.commit()

    token = await _login(client)
    response = await client.get(
        "/api/v1/notifications", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["title"] == "Variant X is back in stock"
    assert body["items"][0]["is_read"] is False


@pytest.mark.asyncio
async def test_marking_read_clears_the_badge(
    client: AsyncClient, session: AsyncSession, users_and_memberships, bind
):
    owner, _staff, _m1, _m2 = users_and_memberships
    business = _m1.business_id
    await bind(business)
    notification = await notify(
        session,
        business_id=business,
        kind=NotificationKind.restock,
        title="Variant X is back in stock",
    )
    await session.commit()

    token = await _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    marked = await client.post(f"/api/v1/notifications/{notification.id}/read", headers=headers)
    assert marked.status_code == 200, marked.text
    assert marked.json()["marked_read"] is True

    count = await client.get("/api/v1/notifications/unread-count", headers=headers)
    assert count.json()["count"] == 0


@pytest.mark.asyncio
async def test_a_notification_from_another_business_is_not_visible(
    client: AsyncClient, session: AsyncSession, users_and_memberships, bind
):
    """The staff member of business two must not see business one's notifications."""
    _owner, _staff, m1, _m2 = users_and_memberships
    await bind(m1.business_id)
    await notify(
        session,
        business_id=m1.business_id,
        kind=NotificationKind.restock,
        title="Business one news",
    )
    await session.commit()

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "staff@example.com", "password": "correct-horse-battery"},
    )
    token = response.json()["access_token"]

    listed = await client.get("/api/v1/notifications", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == []

    count = await client.get(
        "/api/v1/notifications/unread-count", headers={"Authorization": f"Bearer {token}"}
    )
    assert count.json()["count"] == 0


@pytest.mark.asyncio
async def test_marking_an_unknown_notification_read_is_not_an_error(
    client: AsyncClient, users_and_memberships
):
    """A stale bell badge must not produce a 500."""
    token = await _login(client)
    response = await client.post(
        f"/api/v1/notifications/{uuid.uuid4()}/read",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["marked_read"] is False
