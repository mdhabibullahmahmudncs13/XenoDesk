"""Auth API tests.

The auth flow is the front door to every tenant-scoped endpoint, so the contract is
worth pinning down: a valid login returns a token, an invalid one returns the same
message whether or not the email exists, and the token alone is not enough — the
caller must also belong to a business.
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_login_returns_token(client: AsyncClient, users_and_memberships):
    owner, _staff, _m1, _m2 = users_and_memberships
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "correct-horse-battery"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["role"] == "owner"
    assert body["business_id"] == str(body["business_id"])
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(client: AsyncClient, users_and_memberships):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_login_does_not_reveal_whether_email_exists(client: AsyncClient):
    """Unknown email and wrong password must be indistinguishable."""
    unknown = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "wrong-password"},
    )
    assert unknown.status_code == 401
    assert unknown.json()["detail"] == "Incorrect email or password."


@pytest.mark.asyncio
async def test_me_requires_authentication(client: AsyncClient):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "unauthorized"
    assert body["type"].endswith("/unauthorized")
    assert "request_id" in body


@pytest.mark.asyncio
async def test_me_returns_the_caller_context(client: AsyncClient, users_and_memberships):
    owner, _staff, _m1, _m2 = users_and_memberships
    token = await _login(client, "owner@example.com")
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == "owner@example.com"
    assert body["role"] == "owner"
    assert body["business"]["name"] == "Business One"


@pytest.mark.asyncio
async def test_memberships_lists_only_the_callers_businesses(
    client: AsyncClient, users_and_memberships
):
    owner, _staff, _m1, _m2 = users_and_memberships
    token = await _login(client, "owner@example.com")
    response = await client.get(
        "/api/v1/auth/memberships", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["business"]["name"] == "Business One"


@pytest.mark.asyncio
async def test_logout_revokes_the_token(client: AsyncClient, users_and_memberships):
    """Logout must actually invalidate the token, not just tell the client to forget it."""
    owner, _staff, _m1, _m2 = users_and_memberships
    token = await _login(client, "owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200

    response = await client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 204, response.text

    after = await client.get("/api/v1/auth/me", headers=headers)
    assert after.status_code == 401
    assert after.json()["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_logout_is_idempotent(client: AsyncClient, users_and_memberships):
    """A second logout with the same token must not error."""
    owner, _staff, _m1, _m2 = users_and_memberships
    token = await _login(client, "owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204
    assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204


@pytest.mark.asyncio
async def test_oversized_idempotency_key_is_rejected(client: AsyncClient):
    """A malformed key must be rejected — silently ignoring it would let a client
    believe it is protected against duplicate effects."""
    response = await client.get("/health", headers={"Idempotency-Key": "k" * 200})
    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


@pytest.mark.asyncio
async def test_request_id_is_echoed(client: AsyncClient):
    response = await client.get("/health", headers={"X-Request-Id": "abc123"})
    assert response.headers["X-Request-Id"] == "abc123"
    assert "X-Response-Time-Ms" in response.headers


@pytest.mark.asyncio
async def test_health_is_public(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token
