"""Inbound webhook security: signatures, replay, and tenant routing.

A webhook is the one endpoint where a request arrives without an auth header, so the
signature check *is* the authentication. These tests pin down that it cannot be
bypassed, and that a replayed webhook produces no second event.
"""

import hashlib
import hmac
import json
import time
import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration

SECRET = "webhook-secret-for-tests"


def _sign(body: bytes, secret: str = SECRET, timestamp: int | None = None) -> dict[str, str]:
    ts = timestamp if timestamp is not None else int(time.time())
    signature = hmac.new(
        secret.encode(),
        f"{ts}.{body.decode()}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return {"X-Signature": f"sha256={signature}", "X-Timestamp": str(ts)}


def _payload(event_id: str = "evt-1", content: str = "hello") -> bytes:
    return json.dumps(
        {
            "event_id": event_id,
            "channel_user_id": "+8801712345678",
            "content": content,
            "received_at": "2026-11-16T09:12:00+00:00",
        }
    ).encode()


@pytest.mark.asyncio
async def test_webhook_rejects_a_bad_signature(client: AsyncClient, businesses):
    business_one, _ = businesses
    body = _payload()
    response = await client.post(
        f"/webhooks/messaging/generic/{business_one.id}",
        content=body,
        headers={"X-Signature": "sha256=deadbeef", "X-Timestamp": str(int(time.time()))},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_webhook_rejects_a_missing_signature(client: AsyncClient, businesses):
    business_one, _ = businesses
    response = await client.post(
        f"/webhooks/messaging/generic/{business_one.id}",
        content=_payload(),
        headers={"X-Timestamp": str(int(time.time()))},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_webhook_rejects_a_stale_timestamp(client: AsyncClient, businesses):
    """A captured signature must not be replayable outside the window."""
    business_one, _ = businesses
    body = _payload()
    stale = int(time.time()) - 3600
    response = await client.post(
        f"/webhooks/messaging/generic/{business_one.id}",
        content=body,
        headers=_sign(body, timestamp=stale),
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_webhook_accepts_a_valid_signature(client: AsyncClient, businesses, session):
    business_one, _ = businesses
    body = _payload(event_id=f"evt-{uuid.uuid4().hex[:8]}")
    response = await client.post(
        f"/webhooks/messaging/generic/{business_one.id}",
        content=body,
        headers=_sign(body),
    )
    assert response.status_code == 202, response.text
    body_json = response.json()
    assert body_json["received"] is True
    assert body_json["duplicate"] is False


@pytest.mark.asyncio
async def test_replayed_webhook_produces_no_second_event(client: AsyncClient, businesses, session):
    """The provider_event_id unique constraint is what makes a retry safe."""
    business_one, _ = businesses
    body = _payload(event_id=f"evt-{uuid.uuid4().hex[:8]}")
    headers = _sign(body)

    first = await client.post(
        f"/webhooks/messaging/generic/{business_one.id}", content=body, headers=headers
    )
    assert first.status_code == 202
    assert first.json()["duplicate"] is False

    second = await client.post(
        f"/webhooks/messaging/generic/{business_one.id}", content=body, headers=headers
    )
    assert second.status_code == 202
    assert second.json()["duplicate"] is True


@pytest.mark.asyncio
async def test_webhook_for_an_unknown_business_is_not_found(client: AsyncClient):
    response = await client.post(
        f"/webhooks/messaging/generic/{uuid.uuid4()}",
        content=_payload(),
        headers=_sign(_payload()),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_webhook_challenge_is_echoed(client: AsyncClient, businesses):
    """The provider handshake: echo the challenge so it can verify the URL."""
    business_one, _ = businesses
    response = await client.get(
        f"/webhooks/messaging/generic/{business_one.id}?hub.challenge=abc123"
    )
    assert response.status_code == 200
    assert response.text == "abc123"


@pytest.mark.asyncio
async def test_unknown_channel_is_not_found(client: AsyncClient, businesses):
    business_one, _ = businesses
    response = await client.post(
        f"/webhooks/messaging/telegram/{business_one.id}",
        content=_payload(),
        headers=_sign(_payload()),
    )
    assert response.status_code == 404
