"""Delayed work: scheduling, claiming and running jobs.

**The database is the source of truth, Redis is only a wake-up signal.** A job lives
in ``scheduled_jobs`` with a ``run_at``; Redis holds a key that expires at that
moment so a worker knows to look. If Redis is down, the worker still finds the job by
polling the table — Redis makes the worker *prompt*, not *correct*. A queue that only
exists in Redis loses jobs when Redis restarts.

**Idempotency is enforced by the database, not by the caller.** ``(business_id,
idempotency_key)`` is unique, so scheduling the same logical job twice creates one
row. The second schedule returns the existing job rather than raising, because
"schedule this review request" being called twice is normal, not an error.

**Claiming is atomic.** Two workers must not run the same job. The claim is a single
``UPDATE ... WHERE state = 'pending'`` — the row lock Postgres takes makes exactly
one worker win.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.core.config import get_settings
from xenovarients.models.platform import JobState, JobType, ScheduledJob

logger = logging.getLogger(__name__)

# The Redis key that tells a worker "there is work due". One per business so a
# worker can wake on the earliest job for that tenant.
WAKEUP_KEY = "xenovarients:jobs:wakeup:{business_id}"


async def schedule(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    job_type: JobType | str,
    run_at: datetime,
    idempotency_key: str,
    payload: dict[str, Any] | None = None,
) -> ScheduledJob:
    """Schedule a job to run at ``run_at``.

    Idempotent: scheduling the same ``idempotency_key`` twice returns the same job.
    """
    kind = job_type.value if isinstance(job_type, JobType) else job_type

    existing: ScheduledJob | None = await session.scalar(
        select(ScheduledJob).where(
            ScheduledJob.business_id == business_id,
            ScheduledJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing

    job = ScheduledJob(
        business_id=business_id,
        job_type=kind,
        run_at=run_at,
        state=JobState.pending.value,
        payload=payload or {},
        idempotency_key=idempotency_key,
    )
    session.add(job)
    try:
        await session.flush()
    except IntegrityError:
        # Another worker scheduled the same key between our SELECT and our INSERT.
        # The unique constraint is the real arbiter; roll back to the savepoint and
        # read the row the other worker created.
        await session.rollback()
        winner: ScheduledJob | None = await session.scalar(
            select(ScheduledJob).where(
                ScheduledJob.business_id == business_id,
                ScheduledJob.idempotency_key == idempotency_key,
            )
        )
        if winner is None:
            raise
        return winner
    return job


async def claim_due(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    now: datetime | None = None,
    limit: int = 20,
) -> list[ScheduledJob]:
    """Atomically claim the jobs that are due, so no two workers run the same one.

    The claim is one ``UPDATE`` with ``state = 'pending'`` in the WHERE clause. The
    row lock Postgres takes on that update means exactly one worker wins each row,
    and the ``RETURNING`` clause gives the winner back exactly what it claimed.
    """
    moment = now or datetime.now(UTC)
    result = await session.execute(
        update(ScheduledJob)
        .where(
            ScheduledJob.business_id == business_id,
            ScheduledJob.state == JobState.pending.value,
            ScheduledJob.run_at <= moment,
        )
        .values(state=JobState.claimed.value)
        .returning(ScheduledJob)
    )
    return list(result.scalars().all())


async def complete(session: AsyncSession, *, job: ScheduledJob) -> ScheduledJob:
    """Mark a job done."""
    job.state = JobState.done.value
    job.last_error = None
    await session.flush()
    return job


async def fail(
    session: AsyncSession,
    *,
    job: ScheduledJob,
    error: str,
    max_attempts: int | None = None,
    retry_delay_seconds: int | None = None,
) -> ScheduledJob:
    """Record a failure and decide whether to retry.

    A failed job goes back to ``pending`` with a later ``run_at`` — the same
    exponential backoff the outbound dispatcher uses — until the attempt budget is
    spent. Then it is ``failed`` for good.
    """
    settings = get_settings()
    budget = max_attempts if max_attempts is not None else settings.max_delivery_attempts
    base = (
        retry_delay_seconds
        if retry_delay_seconds is not None
        else settings.delivery_retry_base_seconds
    )

    job.attempts += 1
    job.last_error = error[:2000]

    if job.attempts >= budget:
        job.state = JobState.failed.value
        return job

    job.state = JobState.pending.value
    job.run_at = datetime.now(UTC) + _backoff(base, job.attempts)
    await session.flush()
    return job


def _backoff(base_seconds: int, attempt_number: int) -> Any:
    from datetime import timedelta

    return timedelta(seconds=base_seconds * (2 ** (attempt_number - 1)))


async def cancel(session: AsyncSession, *, job: ScheduledJob) -> ScheduledJob:
    """Cancel a job that has not run yet."""
    job.state = JobState.cancelled.value
    await session.flush()
    return job


def wakeup_key(business_id: uuid.UUID | str) -> str:
    """The Redis key a worker watches for a given business."""
    return WAKEUP_KEY.format(business_id=business_id)


async def publish_wakeup(redis: Any, business_id: uuid.UUID | str, delay_seconds: float) -> None:
    """Tell a worker that a job is due in ``delay_seconds``.

    The key expires on its own, so a missed wake-up leaves no stale state behind.
    Failure here is not fatal: the worker polls the table as well.
    """
    try:
        await redis.set(wakeup_key(business_id), "1", ex=max(1, int(delay_seconds) + 1))
    except Exception as exc:  # noqa: BLE001 — Redis is an optimisation, not a dependency
        logger.warning("Could not publish job wakeup: %s", exc)
