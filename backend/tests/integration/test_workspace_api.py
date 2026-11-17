"""Agent Workspace endpoint coverage (AW-03, AW-08, AW-09)."""

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
async def test_chat_session_rejects_images_with_clear_message(client, users_and_memberships):
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    response = await client.post("/api/v1/agent-workspace/sessions", headers=headers)
    assert response.status_code == 200, response.text
    session_id = response.json()["id"]

    response = await client.post(
        f"/api/v1/agent-workspace/sessions/{session_id}/messages",
        headers=headers,
        json={"content": "What is this?", "image_attached": True},
    )
    assert response.status_code == 400
    assert "Image analysis is not supported" in response.json()["detail"]
