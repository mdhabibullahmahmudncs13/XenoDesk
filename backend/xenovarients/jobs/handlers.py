"""Job handlers.

Each handler does one job type's work. Handlers are registered here so a new job
type is one function — the registry in ``runner.py`` finds it by name.

``retry_delivery`` drives the outbound dispatcher; ``source_sync`` drives the M1
sync job. The others (``review_request``, ``restock_batch_dispatch``) belong to the
M2 features and are registered when those features land.
"""

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.jobs.runner import register
from xenovarients.platform.channels import build_adapters
from xenovarients.platform.inbound_processing import process_pending_events
from xenovarients.platform.outbound import dispatch_batch
from xenovarients.platform.source import StubSource
from xenovarients.platform.sync import sync_customers, sync_inventory, sync_orders


@register("retry_delivery")
async def retry_delivery(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Dispatch the outbound messages that are due on each channel.

    The payload names the channels to dispatch; an empty payload means "every
    channel this deployment has an adapter for".
    """
    business_id = payload.get("business_id")
    if business_id is None:
        raise ValueError("retry_delivery needs a business_id in its payload.")

    adapters = build_adapters()
    wanted: list[str] = payload.get("channels") or list(adapters)

    redis = _redis()
    for channel in wanted:
        adapter = adapters.get(channel)
        if adapter is None:
            continue
        await dispatch_batch(session, business_id=business_id, adapter=adapter, redis=redis)


def _redis() -> Any:
    """The Redis client for the rate limiter.

    None when Redis is unreachable: the limiter fails open, so the sends go out
    and the provider's own throttle handles the overflow.
    """
    from xenovarients.platform.realtime import get_redis

    try:
        return get_redis()
    except Exception:  # noqa: BLE001 — a missing Redis must not stop dispatch
        return None


@register("source_sync")
async def source_sync(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Pull the source's data into the mirror (CG-04).

    The payload may carry ``updated_since`` to read only what changed since the
    last run. A missing value means a full backfill.

    The source is the stub until OD-01 is answered; swapping in a real adapter is a
    one-class change (see ``platform/source.py``).
    """
    business_id = payload.get("business_id")
    if business_id is None:
        raise ValueError("source_sync needs a business_id in its payload.")

    updated_since = _as_datetime(payload.get("updated_since"))
    source = StubSource()

    await sync_inventory(session, business_id=business_id, source=source)
    await sync_customers(
        session, business_id=business_id, source=source, updated_since=updated_since
    )
    await sync_orders(session, business_id=business_id, source=source, updated_since=updated_since)


def _as_datetime(value: Any) -> datetime | None:
    """The payload's timestamp, or None when there is none."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise ValueError(f"updated_since must be a timestamp, got {type(value).__name__}.")


@register("process_inbound")
async def process_inbound(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Turn the stored inbound events into Returning Customer bubbles.

    The webhook endpoint only stores and acknowledges; this handler does the work
    afterwards, so a slow resolution never makes a provider time out.
    """
    business_id = payload.get("business_id")
    if business_id is None:
        raise ValueError("process_inbound needs a business_id in its payload.")

    redis = _redis()
    await process_pending_events(
        session,
        business_id=business_id,
        limit=int(payload.get("limit") or 50),
        redis=redis,
    )
