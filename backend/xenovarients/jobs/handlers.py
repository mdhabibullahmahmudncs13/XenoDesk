"""Job handlers.

Each handler does one job type's work. Handlers are registered here so a new job
type is one function — the registry in ``runner.py`` finds it by name.

``retry_delivery`` is the one handler that ships in Phase 2, because the outbound
dispatcher it drives already exists. The others (``review_request``,
``restock_batch_dispatch``, ``inventory_poll``) belong to the M1 and M2 features and
are registered when those features land.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.jobs.runner import register
from xenovarients.platform.channels import build_adapters
from xenovarients.platform.outbound import dispatch_batch


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

    for channel in wanted:
        adapter = adapters.get(channel)
        if adapter is None:
            continue
        await dispatch_batch(session, business_id=business_id, adapter=adapter)
