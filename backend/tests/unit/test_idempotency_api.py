"""The Idempotency-Key middleware: store a response, replay it on a repeat.

The properties worth pinning: a repeat replays rather than acting again, a repeat
with a *different* body is a conflict rather than a replay, and a request with no
key is untouched.
"""

import uuid

import pytest
from httpx import AsyncClient

from xenovarients.platform.idempotency import fingerprint, parse_body

pytestmark = pytest.mark.integration


async def _login(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "correct-horse-battery"},
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def test_the_fingerprint_covers_the_method_and_path() -> None:
    a = fingerprint("POST", "/api/v1/thing", b"{}")
    b = fingerprint("POST", "/api/v1/other", b"{}")
    c = fingerprint("PUT", "/api/v1/thing", b"{}")
    assert a != b
    assert a != c


def test_the_fingerprint_covers_the_body() -> None:
    assert fingerprint("POST", "/x", b'{"a":1}') != fingerprint("POST", "/x", b'{"a":2}')


def test_a_non_json_body_parses_to_an_empty_object() -> None:
    assert parse_body(b"not json") == {}
    assert parse_body(b"") == {}
    assert parse_body(b'{"a":1}') == {"a": 1}


@pytest.mark.asyncio
async def test_a_request_without_a_key_is_untouched(client: AsyncClient, users_and_memberships):
    """No key means no stored response and no replay header."""
    token = await _login(client)
    response = await client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 204
    assert "Idempotent-Replay" not in response.headers


@pytest.mark.asyncio
async def test_a_repeated_key_replays_the_stored_response(
    client: AsyncClient, users_and_memberships
):
    """The second request returns the first response without acting again."""
    token = await _login(client)
    key = f"key-{uuid.uuid4().hex[:12]}"
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": key}

    first = await client.post("/api/v1/auth/logout", headers=headers)
    assert first.status_code == 204, first.text

    second = await client.post("/api/v1/auth/logout", headers=headers)
    assert second.status_code == 204, second.text
    assert second.headers.get("Idempotent-Replay") == "true"


@pytest.mark.asyncio
async def test_a_repeated_key_with_a_different_body_is_a_conflict(
    client: AsyncClient, users_and_memberships
):
    """The same key with a different body is a mistake, not a retry.

    Replaying the first response would perform the first request's action for the
    second request's intent.
    """
    token = await _login(client)
    key = f"key-{uuid.uuid4().hex[:12]}"
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": key}

    first = await client.post("/api/v1/auth/logout", headers=headers, json={"reason": "one"})
    assert first.status_code == 204, first.text

    second = await client.post("/api/v1/auth/logout", headers=headers, json={"reason": "two"})
    assert second.status_code == 409, second.text
    assert second.json()["code"] == "idempotency_conflict"


@pytest.mark.asyncio
async def test_a_malformed_key_is_rejected(client: AsyncClient, users_and_memberships):
    """A client that sends a malformed key believes it is protected.

    Silently ignoring the key would leave it unprotected while it believes
    otherwise, so the request is rejected outright.
    """
    token = await _login(client)
    response = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "x" * 200},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


@pytest.mark.asyncio
async def test_an_unauthenticated_request_with_a_key_is_not_stored(
    client: AsyncClient, users_and_memberships
):
    """There is no tenant to attribute the record to, so nothing is stored."""
    response = await client.post(
        "/api/v1/auth/logout", headers={"Idempotency-Key": f"key-{uuid.uuid4().hex[:12]}"}
    )
    assert response.status_code == 401
    assert "Idempotent-Replay" not in response.headers
