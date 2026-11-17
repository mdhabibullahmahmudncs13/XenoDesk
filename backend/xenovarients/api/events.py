"""The realtime event stream.

One SSE stream per business, authenticated like any other endpoint. The business
comes from the token, never from a query parameter — a stream that accepted a
``business_id`` parameter would let any authenticated user watch any tenant's
dashboard.
"""

import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from xenovarients.api.deps import Principal, get_principal
from xenovarients.platform.realtime import (
    HEARTBEAT_SECONDS,
    format_comment,
    format_sse_raw,
    get_redis,
    subscribe,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/events", tags=["realtime"])


async def _stream(request: Request, business_id: str) -> AsyncIterator[str]:
    """Yield SSE frames for one business until the client disconnects."""
    redis = get_redis()
    pubsub = await subscribe(redis, business_id)
    try:
        # Tell the client the stream is live before anything else. The browser's
        # EventSource fires onopen on the first frame, so an empty stream looks
        # like a connection that never came up.
        yield format_comment("connected")

        while True:
            if await request.is_disconnected():
                break
            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 — a Redis hiccup must not kill the stream
                logger.warning("Realtime subscribe failed: %s", exc)
                await asyncio.sleep(HEARTBEAT_SECONDS)
                continue

            if message is not None and message.get("type") == "message":
                yield format_sse_raw(message["data"])
            else:
                # No event in this second — send a heartbeat so proxies and the
                # client both know the stream is alive.
                yield format_comment()
    finally:
        try:
            await pubsub.unsubscribe()
            await pubsub.aclose()
        except Exception:  # noqa: BLE001 — closing a dead subscription must not raise
            logger.debug("Realtime subscription close failed", exc_info=True)
        await redis.aclose()


@router.get("/stream")
async def event_stream(
    request: Request,
    principal: Principal = Depends(get_principal),
) -> StreamingResponse:
    """Subscribe to this business's realtime events.

    The response is ``text/event-stream``. The client reconnects on its own;
    because events are an acceleration of the REST state rather than the state
    itself, a reconnect loses nothing that a re-read would not recover.
    """
    return StreamingResponse(
        _stream(request, str(principal.business_id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
