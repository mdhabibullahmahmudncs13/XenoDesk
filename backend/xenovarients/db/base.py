"""Declarative base and the tenant-scoped mixin.

Every tenant-scoped model sets ``__tenant_scoped__ = True`` (via TenantScopedMixin). The
TenantFilter event listener in ``db/tenant.py`` appends a business_id predicate to every
statement touching such a model, and raises if no tenant is in context.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TenantScopedMixin:
    """Marks a model as tenant-scoped. The TenantFilter enforces the predicate."""

    __tenant_scoped__ = True


class TenantExemptMixin:
    """Marks a model that maps *between* tenants and so cannot be tenant-filtered.

    ``business_memberships`` is the only such table: a user may belong to several
    businesses and must be able to enumerate their own memberships before any tenant
    has been selected. It is protected by its ``(business_id, user_id)`` unique
    constraint and by the fact that it is only ever read for the authenticated user.
    """

    __tenant_exempt__ = True


class UUIDPrimaryKeyMixin:
    id: Mapped[Any] = mapped_column(primary_key=True)
