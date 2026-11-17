"""Authentication endpoints.

Login resolves the email to a user, verifies the password, then loads the caller's
membership. A user with exactly one membership gets that business; a user with several
must pick one with ``X-Business-Id`` on a later request.
"""

import uuid
from datetime import UTC, datetime

import jwt
from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.api.deps import (
    Principal,
    get_current_user,
    get_principal,
    get_tenant_session,
)
from xenovarients.api.errors import Conflict, Unauthorized
from xenovarients.core.config import get_settings
from xenovarients.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from xenovarients.db.session import SessionLocal
from xenovarients.db.tenant import install_tenant_filter, reset_tenant
from xenovarients.models.tenancy import Business, BusinessMembership, RevokedToken, User
from xenovarients.schemas.auth import (
    BusinessSummary,
    LoginRequest,
    MembershipResponse,
    MeResponse,
    SignupRequest,
    TokenResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _business_summary(business: Business) -> BusinessSummary:
    return BusinessSummary(
        id=business.id,
        name=business.name,
        timezone=business.timezone,
        currency=business.currency,
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, response: Response) -> TokenResponse:
    settings = get_settings()
    async with SessionLocal() as session:
        install_tenant_filter(session)
        try:
            result = await session.execute(select(User).where(User.email == payload.email.lower()))
            user = result.scalar_one_or_none()
            if user is None or not verify_password(payload.password, user.password_hash):
                # Same message either way — do not reveal whether the email exists.
                raise Unauthorized("Incorrect email or password.")
            if not user.is_active:
                raise Unauthorized("User account is inactive.")

            memberships = (
                await session.execute(
                    select(BusinessMembership, Business)
                    .join(Business, Business.id == BusinessMembership.business_id)
                    .where(BusinessMembership.user_id == user.id)
                )
            ).all()
            if not memberships:
                raise Unauthorized("This account is not a member of any business.")

            membership, business = memberships[0]
            if len(memberships) > 1:
                # Ambiguous without a business selector — the client asks, then retries.
                raise Unauthorized(
                    "This account belongs to multiple businesses. "
                    "Select one with the X-Business-Id header.",
                    extra={
                        "memberships": [
                            {
                                "business": _business_summary(b).model_dump(mode="json"),
                                "role": m.role,
                            }
                            for m, b in memberships
                        ]
                    },
                )

            user.last_login_at = datetime.now(UTC)
            await session.commit()
        finally:
            reset_tenant()

    token = create_access_token(user_id=user.id, business_id=business.id, role=membership.role)
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_ttl_minutes * 60,
        user_id=user.id,
        business_id=business.id,
        role=membership.role,
    )


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(payload: SignupRequest, response: Response) -> TokenResponse:
    """Create the first owner and business in one transaction."""
    settings = get_settings()
    async with SessionLocal() as session:
        install_tenant_filter(session)
        try:
            email = payload.email.lower()
            existing = await session.scalar(select(User).where(User.email == email))
            if existing is not None:
                raise Conflict("An account already exists for this email.")

            business = Business(name=payload.business_name.strip())
            user = User(
                email=email,
                name=payload.name.strip(),
                password_hash=hash_password(payload.password),
            )
            session.add_all([business, user])
            await session.flush()
            session.add(
                BusinessMembership(
                    business_id=business.id,
                    user_id=user.id,
                    role="owner",
                )
            )
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise Conflict("An account already exists for this email.") from exc
        finally:
            reset_tenant()

    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(
        access_token=create_access_token(
            user_id=user.id,
            business_id=business.id,
            role="owner",
        ),
        expires_in=settings.access_token_ttl_minutes * 60,
        user_id=user.id,
        business_id=business.id,
        role="owner",
    )


@router.get("/me", response_model=MeResponse)
async def me(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> MeResponse:
    business = await session.get(Business, principal.business_id)
    if business is None:
        raise Unauthorized("Business no longer exists.")
    return MeResponse(
        user_id=principal.user_id,
        email=await session.scalar(select(User.email).where(User.id == principal.user_id)) or "",
        name=await session.scalar(select(User.name).where(User.id == principal.user_id)) or "",
        role=principal.role,
        business=_business_summary(business),
    )


@router.post("/logout", status_code=204)
async def logout(authorization: str | None = Header(default=None)) -> Response:
    """Revoke the presented access token.

    The JWT is stateless, so logout records its ``jti`` in the denylist; every later
    request carrying that token is rejected. The row expires with the token it names,
    so the denylist does not grow without bound.

    This deliberately does not depend on ``get_current_user``: a token that is
    *already* revoked must still logout cleanly, or a client retrying after a dropped
    response would get a 401 it cannot act on. The user id comes from the claims.
    """
    if not authorization:
        raise Unauthorized("Missing Authorization header.")
    _, _, token = authorization.partition(" ")
    try:
        claims = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid or expired access token.") from exc

    jti = claims.get("jti")
    if not jti:
        raise Unauthorized("Access token has no id.")

    subject = claims.get("sub")
    try:
        user_id = uuid.UUID(subject) if subject else None
    except ValueError:
        user_id = None

    async with SessionLocal() as session:
        install_tenant_filter(session)
        try:
            existing = await session.scalar(select(RevokedToken).where(RevokedToken.jti == jti))
            if existing is None:
                expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
                session.add(RevokedToken(jti=jti, user_id=user_id, expires_at=expires_at))
                await session.commit()
        finally:
            reset_tenant()
    return Response(status_code=204)


@router.get("/memberships", response_model=list[MembershipResponse])
async def memberships(
    user: User = Depends(get_current_user),
) -> list[MembershipResponse]:
    """All businesses this user belongs to. Lets the client pick one."""
    async with SessionLocal() as session:
        install_tenant_filter(session)
        try:
            rows = (
                await session.execute(
                    select(BusinessMembership, Business)
                    .join(Business, Business.id == BusinessMembership.business_id)
                    .where(BusinessMembership.user_id == user.id)
                )
            ).all()
        finally:
            reset_tenant()
    return [MembershipResponse(business=_business_summary(b), role=m.role) for m, b in rows]
