"""Runs one Market Intelligence pass over the free sources.

The orchestrator only gathers and assembles: all arithmetic lives in ``metrics.py``.
A source that fails leaves its panel ``available: False`` with the reason, and the
other panels still render — a dead provider must not blank the screen.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from xenovarients.platform.market import metrics
from xenovarients.platform.market.daraz import fetch_listings
from xenovarients.platform.market.trends import fetch_trends
from xenovarients.platform.market.types import MarketListing, TrendSeries

SNAPSHOT_TTL_HOURS = 12


def _source(
    source_id: str,
    label: str,
    status: str,
    detail: str,
    url: str,
) -> dict[str, str]:
    return {
        "id": source_id,
        "label": label,
        "status": status,
        "detail": detail,
        "url": url,
    }


async def run_research(keyword: str) -> dict[str, Any]:
    """Collect, compute and assemble one snapshot payload."""
    keyword = keyword.strip()
    now = datetime.now(UTC)

    trend_result, listing_result = await asyncio.gather(
        fetch_trends(keyword),
        fetch_listings(keyword),
        return_exceptions=True,
    )

    trend: TrendSeries | None = (
        trend_result if isinstance(trend_result, TrendSeries) else None
    )
    listings: tuple[MarketListing, ...] = ()
    if isinstance(listing_result, tuple):
        listings = listing_result

    trend_error = (
        str(trend_result)
        if isinstance(trend_result, BaseException)
        else None
    )
    listing_error = (
        str(listing_result)
        if isinstance(listing_result, BaseException)
        else None
    )

    demand = (
        metrics.demand_metrics(trend)
        if trend is not None
        else metrics.unavailable(trend_error or "Google Trends unavailable.")
    )
    competition = (
        metrics.competition_metrics(listings)
        if listings
        else metrics.unavailable(listing_error or "No marketplace readings.")
    )
    prices = (
        metrics.price_metrics(listings)
        if listings
        else metrics.unavailable(listing_error or "No marketplace readings.")
    )
    if competition.get("available"):
        competition.pop("_top_seller_id", None)

    demand_quality = metrics.panel_quality(
        available=bool(demand.get("available")),
        sample=len(demand.get("series") or []),
        min_sample=metrics.MIN_SAMPLE["demand"],
        direct=False,
    )
    competition_quality = metrics.panel_quality(
        available=bool(competition.get("available")),
        sample=len(listings),
        min_sample=metrics.MIN_SAMPLE["competition"],
        direct=True,
    )
    price_quality = metrics.panel_quality(
        available=bool(prices.get("available")),
        sample=int(prices.get("sample") or 0),
        min_sample=metrics.MIN_SAMPLE["prices"],
        direct=True,
    )
    quality = metrics.overall_quality(demand_quality, competition_quality, price_quality)

    sources = [
        _source(
            "google_trends",
            "Google Trends",
            "ok" if trend is not None else "failed",
            (
                f"{len(demand.get('series') or [])} months of relative interest, geo BD"
                if trend is not None
                else (trend_error or "No response.")
            ),
            trend.source_url
            if trend is not None and trend.source_url
            else "https://trends.google.com/trends/explore?geo=BD",
        ),
        _source(
            "daraz_bd",
            "Daraz Bangladesh",
            "ok" if listings else "failed",
            (
                f"{len(listings)} listings read from the public catalogue endpoint"
                if listings
                else (listing_error or "No response.")
            ),
            f"https://www.daraz.com.bd/catalog/?q={keyword.replace(' ', '+')}",
        ),
    ]

    return {
        "keyword": keyword,
        "captured_at": now.isoformat(),
        "expires_at": metrics.expiry(SNAPSHOT_TTL_HOURS).isoformat(),
        "ttl_hours": SNAPSHOT_TTL_HOURS,
        "demand": {**demand, "quality": demand_quality},
        "competition": {**competition, "quality": competition_quality},
        "prices": {**prices, "quality": price_quality},
        "quality": quality,
        "risks": metrics.risk_factors(
            competition=competition,
            prices=prices,
            demand=demand,
            quality=quality,
        ),
        "sources": sources,
        "method": (
            "Computed from free public sources. Percentiles and shares are arithmetic "
            "over the records read; nothing is estimated or generated."
        ),
    }
