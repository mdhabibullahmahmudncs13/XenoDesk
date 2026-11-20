"""Request dependencies: authentication, role checks and the tenant-bound session.

The chain is deliberate:

    get_current_user  → resolves the bearer token to a User
    require_role      → checks the membership role for the active business
    get_tenant_session → yields a session that filters by that business

``business_id`` is only ever read from the verified token. A body or query parameter
carrying ``business_id`` is rejected by the schemas.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.api.errors import Forbidden, Unauthorized
from xenovarients.core.security import decode_access_token
from xenovarients.db.session import SessionLocal
from xenovarients.db.tenant import bind_tenant, clear_tenant, install_tenant_filter, reset_tenant
from xenovarients.models.tenancy import BusinessMembership, RevokedToken, Role, User


@dataclass(frozen=True)
class Principal:
    """The authenticated caller and the tenant they are acting in."""

    user_id: uuid.UUID
    business_id: uuid.UUID
    role: str

    def has_role(self, *roles: str) -> bool:
        return self.role in roles


async def resolve_user(authorization: str | None) -> User:
    """Turn a raw ``Authorization`` header into the user it names.

    Kept separate from the dependency so the MCP servers can authenticate a tool call
    from the request headers without going through FastAPI's injection.
    """
    if not authorization:
        raise Unauthorized("Missing Authorization header.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("Authorization header must be 'Bearer <token>'.")
    try:
        claims = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid or expired access token.") from exc

    subject = claims.get("sub")
    if not subject:
        raise Unauthorized("Access token has no subject.")
    try:
        user_id = uuid.UUID(subject)
    except ValueError as exc:
        raise Unauthorized("Access token subject is not a valid id.") from exc

    # No tenant is set here, so this query is not tenant-filtered — it reads the
    # global users table, which is correct: the user is not a tenant-scoped resource.
    async with SessionLocal() as session:
        install_tenant_filter(session)
        try:
            user = await session.get(User, user_id)
            if user is not None:
                jti = claims.get("jti")
                if jti:
                    revoked = await session.scalar(
                        select(RevokedToken).where(RevokedToken.jti == jti)
                    )
                    if revoked is not None:
                        raise Unauthorized("Access token has been revoked.")
        finally:
            reset_tenant()
    if user is None:
        raise Unauthorized("User no longer exists.")
    if not user.is_active:
        raise Unauthorized("User account is inactive.")
    return user


async def get_current_user(
    authorization: str | None = Header(default=None),
) -> User:
    return await resolve_user(authorization)


async def _principal_for_user(user: User, x_business_id: str | None) -> Principal:
    """The caller's role in the selected business."""
    business_id = None
    if x_business_id:
        try:
            business_id = uuid.UUID(x_business_id)
        except ValueError as exc:
            raise Forbidden("X-Business-Id is not a valid business id.") from exc

    async with SessionLocal() as session:
        install_tenant_filter(session)
        try:
            stmt = BusinessMembership.__table__.select().where(
                BusinessMembership.user_id == user.id
            )
            if business_id is not None:
                stmt = stmt.where(BusinessMembership.business_id == business_id)
            rows = (await session.execute(stmt)).mappings().all()
        finally:
            reset_tenant()

    if not rows:
        raise Forbidden("You do not belong to this business.")
    if len(rows) > 1:
        raise Forbidden(
            "This account belongs to multiple businesses. "
            "Send the X-Business-Id header to select one."
        )
    row = rows[0]
    return Principal(
        user_id=user.id,
        business_id=row["business_id"],
        role=row["role"],
    )


async def resolve_principal(
    *,
    authorization: str | None,
    x_business_id: str | None,
) -> Principal:
    """Authenticate from raw header values, for callers outside the dependency graph.

    This is the same chain the HTTP API uses: token → user → membership → role. The MCP
    servers use it so a tool call is held to exactly the API's tenant and role checks.
    """
    user = await resolve_user(authorization)
    return await _principal_for_user(user, x_business_id)


async def get_principal(
    user: User = Depends(get_current_user),
    x_business_id: str | None = Header(default=None, alias="X-Business-Id"),
) -> Principal:
    """Resolve the tenant for this request and the caller's role in it.

    ``X-Business-Id`` may select a business the user belongs to (multi-tenant users).
    If absent, the user's single membership is used. The role is always read from
    ``business_memberships`` — never from the token, so a revoked role takes effect
    immediately rather than at token expiry.
    """
    return await _principal_for_user(user, x_business_id)


async def get_tenant_session(
    principal: Principal = Depends(get_principal),
) -> AsyncIterator[AsyncSession]:
    """A session whose every tenant-scoped query is filtered to the caller's business."""
    business_id = str(principal.business_id)
    async with SessionLocal() as session:
        install_tenant_filter(session)
        try:
            # Binds both isolation layers: the ORM filter and the Postgres RLS session variable.
            await bind_tenant(session, business_id)
            yield session
        finally:
            # Clear the session variable before the connection returns to the pool.
            await session.rollback()
            await clear_tenant(session)
            reset_tenant()


def require_role(*roles: str) -> Callable[..., Awaitable[Principal]]:
    """Dependency factory: the caller must hold one of ``roles`` in the active business."""

    async def _dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in roles:
            raise Forbidden(
                f"This action requires role: {', '.join(roles)}.",
                extra={"required_roles": list(roles), "actual_role": principal.role},
            )
        return principal

    return _dependency


require_owner = require_role(Role.owner.value)
require_admin = require_role(Role.owner.value, Role.admin.value)
require_staff = require_role(Role.owner.value, Role.admin.value, Role.staff.value)
