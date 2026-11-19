import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.api.deps import Principal, get_principal, get_tenant_session
from xenovarients.models.sourcing import (
    MarketSnapshot,
    SourcingCartListing,
    SourcingProfile,
    TrackedProduct,
)
from xenovarients.platform.market import run_research
from xenovarients.platform.onboarding import (
    MAX_LENGTHS,
    STEPS,
    Step,
    closing,
    is_usable,
    line,
    next_step,
    parse_budget,
    parse_channels,
    reask_line,
)

router = APIRouter(prefix="/api/v1/sourcing", tags=["sourcing"])


class ProfileIn(BaseModel):
    business_type: str | None = None
    location: str | None = None
    product_idea: str | None = None
    investment_budget: Decimal | None = Field(default=None, ge=0)
    team_size: str | None = None
    account_type: str | None = None
    experience: str | None = None
    sales_channels: list[str] = []


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_type: str | None
    location: str | None
    product_idea: str | None
    investment_budget: Decimal | None
    team_size: str | None
    account_type: str | None
    experience: str | None
    sales_channels: list[str]


class TrackIn(BaseModel):
    keyword: str = Field(min_length=1, max_length=255)


class CartListingIn(BaseModel):
    listing_id: str = Field(min_length=1, max_length=255)
    marketplace: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1)
    unit_price: Decimal | None = Field(default=None, ge=0)
    currency: str = "BDT"
    shipping_estimate: str | None = None


class CartListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    listing_id: str
    marketplace: str
    title: str
    unit_price: Decimal | None
    currency: str
    shipping_estimate: str | None


class ResearchIn(BaseModel):
    keyword: str | None = Field(default=None, max_length=255)


class OnboardingAnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=1000)


class OnboardingStepOut(BaseModel):
    complete: bool
    field: str | None
    prompt: str
    options: list[str]
    progress: int
    total: int
    profile: ProfileOut | None


# The onboarding lines are written, not generated. A local model asked to rephrase
# them reliably drops the acknowledgment and asks a generic question instead ("Great!
# Where will you be listing your products?"), which is exactly what made onboarding
# read like a form. The script reacts to the answer every time, is instant, and cannot
# invent a question about a field that does not exist.


def _out(
    profile: SourcingProfile | None,
    *,
    prompt: str,
    index: int,
    step: Step | None,
) -> OnboardingStepOut:
    """One onboarding step as the API returns it."""
    return OnboardingStepOut(
        complete=step is None,
        field=step.field if step is not None else None,
        prompt=prompt,
        options=list(step.options) if step is not None else [],
        progress=index,
        total=len(STEPS),
        profile=ProfileOut.model_validate(profile) if profile is not None else None,
    )


async def _get_profile(
    principal: Principal,
    session: AsyncSession,
) -> SourcingProfile | None:
    return await session.scalar(
        select(SourcingProfile).where(SourcingProfile.business_id == principal.business_id)
    )


