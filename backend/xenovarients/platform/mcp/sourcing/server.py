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
from xenovarients.platform.mcp import external
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

    demand = await _live_demand(chosen, geo=geo.upper(), timeframe=timeframe)
    if demand.get("reason") == "source_unavailable":
        return result(
            available=False,
            field="demand",
            reason="source_unavailable",
            detail=demand.get("detail"),
            keyword=chosen,
            cached=False,
        )

    return result(
        keyword=chosen,
        geo=geo.upper(),
        timeframe=timeframe,
        demand=demand,
        data_as_of=datetime.now(UTC).isoformat(),
        cached=False,
        persisted=False,
    )


@read_only(server)
async def get_enriched_demand(
    ctx: Context,
    keyword: str | None = None,
    geo: str = "BD",
    timeframe: str = "today 5-y",
    refresh: bool = False,
) -> dict[str, Any]:
    """Demand for a keyword: the captured Trends reading plus an optional second source.

    By default ``demand`` is the stored snapshot, so the answer matches what the business
    last saw. ``refresh: true`` fetches Google Trends live and still stores nothing.
    ``enrichment`` is the third-party demand source's own answer, or ``available: false``
    with the reason — the cached reading stands alone when that source is absent.
    """
    principal = await authenticate(ctx, roles=STAFF_ROLES)
    chosen = (keyword or "").strip().lower()
    demand: dict[str, Any]
    stored_demand: Any = None
    captured_at: str | None = None
    expires_at: str | None = None

    async with tenant_session(principal.business_id) as session:
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
                    "demand",
                    "no_keyword",
                    detail="Pass a keyword, or save a product idea in Onboarding first.",
                )
            )

        if not refresh:
            snapshot = await session.scalar(
                select(MarketSnapshot)
                .where(
                    MarketSnapshot.business_id == principal.business_id,
                    MarketSnapshot.keyword == chosen,
                )
                .order_by(MarketSnapshot.captured_at.desc())
                .limit(1)
            )
            if snapshot is not None:
                captured_at = iso(snapshot.captured_at)
                expires_at = iso(snapshot.expires_at)
                stored_demand = dict(snapshot.payload).get("demand")

    if refresh:
        demand = await _live_demand(chosen, geo=geo.upper(), timeframe=timeframe)
        demand_source = "live"
    elif stored_demand is None:
        demand = unavailable(
            "demand",
            "no_research_yet",
            detail="No research has been captured for this keyword yet.",
        )
        demand_source = None
    else:
        demand = stored_demand
        demand_source = "cached"

    return result(
        keyword=chosen,
        geo=geo.upper(),
        timeframe=timeframe,
        demand=demand,
        demand_source=demand_source,
        enrichment=await external.call(
            "demand_signal",
            "get_enriched_demand",
            {"keyword": chosen, "geo": geo.upper(), "timeframe": timeframe},
        ),
        captured_at=captured_at,
        expires_at=expires_at,
        cached=demand_source == "cached",
        persisted=False,
    )


async def _live_demand(keyword: str, *, geo: str, timeframe: str) -> dict[str, Any]:
    """One live Google Trends read, with its quality panel; never stored."""
    try:
        series = await fetch_trends(keyword, geo=geo, timeframe=timeframe)
    except (MarketSourceError, httpx.HTTPError) as exc:
        return {"available": False, "reason": "source_unavailable", "detail": str(exc)}

    demand = metrics.demand_metrics(series)
    quality = metrics.panel_quality(
        available=bool(demand.get("available")),
        sample=len(demand.get("series") or []),
        min_sample=metrics.MIN_SAMPLE["demand"],
        direct=False,
    )
    return {**demand, "quality": quality}
