"""Shared test fixtures.

Integration tests need a real Postgres — the RLS layer cannot be exercised against
SQLite, and the tenant guarantee is the thing most worth testing.

The schema is created by the *owner* role (it needs DDL rights) but the tests query
through the *app* role, which is not a superuser and does not have BYPASSRLS. That
split is what makes the RLS assertions meaningful — a superuser would bypass the
policies and the isolation tests would silently pass against an empty result set.

``TEST_DATABASE_URL`` points at the app role. ``TEST_ADMIN_DATABASE_URL`` points at
the owner role and is only used to create and tear down the schema.
"""

import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.rls import drop_rls, install_rls
from xenovarients.core.security import hash_password
from xenovarients.db.base import Base
from xenovarients.db.tenant import (
    bind_tenant,
    clear_tenant,
    install_tenant_filter,
    reset_tenant,
)
from xenovarients.main import create_app
from xenovarients.models.customer import Customer
from xenovarients.models.tenancy import Business, BusinessMembership, Role, User

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://xenovarients_app:xenovarients_app@localhost:55432/xenovarients_test",
)
TEST_ADMIN_DATABASE_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL",
    "postgresql+asyncpg://xenovarients:xenovarients@localhost:55432/xenovarients_test",
)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def schema() -> AsyncIterator[None]:
    """Create the schema, install the RLS policies and triggers, and grant the app role."""
    admin = create_async_engine(TEST_ADMIN_DATABASE_URL, poolclass=None)
    async with admin.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        await install_rls(conn)
        # Grants must come *after* create_all: GRANT ON ALL TABLES only covers the
        # tables that exist when it runs.
        await conn.execute(text("GRANT USAGE ON SCHEMA public TO xenovarients_app"))
        await conn.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
                "TO xenovarients_app"
            )
        )
        await conn.execute(
            text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO xenovarients_app")
        )
    yield
    async with admin.begin() as conn:
        await drop_rls(conn)
        await conn.run_sync(Base.metadata.drop_all)
    await admin.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def engine(schema):
    eng = create_async_engine(TEST_DATABASE_URL, poolclass=None)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def admin_session(schema):
    """A session as the schema owner, for cleanup that the app role cannot perform.

    ``audit_log`` is append-only: its trigger blocks DELETE, and TRUNCATE — which does
    not fire per-row DELETE triggers — needs privileges the app role deliberately does
    not have. This is the only way to clear it in tests, and it is exactly why the app
    role is kept this restricted.
    """
    eng = create_async_engine(TEST_ADMIN_DATABASE_URL, poolclass=None)
    maker = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def session(engine) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        install_tenant_filter(s)
        yield s
        await s.rollback()
        await clear_tenant(s)
        reset_tenant()


@pytest_asyncio.fixture(loop_scope="session")
async def bind(session: AsyncSession):
    """Bind the current session to a business (ORM filter + Postgres RLS variable)."""

    async def _bind(business_id: uuid.UUID) -> None:
        await bind_tenant(session, str(business_id))

    return _bind


@pytest_asyncio.fixture
async def customer_factory(session: AsyncSession):
    """Create and persist a customer under the currently bound tenant.

    The caller must already have bound a tenant (via the ``bind`` fixture) — the
    tenant filter would otherwise reject the insert, which is the point.
    """

    async def _factory(
        business_: Business,
        *,
        name: str | None = None,
        phone_e164: str | None = None,
        email_normalised: str | None = None,
    ) -> Customer:
        row = Customer(
            business_id=business_.id,
            source_customer_id=f"src-c-{uuid.uuid4().hex[:10]}",
            name=name,
            phone_e164=phone_e164,
            email_normalised=email_normalised,
        )
        session.add(row)
        await session.flush()
        return row

    return _factory


@pytest_asyncio.fixture
async def tenant_session_factory(engine):
    """Opens a session already bound to a business (ORM filter + RLS session variable)."""
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _factory(business_id: uuid.UUID) -> AsyncSession:
        s = maker()
        install_tenant_filter(s)
        await bind_tenant(s, str(business_id))
        return s

    return _factory


@pytest_asyncio.fixture(loop_scope="session")
async def clear_audit_log(
    session: AsyncSession, admin_session: AsyncSession
) -> AsyncIterator[Callable[[], Awaitable[None]]]:
    """Clear the append-only ``audit_log`` table.

    ``audit_log`` has a trigger that blocks DELETE, and its FKs are RESTRICT, so
    deleting a business or a user that has audit history fails outright. TRUNCATE does
    not fire per-row DELETE triggers, but it needs privileges the app role
    deliberately does not have — so the owner connection does it.

    This is the honest cost of an append-only log: it cannot be cleared through the
    normal application path, only by an administrator.
    """

    async def _clear() -> None:
        await session.rollback()
        await admin_session.execute(text("TRUNCATE audit_log CASCADE"))
        await admin_session.commit()

    yield _clear


@pytest_asyncio.fixture(loop_scope="session")
async def businesses(
    session: AsyncSession, clear_audit_log
) -> AsyncIterator[tuple[Business, Business]]:
    """Two unrelated businesses — the fixture pair for cross-tenant tests."""
    made = []
    for name in ("Business One", "Business Two"):
        business = Business(
            name=name,
            timezone="Asia/Dhaka",
            currency="BDT",
            webhook_secret="webhook-secret-for-tests",
        )
        session.add(business)
        await session.flush()
        made.append(business)
    await session.commit()
    yield made[0], made[1]
    await clear_audit_log()
    for business in made:
        await session.delete(business)
    await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def users_and_memberships(
    session: AsyncSession, businesses: tuple[Business, Business], bind, clear_audit_log
) -> AsyncIterator[tuple[User, User, BusinessMembership, BusinessMembership]]:
    """One owner in business one, one staff in business two.

    Memberships are tenant-exempt (they map a user to their businesses), so they are
    written without a tenant context. The rows are removed afterwards — the schema
    fixture is session-scoped, so leftover rows would collide on the next test.
    """
    owner = User(
        email="owner@example.com",
        name="Owner",
        password_hash=hash_password("correct-horse-battery"),
        is_active=True,
    )
    staff = User(
        email="staff@example.com",
        name="Staff",
        password_hash=hash_password("correct-horse-battery"),
        is_active=True,
    )
    session.add_all([owner, staff])
    await session.flush()
    memberships = []
    for business, user, role in (
        (businesses[0], owner, Role.owner.value),
        (businesses[1], staff, Role.staff.value),
    ):
        membership = BusinessMembership(business_id=business.id, user_id=user.id, role=role)
        session.add(membership)
        await session.commit()
        memberships.append(membership)
    yield owner, staff, memberships[0], memberships[1]
    await clear_audit_log()
    for membership in memberships:
        await session.delete(membership)
    await session.delete(owner)
    await session.delete(staff)
    await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
