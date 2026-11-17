"""Realtime events: Redis pub/sub in, SSE out.

**The publish path never blocks on a subscriber.** A dashboard that is slow to read
must not slow down the action that triggered the event. Publishing is a fire-and-
forget Redis write; if Redis is down the event is lost, and that is acceptable —
the dashboard re-reads the REST state on reconnect, so the SSE stream is an
*acceleration*, not the source of truth.

**Events are namespaced by business.** The channel name carries the business id, so
a subscriber for tenant A can never receive tenant B's events even if a publisher
mixes up the arguments.

**Reconnect is the client's job, and it must not duplicate.** The browser's
``EventSource`` reconnects automatically; the server treats each connection as
independent and sends a heartbeat so a dead connection is noticed rather than
silently hanging.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from xenovarients.core.config import get_settings

logger = logging.getLogger(__name__)

# The Redis pub/sub channel for one business's events.
CHANNEL_TEMPLATE = "xenovarients:events:{business_id}"

# The heartbeat interval. A proxy that drops idle connections kills the stream
# silently otherwise, and the client cannot tell a slow stream from a dead one.
HEARTBEAT_SECONDS = 15.0


@dataclass(frozen=True)
class Event:
    """One realtime event."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_json(self) -> str:
        return json.dumps({"id": self.event_id, "type": self.type, "data": self.data})


def channel_for(business_id: uuid.UUID | str) -> str:
    """The Redis pub/sub channel for a business."""
    return CHANNEL_TEMPLATE.format(business_id=business_id)


async def publish(redis: Any, business_id: uuid.UUID | str, event: Event) -> bool:
    """Publish an event to a business's subscribers.

    Returns whether the publish succeeded. A failure is logged and swallowed: the
    event is an acceleration of the REST state, not the state itself.
    """
    try:
        await redis.publish(channel_for(business_id), event.to_json())
        return True
    except Exception as exc:  # noqa: BLE001 — a failed publish must not fail the action
        logger.warning("Could not publish realtime event %s: %s", event.type, exc)
        return False


async def subscribe(redis: Any, business_id: uuid.UUID | str) -> Any:
    """Open a pub/sub subscription for a business.

    Returns the subscription object; the caller iterates it and closes it when the
    client disconnects.
    """
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel_for(business_id))
    return pubsub


def format_sse(event: Event) -> str:
    """Render an event in the SSE wire format."""
    return f"id: {event.event_id}\nevent: {event.type}\ndata: {event.to_json()}\n\n"


def format_sse_raw(payload: str) -> str:
    """Render a published payload as an SSE frame.

    The payload was produced by ``Event.to_json``, so the type is read back out of
    it rather than carried alongside the data.
    """
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return format_comment()
    if not isinstance(data, dict):
        return format_comment()
    return f"id: {data.get('id', '')}\nevent: {data.get('type', 'message')}\ndata: {payload}\n\n"


def format_comment(text: str = "heartbeat") -> str:
    """Render an SSE comment — used for the heartbeat.

    A comment is ignored by the browser's ``EventSource`` but keeps the connection
    alive and lets the server notice a client that has gone away.
    """
    return f": {text}\n\n"


def get_redis() -> Any:
    """The Redis client.

    Imported lazily so a process that never serves SSE does not need a live Redis
    connection to start.
    """
    from redis.asyncio import Redis

    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)
