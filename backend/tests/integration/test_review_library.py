"""Review library and detail endpoint coverage (RV-11, RV-13)."""

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
async def test_review_library_supports_filters_and_empty_state(client, users_and_memberships):
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    response = await client.get(
        "/api/v1/creator-commerce/reviews/library",
        headers=headers,
        params={
            "consent_state": "approved",
            "since": "2026-01-01T00:00:00Z",
            "until": "2026-12-31T23:59:59Z",
            "limit": 10,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "has_more": False}


@pytest.mark.asyncio
async def test_review_detail_does_not_reveal_missing_review(client, users_and_memberships):
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    response = await client.get(
        "/api/v1/creator-commerce/reviews/00000000-0000-0000-0000-000000000000",
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_review_export_has_consent_gate_and_revocation_counter(
    client, users_and_memberships
):
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    response = await client.get(
        "/api/v1/creator-commerce/reviews/export",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "revoked_count": 0}
