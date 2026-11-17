"""Database engine, session factory and the tenant-bound session dependency."""

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from xenovarients.core.config import get_settings
from xenovarients.db.tenant import (
    bind_tenant,
    clear_tenant,
    install_tenant_filter,
    reset_tenant,
)

_settings = get_settings()

engine = create_async_engine(
    str(_settings.database_url),
    echo=_settings.db_echo,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Plain session — no tenant. For auth, health checks and admin-only paths."""
    async with SessionLocal() as session:
        install_tenant_filter(session)
        try:
            yield session
        finally:
            reset_tenant()


async def get_tenant_session(business_id: str) -> AsyncIterator[AsyncSession]:
    """Session bound to a tenant. Every tenant-scoped query in it is filtered."""
    async with SessionLocal() as session:
        install_tenant_filter(session)
        try:
            await bind_tenant(session, business_id)
            yield session
        finally:
            # Clear the session variable before the connection goes back to the pool —
            # otherwise the next request could inherit this tenant's RLS context.
            await session.rollback()
            await clear_tenant(session)
            reset_tenant()


async def dispose_engine() -> None:
    await engine.dispose()


def sync_engine() -> Any:
    """Synchronous engine for Alembic migrations."""
    from sqlalchemy import create_engine

    url = str(_settings.database_url).replace("postgresql+asyncpg://", "postgresql://")
    return create_engine(url, pool_pre_ping=True)
