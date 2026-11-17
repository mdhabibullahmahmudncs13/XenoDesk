"""Every shared service is tenant-scoped.

Phase 2's exit criterion is that *every* shared service has an isolation test, not
just the customer table. Each service writes into a tenant-scoped table, and a
service that reads across tenants leaks one business's customers into another's
dashboard.

**Both layers are asserted separately.** A test that only checks the visible
result passes whenever *either* layer holds — so it cannot tell a working
guarantee from a lucky one. The ORM layer is checked on the *compiled statement*
(does it carry the tenant predicate?), and the RLS layer on the *visible result*
(as raw SQL, with the ORM filter out of the way).

The first half of each test asserts the ORM predicate; the second asserts that
raw SQL still sees nothing. Break either layer and exactly one half fails.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.db.tenant import _apply_tenant_predicate
from xenovarients.models.customer import Customer
from xenovarients.models.messaging import (
    ContactPermission,
    IdentityConflict,
    InboundMessageEvent,
    MessagingIdentityLink,
)
from xenovarients.models.outbound import OutboundMessage
from xenovarients.models.platform import IdempotencyRecord, ScheduledJob
from xenovarients.platform.identity import grant_permission, link

pytestmark = pytest.mark.integration


def assert_orm_scoped(statement: Select[Any], business_id: uuid.UUID) -> None:
    """The ORM layer adds the tenant predicate to this statement.

    Asserted on the compiled SQL, not the result: the result is masked by RLS, so
    a result-only assertion cannot tell the two layers apart.
    """
    scoped = _apply_tenant_predicate(statement, str(business_id))
    compiled = scoped.compile()
    sql = str(compiled)
    params = {key: str(value) for key, value in compiled.params.items()}
    assert "business_id" in sql
    assert str(business_id) in params.values()


async def assert_rls_hides(conn_table: str, session: AsyncSession) -> None:
    """The RLS layer shows nothing to the other business.

    Raw SQL, so the ORM filter is not involved — this is the database's guarantee
    on its own.
    """
    count = await session.scalar(text(f"SELECT count(*) FROM {conn_table}"))
    assert count == 0


@pytest_asyncio.fixture
async def customer(session: AsyncSession, businesses, bind) -> Customer:
    """One customer in business one, written under business one's context."""
    business_one, _ = businesses
    await bind(business_one.id)
    row = Customer(
        business_id=business_one.id,
        source_customer_id=f"src-c-{uuid.uuid4().hex[:10]}",
        name="Nadia",
        phone_e164="+8801712345678",
    )
    session.add(row)
    await session.commit()
    return row


async def test_identity_links_do_not_leak(session: AsyncSession, businesses, customer, bind):
    """A verified identity link belongs to one business."""
    business_one, business_two = businesses
    await bind(business_one.id)
    await link(
        session,
        business_id=business_one.id,
        channel="sms",
        channel_user_id="+8801712345678",
        customer_id=customer.id,
    )
    await session.commit()

    assert_orm_scoped(select(MessagingIdentityLink), business_one.id)

    await bind(business_two.id)
    assert (await session.execute(select(MessagingIdentityLink))).scalars().all() == []
    await assert_rls_hides("messaging_identity_links", session)


async def test_identity_conflicts_do_not_leak(session: AsyncSession, businesses, customer, bind):
    """An unresolved identity conflict is a business's business."""
    business_one, business_two = businesses
    await bind(business_one.id)
    session.add(
        IdentityConflict(
            business_id=business_one.id,
            channel="sms",
            channel_user_id="+8801712345678",
            candidate_customer_ids=[str(customer.id)],
            reason="multiple_phone_matches",
            state="open",
        )
    )
    await session.commit()

    assert_orm_scoped(select(IdentityConflict), business_one.id)

    await bind(business_two.id)
    assert (await session.execute(select(IdentityConflict))).scalars().all() == []
    await assert_rls_hides("identity_conflicts", session)


async def test_contact_permissions_do_not_leak(session: AsyncSession, businesses, customer, bind):
    """Consent is per business. Another business must not inherit it."""
    business_one, business_two = businesses
    await bind(business_one.id)
    await grant_permission(
        session,
        business_id=business_one.id,
        customer_id=customer.id,
        channel="sms",
        contact_value="+8801712345678",
        source="opt_in",
        purposes=["restock"],
    )
    await session.commit()

    assert_orm_scoped(select(ContactPermission), business_one.id)

    await bind(business_two.id)
    assert (await session.execute(select(ContactPermission))).scalars().all() == []
    await assert_rls_hides("contact_permissions", session)


