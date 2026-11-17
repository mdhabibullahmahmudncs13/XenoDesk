"""Audit log: it records, it stays append-only, and it does not leak across tenants."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.models.tenancy import AuditLog, Business
from xenovarients.platform import audit

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_record_hashes_before_and_after(
    session: AsyncSession,
    businesses: tuple[Business, Business],
    users_and_memberships,
    bind,
):
    """The log stores hashes, not payloads — a batch of recipients must not fit in a row."""
    business_one, _business_two = businesses
    owner, _staff, _m1, _m2 = users_and_memberships
    await bind(business_one.id)

    entry = await audit.record(
        session,
        business_id=business_one.id,
        action=audit.AuditAction.batch_approved,
        target_type="restock_batch",
        target_id="batch-1",
        actor_user_id=owner.id,
        before={"recipients": 5000},
        after={"recipients": 4000},
    )
    await session.commit()

    assert entry.before_hash is not None
    assert entry.after_hash is not None
    assert entry.before_hash != entry.after_hash
    # The payload must not be recoverable from the row.
    assert "5000" not in (entry.metadata_json or {}).values()


@pytest.mark.asyncio
async def test_audit_log_rejects_update(
    session: AsyncSession, businesses: tuple[Business, Business], bind
):
    """A DB trigger blocks UPDATE. This is the guarantee, not a convention."""
    business_one, _ = businesses
    await bind(business_one.id)
    await audit.record(
        session,
        business_id=business_one.id,
        action=audit.AuditAction.consent_changed,
        target_type="contact_permission",
        target_id="cp-1",
    )
    await session.commit()

    with pytest.raises(DBAPIError) as exc_info:
        await session.execute(text("UPDATE audit_log SET action = 'tampered'"))
        await session.commit()
    assert "append-only" in str(exc_info.value)
    await session.rollback()


@pytest.mark.asyncio
async def test_audit_log_rejects_delete(
    session: AsyncSession, businesses: tuple[Business, Business], bind
):
    business_one, _ = businesses
    await bind(business_one.id)
    await audit.record(
        session,
        business_id=business_one.id,
        action=audit.AuditAction.export_created,
        target_type="export",
        target_id="export-1",
    )
    await session.commit()

    with pytest.raises(DBAPIError) as exc_info:
        await session.execute(text("DELETE FROM audit_log"))
        await session.commit()
    assert "append-only" in str(exc_info.value)
    await session.rollback()


@pytest.mark.asyncio
async def test_audit_entries_are_tenant_scoped(
    session: AsyncSession, businesses: tuple[Business, Business], bind
):
    """One business must not read another business's audit trail."""
    business_one, business_two = businesses
    await bind(business_one.id)
    await audit.record(
        session,
        business_id=business_one.id,
        action=audit.AuditAction.role_changed,
        target_type="business_membership",
        target_id="bm-1",
    )
    await session.commit()

    # Under the other tenant, the entry is invisible.
    await bind(business_two.id)
    visible = (
        (await session.execute(select(AuditLog).where(AuditLog.business_id == business_one.id)))
        .scalars()
        .all()
    )
    assert visible == []
