"""The worker process: the loop that actually runs scheduled work.

``jobs/runner.py`` holds the machinery — claim, run, retry, reap. This module is the
process that drives it, and outside the tests it is the only thing that does. Without
a running worker, nothing scheduled ever executes: review requests are never sent,
inbound events never resolve, restock detection never fires, and the outbound
dispatcher (a ``retry_delivery`` job) never runs either.

Run it with::

    python -m xenovarients.jobs.worker     # or the xenovarients-worker script

**It discovers tenants by walking ``businesses``, not ``scheduled_jobs``.** Row-level
security hides every tenant's job rows until ``app.business_id`` is set, so a
cross-tenant "which jobs are due?" query returns an empty set under the app role. The
tenant root is not RLS-protected, so the sweep starts there and each tenant is polled
in its own bound session.

shortcut: one pass over every business per interval; move to a due-jobs query against
a BYPASSRLS role once the tenant count makes the sweep expensive.
"""

import asyncio
import contextlib
import logging
import signal
import uuid

from sqlalchemy import select

from xenovarients.core.config import get_settings
from xenovarients.core.logging import configure_logging
from xenovarients.db.session import SessionLocal, dispose_engine
from xenovarients.jobs import handlers  # noqa: F401 — importing registers the handlers
from xenovarients.jobs.runner import poll_once
from xenovarients.models.tenancy import Business

logger = logging.getLogger(__name__)

# How long to wait between passes when no wake-up arrives.
INTERVAL_SECONDS = 5.0

# Jobs claimed per business per pass.
BATCH_SIZE = 20


async def business_ids() -> list[uuid.UUID]:
    """Every tenant, read from the tenant root.

    ``businesses`` carries no RLS policy, which is what makes it readable here with no
    tenant bound. The tenant-scoped tables are not — that is the whole point of them.
    """
    async with SessionLocal() as session:
        rows = await session.execute(select(Business.id))
        return list(rows.scalars().all())


async def poll_all_once(*, limit: int = BATCH_SIZE) -> dict[str, int]:
    """Run one pass of the worker over every business.

    One tenant's failure must not stop the pass for the others, so each is caught and
    logged individually.
    """
    total = {"businesses": 0, "done": 0, "failed": 0}
    for business_id in await business_ids():
        try:
            counts = await poll_once(business_id, limit=limit)
        except Exception:  # noqa: BLE001 — one bad tenant must not stop the queue
            logger.exception("Worker pass failed for business %s", business_id)
            continue
        total["businesses"] += 1
        total["done"] += counts["done"]
        total["failed"] += counts["failed"]
    return total


async def run_forever(
    *,
    interval_seconds: float = INTERVAL_SECONDS,
    limit: int = BATCH_SIZE,
) -> None:
    """Poll until SIGINT or SIGTERM, then return so the caller can clean up."""
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stopping.set)
        except NotImplementedError:  # Windows has no loop signal handlers
            signal.signal(sig, lambda *_: stopping.set())

    logger.info("Worker started (interval=%.1fs, batch=%d)", interval_seconds, limit)
    while not stopping.is_set():
        counts = await poll_all_once(limit=limit)
        if counts["done"] or counts["failed"]:
            logger.info(
                "Worker pass: %d done, %d failed across %d businesses",
                counts["done"],
                counts["failed"],
                counts["businesses"],
                extra={"outcome": "job_pass"},
            )
        try:
            await asyncio.wait_for(stopping.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
    logger.info("Worker stopped")


async def _run() -> None:
    try:
        await run_forever()
    finally:
        await dispose_engine()


def main() -> None:
    """Entry point for ``python -m xenovarients.jobs.worker`` and the console script."""
    configure_logging(get_settings().log_level)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run())


if __name__ == "__main__":
    main()
