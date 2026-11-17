"""Creator Commerce ad intelligence, own-ad performance, and collaboration views."""

import base64
import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xenovarients.api.deps import Principal, get_tenant_session, require_admin, require_owner
from xenovarients.api.errors import BadRequest, NotFound
from xenovarients.core.config import get_settings
from xenovarients.models.ads import AdAccountConnection, AdInsightSnapshot, CollaborationSuggestion
from xenovarients.platform.ads import (
    is_stale,
    metrics_with_unavailable_reasons,
    passes_guard,
    rank_own_ads,
)

router = APIRouter(prefix="/api/v1/creator-commerce", tags=["creator-commerce"])


def _cipher() -> Fernet:
    key = hashlib.sha256(get_settings().jwt_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


class AdOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    advertiser_name: str | None
    ad_url: str | None
    creative: dict[str, Any]
    score: float | None
    score_breakdown: dict[str, Any] | None
    source_tier: str


class OwnAdOut(BaseModel):
    id: uuid.UUID
    ad_id: str | None
    objective: str | None
    metrics: dict[str, Any]
    synced_at: datetime
    stale: bool
    eligible: bool


class ConnectionIn(BaseModel):
    external_account_id: str
    account_name: str | None = None
    access_token: str = Field(min_length=1)


class ConnectionOut(BaseModel):
    id: uuid.UUID
    provider: str
    external_account_id: str
    account_name: str | None
    scopes: list[str]


class SuggestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    name: str
    platform: str | None
    niche: str | None
    location: str | None
    audience_metric: dict[str, Any] | None
    contact_route: str | None
    match_reasons: dict[str, Any]
    is_verified: bool


@router.get("/ads/intelligence")
async def list_ad_intelligence(
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
    keyword: str = Query(default=""),
    country: str = Query(default="BD"),
    limit: int = Query(default=5, ge=1, le=50),
) -> list[AdOut]:
    rows = (
        await session.execute(
            select(AdInsightSnapshot)
            .where(
                AdInsightSnapshot.business_id == principal.business_id,
                AdInsightSnapshot.scope == "competitor",
            )
            .order_by(
                AdInsightSnapshot.score.desc().nullslast(),
                AdInsightSnapshot.synced_at.desc(),
            )
            .limit(limit)
        )
    ).scalars()
    result = []
    for row in rows:
        creative = dict(row.creative or {})
        creative.setdefault("visible_price", "Not visible")
        creative.setdefault("copy", "Not available")
        result.append(
            AdOut(
                id=row.id,
                advertiser_name=row.advertiser_name,
                ad_url=row.ad_url,
                creative=creative,
                score=float(row.score) if row.score is not None else None,
                score_breakdown=row.score_breakdown,
                source_tier=row.source_tier,
            )
        )
    return result


@router.post("/ads/own/connections", response_model=ConnectionOut)
async def connect_own_ad_account(
    body: ConnectionIn,
    principal: Principal = Depends(require_owner),
    session: AsyncSession = Depends(get_tenant_session),
) -> ConnectionOut:
    if body.external_account_id.strip() == "":
        raise BadRequest("external_account_id is required.")
    connection = AdAccountConnection(
        business_id=principal.business_id,
        provider="meta",
        external_account_id=body.external_account_id,
        account_name=body.account_name,
        scopes=["ads_read"],
        access_token_encrypted=_cipher().encrypt(body.access_token.encode()).decode(),
        connected_by_user_id=principal.user_id,
    )
    session.add(connection)
    await session.commit()
    return ConnectionOut.model_validate(connection, from_attributes=True)


@router.get("/ads/own/performance")
async def list_own_ad_performance(
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
    objective: str = Query(default="sales"),
    since: datetime | None = Query(default=None),
) -> list[OwnAdOut]:
    statement = select(AdInsightSnapshot).where(
        AdInsightSnapshot.business_id == principal.business_id,
        AdInsightSnapshot.scope == "own",
        AdInsightSnapshot.objective == objective,
    )
    if since is not None:
        statement = statement.where(AdInsightSnapshot.synced_at >= since)
    snapshots = list((await session.execute(statement)).scalars().all())
    try:
        ranked = rank_own_ads(snapshots, objective=objective)
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc
    now = datetime.now(UTC)
    return [
        OwnAdOut(
            id=row.id,
            ad_id=row.ad_id,
            objective=row.objective,
            metrics=metrics_with_unavailable_reasons(row.metrics or {}),
            synced_at=row.synced_at,
            stale=is_stale(row.synced_at, now=now),
            eligible=passes_guard(row.metrics or {}, objective=objective, min_spend=1),
        )
        for row in ranked
    ]


@router.get("/collaborations")
async def list_collaborations(
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
    kind: str | None = Query(default=None),
) -> list[SuggestionOut]:
    statement = select(CollaborationSuggestion).where(
        CollaborationSuggestion.business_id == principal.business_id
    )
    if kind is not None:
        statement = statement.where(CollaborationSuggestion.kind == kind)
    rows = (await session.execute(statement.order_by(CollaborationSuggestion.name))).scalars()
    return [SuggestionOut.model_validate(row, from_attributes=True) for row in rows]


@router.get("/influencers")
async def list_influencers(
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[SuggestionOut]:
    if not get_settings().influencer_suggestions_enabled:
        raise NotFound("Influencer suggestions are disabled.")
    rows = (
        await session.execute(
            select(CollaborationSuggestion)
            .where(
                CollaborationSuggestion.business_id == principal.business_id,
                CollaborationSuggestion.kind == "influencer",
            )
            .order_by(CollaborationSuggestion.name)
        )
    ).scalars()
    return [SuggestionOut.model_validate(row, from_attributes=True) for row in rows]
