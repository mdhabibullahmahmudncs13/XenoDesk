"""The realtime path, end to end, against a real Redis.

The SSE endpoint's promise is a published event reaches a connected client
quickly. That promise is only meaningful against a real Redis — the publish, the
subscription and the wire format all have to line up — so this test uses the live
Redis rather than a stand-in.

The subscription is opened directly rather than through the HTTP client: the
ASGI transport buffers a response body, and an SSE stream never ends, so driving
it over httpx would hang. The endpoint's own auth and routing are covered
separately, and the wire format is exercised here.
"""

import asyncio
import json
import time
import uuid

import pytest
from httpx import AsyncClient

from xenovarients.platform.realtime import (
    Event,
    channel_for,
    format_sse_raw,
    get_redis,
    publish,
    subscribe,
)

pytestmark = pytest.mark.integration

# The budget the plan gives the stream: a publish reaches a connected client
# within five seconds at p95.
LATENCY_BUDGET_SECONDS = 5.0


async def _login(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "correct-horse-battery"},
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


@pytest.mark.asyncio
async def test_a_published_event_reaches_a_connected_subscriber(businesses):
    """The whole path: publish to Redis, and the subscriber receives it."""
    business_one, _ = businesses
    redis = get_redis()
    pubsub = await subscribe(redis, business_one.id)

    try:
        # Let the subscription establish before publishing.
        await asyncio.sleep(0.2)

        started = time.monotonic()
        event = Event(type="bubble.created", data={"id": "b-1"})
        assert await publish(redis, business_one.id, event)

        message = None
        while message is None:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=2.0)
        elapsed = time.monotonic() - started
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()
        await redis.aclose()

    assert elapsed < LATENCY_BUDGET_SECONDS
    frame = format_sse_raw(message["data"])
    payload = json.loads(frame.split("data: ", 1)[1])
    assert payload["type"] == "bubble.created"
    assert payload["data"]["id"] == "b-1"


@pytest.mark.asyncio
async def test_a_subscriber_does_not_receive_another_businesss_events(businesses):
    """The channel name carries the business id, so the events cannot cross."""
    business_one, business_two = businesses
    redis = get_redis()
    pubsub = await subscribe(redis, business_one.id)

    try:
        await asyncio.sleep(0.2)
        assert await publish(redis, business_two.id, Event(type="bubble.created"))

        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        assert message is None, "a subscriber received another business's event"
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()
        await redis.aclose()


def test_the_stream_endpoint_takes_no_business_id_parameter():
    """A stream that took a business_id would let any user watch any tenant.

    The business comes from the token, so the endpoint has no parameter to
    tamper with.

    The route's signature is asserted rather than its response: an SSE stream
    never ends, and the ASGI transport buffers a response body, so opening the
    stream over HTTP would hang the test rather than check anything.
    """
    from fastapi.routing import APIRoute

    from xenovarients.api.events import router

    route = next(r for r in router.routes if isinstance(r, APIRoute) and r.path.endswith("/stream"))
    assert route.methods is not None and "GET" in route.methods
    assert route.path == "/api/v1/events/stream", "the path must not carry a tenant"
    query_params = {p.name for p in route.dependant.query_params}
    assert "business_id" not in query_params


@pytest.mark.asyncio
async def test_an_unauthenticated_caller_gets_no_stream(client: AsyncClient, businesses):
    """No token, no stream."""
    response = await client.get("/api/v1/events/stream")
    assert response.status_code == 401


def test_events_are_namespaced_by_business():
    """Two businesses' channels are different, so a subscriber hears only its own."""
    a = channel_for(uuid.uuid4())
    b = channel_for(uuid.uuid4())
    assert a != b
