"""Tenancy and auth models."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from xenovarients.db.base import Base, TenantExemptMixin, TimestampMixin


class Role(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    staff = "staff"


class Business(Base, TimestampMixin):
    """Tenant root. Every other tenant-scoped record hangs off business_id."""

    __tablename__ = "businesses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Dhaka")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BDT")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON(), default=dict, server_default="{}")
    # Per-business secret used to verify inbound webhooks. The webhook URL carries
    # the business id, so the receiver can look the secret up and route the event to
    # the right tenant without an auth header.
    webhook_secret: Mapped[str] = mapped_column(String(255), nullable=False, default="")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BusinessMembership(Base, TenantExemptMixin, TimestampMixin):
    """A user's role within one business.

    Tenant-exempt: this table maps a user to their businesses, so it must be readable
    before a tenant is chosen. Its ``(business_id, user_id)`` unique constraint and the
    authenticated-user-only access path are the guards.
    """

    __tablename__ = "business_memberships"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "user_id", name="uq_business_memberships_business_id_user_id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=Role.staff.value)


class RevokedToken(Base, TimestampMixin):
    """Logout denylist, keyed on the JWT ``jti``.

    Access tokens are stateless, so signing them out server-side needs a record of
    what has been invalidated. The ``jti`` is unique per token, which makes the
    revocation itself idempotent. Rows expire with the token they name — the
    ``expires_at`` column lets a cleanup job delete them once they are worthless.
    """

    __tablename__ = "revoked_tokens"
    __table_args__ = (UniqueConstraint("jti", name="uq_revoked_tokens_jti"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    jti: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditLog(Base, TimestampMixin):
    """Immutable activity log. A DB trigger blocks UPDATE and DELETE.

    The ``business_id`` FK is ``RESTRICT``, not ``CASCADE``: the trigger forbids
    DELETE on this table, so a cascading delete would fail anyway. RESTRICT states the
    real rule — a business with audit history cannot be hard-deleted. Businesses are
    deactivated, not deleted.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    before_hash: Mapped[str | None] = mapped_column(String(64))
    after_hash: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON(), default=dict, server_default="{}")
    ip_address: Mapped[str | None] = mapped_column(String(45))
