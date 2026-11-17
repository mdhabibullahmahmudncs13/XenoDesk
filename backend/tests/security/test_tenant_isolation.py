"""Tenant isolation tests.

Two independent layers must both hold:

1. The ORM TenantFilter — a tenant-scoped query with no tenant in context raises
   ``TenantScopeError`` rather than returning every tenant's rows.
2. Postgres RLS — even raw SQL as the app role sees only the current tenant's rows.

A regression in either one is a data leak, so both are asserted here.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.db.tenant import TenantScopeError, reset_tenant
from xenovarients.models.customer import Customer

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def two_tenants(session: AsyncSession, businesses, bind) -> tuple[uuid.UUID, uuid.UUID]:
    """One customer per tenant, inserted under each tenant's own context.

    RLS is active, so a row for tenant B must be written while the session's tenant
    is B — that is the same rule the application obeys.
    """
    b1, b2 = businesses
    for business, name in ((b1, "cust-one"), (b2, "cust-two")):
        await bind(business.id)
        session.add(
            Customer(
                business_id=business.id,
                source_customer_id=name,
                name=name,
                total_orders=0,
                total_spend=0,
                is_repeat_buyer=False,
            )
        )
        await session.commit()
    reset_tenant()
    return b1.id, b2.id


@pytest.mark.asyncio
async def test_tenant_filter_scopes_queries(session: AsyncSession, two_tenants, bind):
    """Each tenant sees only its own customers."""
    b1, b2 = two_tenants
    await bind(b1)
    rows = (await session.execute(select(Customer))).scalars().all()
    assert {r.name for r in rows} == {"cust-one"}

    await bind(b2)
    rows = (await session.execute(select(Customer))).scalars().all()
    assert {r.name for r in rows} == {"cust-two"}


@pytest.mark.asyncio
async def test_tenant_filter_raises_without_tenant(session: AsyncSession, two_tenants):
    """No tenant in context is an error, not an empty result and not all rows."""
    reset_tenant()
    with pytest.raises(TenantScopeError):
        await session.execute(select(Customer))


@pytest.mark.asyncio
async def test_tenant_filter_blocks_update_across_tenants(session: AsyncSession, two_tenants, bind):
    """An UPDATE cannot touch another tenant's row.

    The ORM filter adds ``business_id = <current tenant>`` to the UPDATE, so the
    statement matches no rows. SQLAlchemy surfaces that as ``StaleDataError``
    rather than silently updating the other tenant's data.
    """
    from sqlalchemy.orm.exc import StaleDataError

    b1, b2 = two_tenants
    await bind(b2)
    target = (await session.execute(select(Customer))).scalars().one()

    await bind(b1)
    target.name = "hijacked"
    with pytest.raises(StaleDataError):
        await session.commit()
    await session.rollback()

    await bind(b2)
    target = (await session.execute(select(Customer))).scalars().one()
    assert target.name == "cust-two"


@pytest.mark.asyncio
async def test_rls_blocks_cross_tenant_read(session: AsyncSession, two_tenants, bind):
    """The database layer holds even when the ORM layer is bypassed with raw SQL."""
    b1, b2 = two_tenants
    await bind(b1)
    count = await session.scalar(text("SELECT count(*) FROM customers"))
    assert count == 1

    await bind(b2)
    count = await session.scalar(text("SELECT count(*) FROM customers"))
    assert count == 1


@pytest.mark.asyncio
async def test_rls_hides_everything_without_a_tenant(session: AsyncSession, two_tenants):
    """With no tenant set, RLS shows zero rows rather than everything."""
    reset_tenant()
    await session.execute(text("SELECT set_config('app.business_id', '', true)"))
    count = await session.scalar(text("SELECT count(*) FROM customers"))
    assert count == 0
