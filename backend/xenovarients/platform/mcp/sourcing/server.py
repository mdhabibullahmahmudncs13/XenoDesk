"""Read-only Market Intelligence tools: cached market readings and a live demand refresh.

``get_market_prices`` returns the stored snapshot exactly as it was captured — no
recomputation, so a stale reading is visibly stale rather than silently refreshed.
``refresh_demand`` asks Google Trends again but **stores nothing**: persisting a snapshot
is the sourcing screen's job, and the snapshot is the business's record of what it saw.
"""

from datetime import UTC, datetime
from typing import Any

import httpx
from mcp.server.mcpserver import Context
from sqlalchemy import select

from xenovarients.models.sourcing import MarketSnapshot, SourcingProfile
from xenovarients.platform.market import metrics
from xenovarients.platform.market.daraz import MarketSourceError
from xenovarients.platform.market.trends import fetch_trends
from xenovarients.platform.mcp.shared import (
    STAFF_ROLES,
    authenticate,
    build_server,
    iso,
    read_only,
    result,
    tenant_session,
    unavailable,
)

server = build_server(
    name="sourcing",
    title="XenoDesk Market Intelligence",
    instructions=(
        "Read-only answers from Market Intelligence: the latest captured price, "
        "competition and demand reading for a keyword, and a live demand refresh that is "
        "not stored. Nothing here writes a snapshot."
    ),
)


@read_only(server)
async def get_market_prices(
    ctx: Context,
    keyword: str | None = None,
) -> dict[str, Any]:
    """The latest captured market reading for a keyword, exactly as it was stored.

    With no keyword, the sourcing profile's product idea is used. If neither exists there
    is no reading — the answer is ``available: false`` with the reason, not zeros.
    """
    principal = await authenticate(ctx, roles=STAFF_ROLES)

    async with tenant_session(principal.business_id) as session:
        chosen = (keyword or "").strip().lower()
        if not chosen:
            chosen = (
                await session.scalar(
                    select(SourcingProfile.product_idea).where(
                        SourcingProfile.business_id == principal.business_id
                    )
                )
                or ""
            ).strip().lower()
        if not chosen:
            return result(
                **unavailable(
                    "market_prices",
                    "no_keyword",
                    detail="Pass a keyword, or save a product idea in Onboarding first.",
                )
            )

        snapshot = await session.scalar(
            select(MarketSnapshot)
            .where(
                MarketSnapshot.business_id == principal.business_id,
                MarketSnapshot.keyword == chosen,
            )
            .order_by(MarketSnapshot.captured_at.desc())
            .limit(1)
        )
        if snapshot is None:
            return result(
                **unavailable(
                    "market_prices",
                    "no_research_yet",
                    keyword=chosen,
                    detail="No research has been captured for this keyword yet.",
                )
            )

        payload = dict(snapshot.payload)
        payload["snapshot_id"] = str(snapshot.id)
        payload["cached"] = True
        payload["captured_at"] = iso(snapshot.captured_at)
        payload["expires_at"] = iso(snapshot.expires_at)
        payload["stale"] = snapshot.expires_at <= datetime.now(UTC)

    return result(
        keyword=payload.get("keyword", chosen),
        prices=payload.get("prices"),
        competition=payload.get("competition"),
        demand=payload.get("demand"),
        quality=payload.get("quality"),
        risks=payload.get("risks"),
        sources=payload.get("sources"),
        method=payload.get("method"),
        snapshot_id=payload["snapshot_id"],
        captured_at=payload["captured_at"],
        expires_at=payload["expires_at"],
        stale=payload["stale"],
        cached=True,
    )


@read_only(server)
async def refresh_demand(
    ctx: Context,
    keyword: str,
    geo: str = "BD",
    timeframe: str = "today 5-y",
) -> dict[str, Any]:
    """Fetch the live Google Trends series for a keyword and compute demand metrics.

    Nothing is persisted (``cached: false``): this is a fresh reading for a question, not
    a new snapshot. A source failure is reported as ``available: false`` with its reason.
    """
    await authenticate(ctx, roles=STAFF_ROLES)
    chosen = keyword.strip()
    if not chosen:
        return result(available=False, field="demand", reason="no_keyword")

    try:
        series = await fetch_trends(chosen, geo=geo.upper(), timeframe=timeframe)
    except (MarketSourceError, httpx.HTTPError) as exc:
        return result(
            available=False,
            field="demand",
            reason="source_unavailable",
            detail=str(exc),
            keyword=chosen,
            cached=False,
        )

    demand = metrics.demand_metrics(series)
    quality = metrics.panel_quality(
        available=bool(demand.get("available")),
        sample=len(demand.get("series") or []),
        min_sample=metrics.MIN_SAMPLE["demand"],
        direct=False,
    )
    return result(
        keyword=chosen,
        geo=geo.upper(),
        timeframe=timeframe,
        demand={**demand, "quality": quality},
        data_as_of=datetime.now(UTC).isoformat(),
        cached=False,
        persisted=False,
    )
