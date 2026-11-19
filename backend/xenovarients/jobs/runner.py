"""The job worker: claim due jobs, run them, record the outcome.

A job handler is a coroutine that takes the job payload and does the work. Handlers
are registered by name so a new job type is one function and one registration — no
switch statement to grow.

**A handler that raises does not lose the job.** The failure is recorded, the job
goes back to ``pending`` with a backoff, and the retry budget eventually marks it
``failed``. A worker that dies mid-job leaves the job in ``claimed``; the reaper
returns stale claims to ``pending`` so the work is not stranded.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.db.session import SessionLocal
from xenovarients.db.tenant import (
    bind_tenant,
    clear_tenant,
    install_tenant_filter,
    reset_tenant,
)
from xenovarients.models.platform import JobState, ScheduledJob
from xenovarients.platform.scheduler import claim_due, complete, fail

logger = logging.getLogger(__name__)

JobHandler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]

_handlers: dict[str, JobHandler] = {}

# A claim older than this is considered stranded — the worker died holding it.
STALE_CLAIM_SECONDS = 300


def register(job_type: str) -> Callable[[JobHandler], JobHandler]:
    """Register a handler for a job type."""

    def _decorate(handler: JobHandler) -> JobHandler:
        _handlers[job_type] = handler
        return handler

    return _decorate


def handlers() -> dict[str, JobHandler]:
    return dict(_handlers)


async def run_job(session: AsyncSession, *, job: ScheduledJob) -> ScheduledJob:
    """Run one job's handler, recording success or failure.

    The handler runs in the job's own transaction: a handler that fails leaves no
    partial state behind, because the failure path rolls back before scheduling the
    retry.
    """
    handler = _handlers.get(job.job_type)
    if handler is None:
        job.state = JobState.failed.value
        job.last_error = f"No handler registered for job type '{job.job_type}'."
        await session.flush()
        return job

    try:
        await handler(session, job.payload or {})
    except Exception as exc:  # noqa: BLE001 — a handler failure must not kill the worker
        logger.exception("Job %s (%s) failed", job.id, job.job_type)
        await session.rollback()
        job = await fail(session, job=job, error=str(exc))
        await session.commit()
        return job

    await complete(session, job=job)
    await session.commit()
    return job


async def reap_stale_claims(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Return stranded ``claimed`` jobs to ``pending``.

    A worker that crashes mid-job leaves the row in ``claimed`` forever. This finds
    those rows and hands them back to the queue.
    """
    moment = now or datetime.now(UTC)
    cutoff = moment - timedelta(seconds=STALE_CLAIM_SECONDS)
    result = await session.execute(
        select(ScheduledJob).where(
            ScheduledJob.state == JobState.claimed.value,
            # The claim time, not the creation time: a job scheduled an hour ago and
            # claimed a second ago is not stale, and reaping it would let a second
            # worker run a handler the first one is still running.
            ScheduledJob.updated_at <= cutoff,
        )
    )
    stale = list(result.scalars().all())
    for job in stale:
        job.state = JobState.pending.value
    if stale:
        await session.commit()
    return len(stale)


async def run_due(business_id: uuid.UUID, *, limit: int = 20) -> dict[str, int]:
    """Claim and run every job that is due for one business.

    Each job runs in its own tenant-bound session, so a handler sees exactly the
    business it belongs to.
    """
    counts = {"done": 0, "failed": 0}

    async with SessionLocal() as session:
        install_tenant_filter(session)
        await bind_tenant(session, str(business_id))
        try:
            jobs = await claim_due(session, business_id=business_id, limit=limit)
            await session.commit()
        finally:
            await session.rollback()
            await clear_tenant(session)
            reset_tenant()

    for job in jobs:
        async with SessionLocal() as session:
            install_tenant_filter(session)
            await bind_tenant(session, str(business_id))
            try:
                done = await run_job(session, job=job)
                counts["done" if done.state == JobState.done.value else "failed"] += 1
            finally:
                await session.rollback()
                await clear_tenant(session)
                reset_tenant()

    return counts


async def poll_once(business_id: uuid.UUID, *, limit: int = 20) -> dict[str, int]:
    """Reap stale claims, then run what is due. One pass of the worker loop."""
    async with SessionLocal() as session:
        install_tenant_filter(session)
        # The reaper reads this tenant's claimed jobs, so it needs the tenant bound
        # exactly like a handler does — an unbound query raises TenantScopeError.
        await bind_tenant(session, str(business_id))
        try:
            await reap_stale_claims(session)
        finally:
            await session.rollback()
            await clear_tenant(session)
            reset_tenant()
    return await run_due(business_id, limit=limit)


async def poll_forever(business_id: uuid.UUID, *, interval_seconds: float = 5.0) -> None:
    """The worker loop. Runs until cancelled."""
    while True:
        await poll_once(business_id)
        await asyncio.sleep(interval_seconds)
