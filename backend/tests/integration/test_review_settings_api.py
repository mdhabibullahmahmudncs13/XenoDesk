"""Review settings API acceptance coverage (RV-03, RV-05, RV-06)."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def _token(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "correct-horse-battery"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_review_settings_use_od08_defaults_and_can_be_updated(client, users_and_memberships):
    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get(
        "/api/v1/creator-commerce/reviews/settings",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "id": response.json()["id"],
        "delay_days": 3,
        "send_window_start": "09:00",
        "send_window_end": "20:00",
        "reply_window_days": 14,
        "channel_order": ["email", "sms"],
        "template_id": None,
    }

    response = await client.patch(
        "/api/v1/creator-commerce/reviews/settings",
        headers=headers,
        json={
            "delay_days": 5,
            "send_window_start": "10:00",
            "channel_order": ["sms", "email"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["delay_days"] == 5
    assert response.json()["send_window_start"] == "10:00"
    assert response.json()["channel_order"] == ["sms", "email"]


@pytest.mark.asyncio
async def test_review_settings_reject_invalid_window_and_channels(client, users_and_memberships):
    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.patch(
        "/api/v1/creator-commerce/reviews/settings",
        headers=headers,
        json={"send_window_start": "20:00", "send_window_end": "09:00"},
    )
    assert response.status_code == 400

    response = await client.patch(
        "/api/v1/creator-commerce/reviews/settings",
        headers=headers,
        json={"channel_order": ["email", "email"]},
    )
    assert response.status_code == 400
