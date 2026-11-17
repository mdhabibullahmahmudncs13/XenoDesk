"""The scheduler: idempotent scheduling, atomic claiming, bounded retries.

The properties that matter: the same logical job scheduled twice exists once, two
workers never run the same job, and a failing job is retried a bounded number of
times before being marked failed.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from xenovarients.models.platform import JobState, JobType, ScheduledJob
from xenovarients.platform.scheduler import (
    cancel,
    claim_due,
    complete,
    fail,
    schedule,
    wakeup_key,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_scheduling_the_same_key_twice_creates_one_job(session, businesses, bind):
    """The same logical job scheduled twice exists once."""
    business_one, _ = businesses
    await bind(business_one.id)
    key = f"job-{uuid.uuid4().hex[:12]}"

    first = await schedule(
        session,
        business_id=business_one.id,
        job_type=JobType.review_request,
        run_at=datetime.now(UTC) + timedelta(minutes=5),
        idempotency_key=key,
        payload={"order_id": str(uuid.uuid4())},
    )
    await session.commit()

    second = await schedule(
        session,
        business_id=business_one.id,
        job_type=JobType.review_request,
        run_at=datetime.now(UTC) + timedelta(minutes=5),
        idempotency_key=key,
    )
    await session.commit()

    assert first.id == second.id
    rows = list(
        (await session.execute(select(ScheduledJob).where(ScheduledJob.idempotency_key == key)))
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_a_job_is_not_claimed_before_it_is_due(session, businesses, bind):
    business_one, _ = businesses
    await bind(business_one.id)
    await schedule(
        session,
        business_id=business_one.id,
        job_type=JobType.review_request,
        run_at=datetime.now(UTC) + timedelta(hours=1),
        idempotency_key=f"job-{uuid.uuid4().hex[:12]}",
    )
    await session.commit()

    assert await claim_due(session, business_id=business_one.id) == []


@pytest.mark.asyncio
async def test_a_due_job_is_claimed(session, businesses, bind):
    business_one, _ = businesses
    await bind(business_one.id)
    job = await schedule(
        session,
        business_id=business_one.id,
        job_type=JobType.review_request,
        run_at=datetime.now(UTC) - timedelta(minutes=1),
        idempotency_key=f"job-{uuid.uuid4().hex[:12]}",
    )
    await session.commit()

    claimed = await claim_due(session, business_id=business_one.id)
    await session.commit()

    assert [j.id for j in claimed] == [job.id]
    assert claimed[0].state == JobState.claimed.value


@pytest.mark.asyncio
async def test_a_claimed_job_is_not_claimed_again(session, businesses, bind):
    """Two workers must not run the same job."""
    business_one, _ = businesses
    await bind(business_one.id)
    await schedule(
        session,
        business_id=business_one.id,
        job_type=JobType.review_request,
        run_at=datetime.now(UTC) - timedelta(minutes=1),
        idempotency_key=f"job-{uuid.uuid4().hex[:12]}",
    )
    await session.commit()

    first = await claim_due(session, business_id=business_one.id)
    await session.commit()
    second = await claim_due(session, business_id=business_one.id)
    await session.commit()

    assert len(first) == 1
    assert second == []


@pytest.mark.asyncio
async def test_a_job_is_not_claimed_for_another_business(session, businesses, bind):
    """Tenant isolation applies to the queue too."""
    business_one, business_two = businesses
    await bind(business_one.id)
    await schedule(
        session,
        business_id=business_one.id,
        job_type=JobType.review_request,
        run_at=datetime.now(UTC) - timedelta(minutes=1),
        idempotency_key=f"job-{uuid.uuid4().hex[:12]}",
    )
    await session.commit()

    await bind(business_two.id)
    assert await claim_due(session, business_id=business_two.id) == []


@pytest.mark.asyncio
async def test_a_failed_job_is_retried_with_a_backoff(session, businesses, bind):
    business_one, _ = businesses
    await bind(business_one.id)
    job = await schedule(
        session,
        business_id=business_one.id,
        job_type=JobType.review_request,
        run_at=datetime.now(UTC) - timedelta(minutes=1),
        idempotency_key=f"job-{uuid.uuid4().hex[:12]}",
    )
    await session.commit()

    before = datetime.now(UTC)
    await fail(session, job=job, error="provider exploded")
    await session.commit()

    assert job.state == JobState.pending.value
    assert job.attempts == 1
    assert job.last_error == "provider exploded"
    assert job.run_at > before


@pytest.mark.asyncio
async def test_the_retry_budget_is_bounded(session, businesses, bind):
    from xenovarients.core.config import get_settings

    settings = get_settings()
    business_one, _ = businesses
    await bind(business_one.id)
    job = await schedule(
        session,
        business_id=business_one.id,
        job_type=JobType.review_request,
        run_at=datetime.now(UTC) - timedelta(minutes=1),
        idempotency_key=f"job-{uuid.uuid4().hex[:12]}",
    )
    await session.commit()

    for _ in range(settings.max_delivery_attempts):
        await fail(session, job=job, error="still broken")
    await session.commit()

    assert job.state == JobState.failed.value
    assert job.attempts == settings.max_delivery_attempts


@pytest.mark.asyncio
async def test_a_completed_job_is_done(session, businesses, bind):
    business_one, _ = businesses
    await bind(business_one.id)
    job = await schedule(
        session,
        business_id=business_one.id,
        job_type=JobType.review_request,
        run_at=datetime.now(UTC) - timedelta(minutes=1),
        idempotency_key=f"job-{uuid.uuid4().hex[:12]}",
    )
    await session.commit()

    await complete(session, job=job)
    await session.commit()

    assert job.state == JobState.done.value
    assert job.last_error is None


@pytest.mark.asyncio
async def test_a_completed_job_is_not_claimed_again(session, businesses, bind):
    business_one, _ = businesses
    await bind(business_one.id)
    job = await schedule(
        session,
        business_id=business_one.id,
        job_type=JobType.review_request,
        run_at=datetime.now(UTC) - timedelta(minutes=1),
        idempotency_key=f"job-{uuid.uuid4().hex[:12]}",
    )
    await session.commit()
    await complete(session, job=job)
    await session.commit()

    assert await claim_due(session, business_id=business_one.id) == []


@pytest.mark.asyncio
async def test_a_cancelled_job_is_not_claimed(session, businesses, bind):
    business_one, _ = businesses
    await bind(business_one.id)
    job = await schedule(
        session,
        business_id=business_one.id,
        job_type=JobType.review_request,
        run_at=datetime.now(UTC) - timedelta(minutes=1),
        idempotency_key=f"job-{uuid.uuid4().hex[:12]}",
    )
    await session.commit()
    await cancel(session, job=job)
    await session.commit()

    assert await claim_due(session, business_id=business_one.id) == []


def test_the_wakeup_key_is_per_business() -> None:
    business_id = uuid.uuid4()
    assert wakeup_key(business_id) != wakeup_key(uuid.uuid4())
    assert str(business_id) in wakeup_key(business_id)
