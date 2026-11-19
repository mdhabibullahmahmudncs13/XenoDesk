"""Tenant isolation enforcement.

Two layers, deliberately:

1. **TenantFilter** (this file) — an ORM-level `do_orm_execute` hook that appends
   ``business_id = :bid`` to every SELECT/UPDATE/DELETE against a tenant-scoped model.
   If no tenant is in context it raises ``TenantScopeError`` rather than silently
   returning every tenant's rows.

2. **Postgres Row Level Security** — a database-level policy keyed on the
   ``app.business_id`` session variable. This catches anything that bypasses the ORM
   (raw SQL, a migration, a psql session).

The ORM layer gives a good error message; the RLS layer gives the actual guarantee.
"""

from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

from sqlalchemy import Delete, Update, event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_current_business_id: ContextVar[str | None] = ContextVar("current_business_id", default=None)


class TenantScopeError(RuntimeError):
    """Raised when a tenant-scoped query runs without a business in context."""


def set_tenant(business_id: str) -> None:
    """Set the tenant for the current task (ORM layer). Always pair with reset_tenant().

    This only affects the ORM filter. To also satisfy the Postgres RLS policies, the
    session variable ``app.business_id`` must be set on the connection — use
    :func:`bind_tenant` which does both, so the two layers cannot drift apart.
    """
    _current_business_id.set(business_id)


async def bind_tenant(session: Any, business_id: str) -> None:
    """Set the tenant on both layers: the ORM contextvar and the Postgres variable.

    The Postgres variable is re-applied at the start of *every* transaction by the
    ``after_begin`` listener (see :func:`_install`). A session holds one connection per
    transaction, and ``commit()`` returns that connection to the pool — so setting the
    variable once on whatever connection happens to be checked out is not enough. The
    next statement can run on a different pooled connection where the variable is
    unset, RLS then hides the tenant's rows, and a refresh or a follow-up read fails.
    Transaction scope (``set_config(..., true)``) means the value disappears together
    with the transaction instead of leaking onto a pooled connection.
    """
    _install(session)
    set_tenant(business_id)
    await session.execute(
        text("SELECT set_config('app.business_id', :b, true)"), {"b": str(business_id)}
    )


async def clear_tenant(session: Any) -> None:
    """Clear the Postgres variable on the current transaction, belt and braces."""
    await session.execute(text("SELECT set_config('app.business_id', '', true)"))


def reset_tenant() -> None:
    _current_business_id.set(None)


def get_tenant() -> str | None:
    return _current_business_id.get()


def require_tenant() -> str:
    business_id = _current_business_id.get()
    if business_id is None:
        raise TenantScopeError(
            "No tenant in context. A tenant-scoped query was attempted without a business_id. "
            "Use the `tenant_session` dependency or set_tenant() explicitly."
        )
    return business_id


def _is_tenant_scoped(entity: Any) -> bool:
    mapper = inspect(entity, raiseerr=False)
    if mapper is None:
        return False
    if getattr(mapper.class_, "__tenant_exempt__", False):
        return False
    return bool(getattr(mapper.class_, "__tenant_scoped__", False))


def _has_business_predicate(statement: Any, business_id: str) -> bool:
    """Whether the statement already filters on this business_id.

    The WHERE clause is not always a BooleanClauseList — a single ``column == value``
    is a bare BinaryExpression — so the clauses are collected defensively.
    """
    whereclause = statement.whereclause
    if whereclause is None:
        return False
    clauses = getattr(whereclause, "clauses", None)
    if clauses is None:
        clauses = [whereclause]
    for clause in clauses:
        right = getattr(clause, "right", None)
        if right is not None and getattr(right, "value", None) == business_id:
            return True
    return False


def _apply_tenant_predicate(statement: Any, business_id: str) -> Any:
    """Add the business_id predicate to a statement if it is not already present."""
    if isinstance(statement, (Update, Delete)):
        # An UPDATE or DELETE carries its target table directly; there is no FROM clause.
        if _has_business_predicate(statement, business_id):
            return statement
        return statement.where(statement.table.c.business_id == business_id)
    # SELECT
    froms = statement.get_final_froms()
    if not froms:
        return statement
    for from_ in froms:
        if "business_id" in from_.c:
            if not _has_business_predicate(statement, business_id):
                statement = statement.where(from_.c.business_id == business_id)
            break
    return statement


def _install(session: Any) -> None:
    if getattr(session, "_tenant_filter_installed", False):
        return

    # ``do_orm_execute`` is a synchronous-only event; on an AsyncSession the listener
    # must be attached to the underlying sync_session.
    target = session.sync_session if hasattr(session, "sync_session") else session

    @event.listens_for(target, "after_begin")
    def _tenant_on_new_transaction(
        session: Any, transaction: Any, connection: Any
    ) -> None:
        # Every transaction in a tenant session is bound, not just the first one: after a
        # commit the session may check out a different pooled connection, and without
        # the variable the RLS policies hide the tenant's own rows.
        business_id = get_tenant()
        if business_id is None:
            return
        connection.execute(
            text("SELECT set_config('app.business_id', :b, true)"), {"b": business_id}
        )

    @event.listens_for(target, "do_orm_execute")
    def _tenant_filter(execute_state: Any) -> None:
        if (
            not execute_state.is_select
            and not execute_state.is_update
            and not execute_state.is_delete
        ):
            return

        statement = execute_state.statement
        entity = execute_state.bind_mapper
        if entity is None or not _is_tenant_scoped(entity):
            return

        business_id = require_tenant()
        execute_state.statement = _apply_tenant_predicate(statement, business_id)

    session._tenant_filter_installed = True


def install_tenant_filter(session: AsyncSession | Session) -> None:
    _install(session)


def tenant_scoped_iter(stmt: Any) -> Iterator[Any]:
    """Helper for building statements that are safe to execute outside a tenant session."""
    yield stmt
