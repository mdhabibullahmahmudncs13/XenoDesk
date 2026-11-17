"""Realtime events: the SSE wire format and the pub/sub contract."""

import json
import uuid
from typing import Any

import pytest

from xenovarients.platform.realtime import (
    Event,
    channel_for,
    format_comment,
    format_sse,
    format_sse_raw,
    publish,
)


def test_an_event_renders_as_an_sse_frame() -> None:
    event = Event(type="bubble.created", data={"customer_id": "c-1"})
    frame = format_sse(event)

    assert frame.startswith(f"id: {event.event_id}")
    assert "event: bubble.created" in frame
    assert frame.endswith("\n\n")

    payload = json.loads(frame.split("data: ", 1)[1].strip())
    assert payload["type"] == "bubble.created"
    assert payload["data"] == {"customer_id": "c-1"}


def test_a_raw_payload_renders_as_an_sse_frame() -> None:
    event = Event(type="bubble.updated", data={"id": "b-1"})
    frame = format_sse_raw(event.to_json())

    assert "event: bubble.updated" in frame
    assert event.event_id in frame


def test_a_malformed_payload_renders_as_a_comment() -> None:
    """A corrupt message must not break the stream."""
    assert format_sse_raw("not json").startswith(": ")


def test_a_comment_is_ignored_by_the_client() -> None:
    comment = format_comment("heartbeat")
    assert comment.startswith(": ")
    assert comment.endswith("\n\n")


def test_each_business_has_its_own_channel() -> None:
    """A subscriber for one tenant can never receive another's events."""
    a = channel_for(uuid.uuid4())
    b = channel_for(uuid.uuid4())
    assert a != b


class FakeRedis:
    """A Redis stand-in that records what was published."""

    def __init__(self, fail: bool = False) -> None:
        self.published: list[tuple[str, str]] = []
        self.fail = fail

    async def publish(self, channel: str, payload: str) -> None:
        if self.fail:
            raise RuntimeError("Redis is down")
        self.published.append((channel, payload))


@pytest.mark.asyncio
async def test_publishing_reaches_the_business_channel() -> None:
    business_id = uuid.uuid4()
    redis = FakeRedis()
    event = Event(type="bubble.created", data={})

    assert await publish(redis, business_id, event) is True
    assert redis.published[0][0] == channel_for(business_id)
    assert json.loads(redis.published[0][1])["type"] == "bubble.created"


@pytest.mark.asyncio
async def test_a_publish_failure_does_not_raise() -> None:
    """The event is an acceleration of the REST state, not the state itself."""
    redis = FakeRedis(fail=True)
    assert await publish(redis, uuid.uuid4(), Event(type="bubble.created")) is False


def test_the_event_id_is_unique() -> None:
    assert Event(type="x").event_id != Event(type="x").event_id


def test_event_data_defaults_to_empty() -> None:
    event: Any = Event(type="bubble.created")
    assert event.data == {}