async def test_inbound_events_do_not_leak(session: AsyncSession, businesses, customer, bind):
    """An inbound conversation belongs to one business only."""
    business_one, business_two = businesses
    await bind(business_one.id)
    session.add(
        InboundMessageEvent(
            business_id=business_one.id,
            provider_event_id=f"evt-{uuid.uuid4().hex[:8]}",
            channel="sms",
            channel_user_id="+8801712345678",
            direction="inbound",
            content="hello",
            received_at=datetime.now(UTC),
        )
    )
    await session.commit()

    assert_orm_scoped(select(InboundMessageEvent), business_one.id)

    await bind(business_two.id)
    assert (await session.execute(select(InboundMessageEvent))).scalars().all() == []
    await assert_rls_hides("inbound_message_events", session)


async def test_outbound_messages_do_not_leak(session: AsyncSession, businesses, customer, bind):
    """A queued message is invisible to another business."""
    business_one, business_two = businesses
    await bind(business_one.id)
    session.add(
        OutboundMessage(
            business_id=business_one.id,
            purpose="restock",
            ref_id=uuid.uuid4(),
            customer_id=customer.id,
            channel="sms",
            to_address="+8801712345678",
            body="Back in stock.",
            idempotency_key=f"idem-{uuid.uuid4().hex[:12]}",
            status="pending",
        )
    )
    await session.commit()

    assert_orm_scoped(select(OutboundMessage), business_one.id)

    await bind(business_two.id)
    assert (await session.execute(select(OutboundMessage))).scalars().all() == []
    await assert_rls_hides("outbound_messages", session)


async def test_scheduled_jobs_do_not_leak(session: AsyncSession, businesses, bind):
    """A queued job belongs to the business that scheduled it."""
    business_one, business_two = businesses
    await bind(business_one.id)
    session.add(
        ScheduledJob(
            business_id=business_one.id,
            job_type="retry_delivery",
            run_at=datetime.now(UTC) + timedelta(minutes=5),
            idempotency_key=f"job-{uuid.uuid4().hex[:12]}",
            state="pending",
        )
    )
    await session.commit()

    assert_orm_scoped(select(ScheduledJob), business_one.id)

    await bind(business_two.id)
    assert (await session.execute(select(ScheduledJob))).scalars().all() == []
    await assert_rls_hides("scheduled_jobs", session)


async def test_idempotency_records_do_not_leak(session: AsyncSession, businesses, bind):
    """A stored response is a business's, and replaying it must stay in that business.

    A record visible to another business would let that business's caller replay
    this business's response.
    """
    business_one, business_two = businesses
    await bind(business_one.id)
    session.add(
        IdempotencyRecord(
            business_id=business_one.id,
            key=f"key-{uuid.uuid4().hex[:12]}",
            endpoint="/api/v1/auth/logout",
            request_fingerprint="a" * 64,
            status_code=204,
            response_body={},
            response_headers={},
        )
    )
    await session.commit()

    assert_orm_scoped(select(IdempotencyRecord), business_one.id)

    await bind(business_two.id)
    assert (await session.execute(select(IdempotencyRecord))).scalars().all() == []
    await assert_rls_hides("idempotency_records", session)


async def test_the_same_key_in_two_businesses_is_two_records(
    session: AsyncSession, businesses, bind
):
    """The idempotency key is unique per business, not globally.

    Two businesses using the same client-generated key must not collide — the key
    is scoped by ``(business_id, key, endpoint)``.
    """
    business_one, business_two = businesses
    key = f"key-{uuid.uuid4().hex[:12]}"
    for business in (business_one, business_two):
        await bind(business.id)
        session.add(
            IdempotencyRecord(
                business_id=business.id,
                key=key,
                endpoint="/api/v1/auth/logout",
                request_fingerprint="a" * 64,
                status_code=204,
                response_body={},
                response_headers={},
            )
        )
        await session.commit()

    await bind(business_one.id)
    assert len((await session.execute(select(IdempotencyRecord))).scalars().all()) == 1