@router.get("/onboarding", response_model=OnboardingStepOut)
async def get_onboarding_step(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> OnboardingStepOut:
    profile = await _get_profile(principal, session)
    index, step = next_step(profile)
    if step is None:
        return _out(profile, prompt=closing(profile), index=index, step=None)
    return _out(profile, prompt=line(profile), index=index, step=step)


@router.post("/onboarding/answer", response_model=OnboardingStepOut)
async def answer_onboarding_step(
    body: OnboardingAnswerIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> OnboardingStepOut:
    profile = await _get_profile(principal, session)
    if profile is None:
        profile = SourcingProfile(
            business_id=principal.business_id,
            user_id=principal.user_id,
            sales_channels=[],
        )
        session.add(profile)
        await session.flush()

    index, step = next_step(profile)
    if step is None:
        await session.commit()
        return _out(profile, prompt=closing(profile), index=index, step=None)

    answer = body.answer.strip()
    if step.field == "investment_budget":
        amount = parse_budget(answer)
        if amount is None:
            # Stay on the question and say it the way a person would, rather than
            # answering a chat message with a 400 and a form error.
            return _out(profile, prompt=reask_line(step.field), index=index, step=step)
        setattr(profile, step.field, amount)
    elif step.field == "sales_channels":
        channels = parse_channels(answer)
        if not channels:
            return _out(profile, prompt=reask_line(step.field), index=index, step=step)
        setattr(profile, step.field, channels)
    else:
        # A greeting or a stray word is not an answer to "where are you selling
        # from?" — stay on the question instead of recording it and echoing it back.
        if not is_usable(step.field, answer):
            return _out(profile, prompt=reask_line(step.field), index=index, step=step)
        setattr(profile, step.field, answer[: MAX_LENGTHS.get(step.field, 255)])

    await session.commit()
    await session.refresh(profile)
    index, upcoming = next_step(profile)
    if upcoming is None:
        return _out(profile, prompt=closing(profile), index=index, step=None)
    return _out(
        profile,
        prompt=line(profile, answered=step.field),
        index=index,
        step=upcoming,
    )


@router.get("/dashboard")
async def dashboard(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, int | str | None]:
    profile = await session.scalar(
        select(SourcingProfile).where(SourcingProfile.business_id == principal.business_id)
    )
    tracked_count = len((await session.execute(select(TrackedProduct.id))).all())
    cart_count = len((await session.execute(select(SourcingCartListing.id))).all())
    return {
        "tracked_product_count": tracked_count,
        "saved_landed_cost": None,
        "net_financial_result": None,
        "next_action": "Open onboarding" if profile is None else "Research",
        "cart_count": cart_count,
    }


def _snapshot_payload(snapshot: MarketSnapshot, *, cached: bool) -> dict[str, Any]:
    payload = dict(snapshot.payload)
    payload["snapshot_id"] = str(snapshot.id)
    payload["cached"] = cached
    payload["stale"] = snapshot.expires_at <= datetime.now(UTC)
    return payload


@router.get("/research/latest")
async def latest_research(
    keyword: str | None = None,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, Any] | None:
    """The newest snapshot for a keyword, so a revisit is free.

    Nothing is recomputed here: this returns exactly what was captured, with its
    original ``captured_at`` and quality score, or ``None`` when nothing was run.
    """
    profile = await _get_profile(principal, session)
    chosen = (keyword or (profile.product_idea if profile else None) or "").strip()
    if not chosen:
        return None
    snapshot = await session.scalar(
        select(MarketSnapshot)
        .where(MarketSnapshot.keyword == chosen.lower())
        .order_by(MarketSnapshot.captured_at.desc())
        .limit(1)
    )
    if snapshot is None:
        return None
    return _snapshot_payload(snapshot, cached=True)


@router.post("/research")
async def run_market_research(
    body: ResearchIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, Any]:
    """Read the free sources, compute the metrics, store and return one snapshot."""
    profile = await _get_profile(principal, session)
    keyword = (body.keyword or (profile.product_idea if profile else None) or "").strip()
    if not keyword:
        raise HTTPException(
            status_code=400,
            detail="Save a product idea in Onboarding first.",
        )
    payload = await run_research(keyword)
    snapshot = MarketSnapshot(
        business_id=principal.business_id,
        user_id=principal.user_id,
        keyword=keyword.lower(),
        captured_at=datetime.fromisoformat(payload["captured_at"]),
        expires_at=datetime.fromisoformat(payload["expires_at"]),
        quality_score=int(payload["quality"]["score"]),
        payload=payload,
    )
    session.add(snapshot)
    await session.commit()
    await session.refresh(snapshot)
    return _snapshot_payload(snapshot, cached=False)


@router.get("/profile", response_model=ProfileOut | None)
async def get_profile(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> SourcingProfile | None:
    return await session.scalar(
        select(SourcingProfile).where(SourcingProfile.business_id == principal.business_id)
    )


@router.put("/profile", response_model=ProfileOut)
async def save_profile(
    body: ProfileIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> SourcingProfile:
    profile = await session.scalar(
        select(SourcingProfile).where(SourcingProfile.business_id == principal.business_id)
    )
    if profile is None:
        profile = SourcingProfile(
            business_id=principal.business_id,
            user_id=principal.user_id,
        )
        session.add(profile)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    await session.commit()
    await session.refresh(profile)
    return profile


@router.post("/products")
async def track_product(
    body: TrackIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, str]:
    keyword = body.keyword.strip().lower()
    existing = await session.scalar(
        select(TrackedProduct).where(
            TrackedProduct.business_id == principal.business_id,
            TrackedProduct.keyword == keyword,
        )
    )
    if existing is None:
        session.add(
            TrackedProduct(
                business_id=principal.business_id,
                user_id=principal.user_id,
                keyword=keyword,
            )
        )
        await session.commit()
    return {"keyword": keyword}


@router.get("/cart", response_model=list[CartListingOut])
async def list_cart(
    session: AsyncSession = Depends(get_tenant_session),
) -> list[SourcingCartListing]:
    rows = await session.execute(
        select(SourcingCartListing).order_by(SourcingCartListing.created_at)
    )
    return list(rows.scalars())


@router.post("/cart", response_model=CartListingOut)
async def add_cart_listing(
    body: CartListingIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> SourcingCartListing:
    listing = await session.scalar(
        select(SourcingCartListing).where(SourcingCartListing.listing_id == body.listing_id)
    )
    if listing is None:
        listing = SourcingCartListing(
            business_id=principal.business_id,
            user_id=principal.user_id,
            listing_id=body.listing_id,
            marketplace=body.marketplace,
            title=body.title,
            unit_price=body.unit_price,
            currency=body.currency,
            shipping_estimate=body.shipping_estimate,
        )
        session.add(listing)
        await session.commit()
        await session.refresh(listing)
    return listing


@router.delete("/cart/{listing_id}", status_code=204)
async def remove_cart_listing(
    listing_id: str,
    session: AsyncSession = Depends(get_tenant_session),
) -> None:
    listing = await session.scalar(
        select(SourcingCartListing).where(SourcingCartListing.listing_id == listing_id)
    )
    if listing is not None:
        await session.delete(listing)
        await session.commit()
