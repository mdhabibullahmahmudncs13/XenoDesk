"""Google Trends — the free demand source.

Google's official Trends API is still an invite-only alpha, so this reads the two
endpoints the Trends website itself calls: ``explore`` returns widget descriptors,
then each widget's data endpoint returns the numbers. Keyless and free.

What it returns is *relative* interest (the term's peak in the window is 100), not
search volume. The metrics layer labels it that way and never converts it to a count.
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote_plus

import httpx

from xenovarients.platform.market.daraz import MarketSourceError
from xenovarients.platform.market.types import (
    RegionInterest,
    RelatedQuery,
    TrendPoint,
    TrendSeries,
)

_EXPLORE = "https://trends.google.com/trends/api/explore"
_MULTILINE = "https://trends.google.com/trends/api/widgetdata/multiline"
_COMPARED_GEO = "https://trends.google.com/trends/api/widgetdata/comparedgeo"
_RELATED = "https://trends.google.com/trends/api/widgetdata/relatedsearches"
_HOME = "https://trends.google.com/trends/"
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124 Safari/537.36"
)
_TIMEOUT = httpx.Timeout(25.0, connect=10.0)


def _unprefix(text: str) -> str:
    """Google prefixes JSON with ``)]}'`` to defeat script tags."""
    return text[5:] if text.startswith(")]}'") else text


def _widget(payload: dict[str, Any], prefix: str) -> dict[str, Any] | None:
    for widget in payload.get("widgets") or []:
        if str(widget.get("id", "")).startswith(prefix):
            return widget
    return None


def _value(point: dict[str, Any]) -> float:
    raw = point.get("value")
    if isinstance(raw, list):
        raw = raw[0] if raw else 0
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def _month(epoch: Any) -> str | None:
    try:
        moment = datetime.fromtimestamp(int(epoch), UTC)
    except (TypeError, ValueError, OSError):
        return None
    return moment.strftime("%Y-%m")


def parse_timeseries(payload: dict[str, Any]) -> tuple[TrendPoint, ...]:
    """Weekly points from ``multiline``, bucketed by month."""
    buckets: dict[str, list[float]] = {}
    for point in (payload.get("default") or {}).get("timelineData") or []:
        month = _month(point.get("time"))
        if month is None:
            continue
        buckets.setdefault(month, []).append(_value(point))
    return tuple(
        TrendPoint(period=month, index=round(sum(values) / len(values), 1))
        for month, values in sorted(buckets.items())
    )


def parse_regions(payload: dict[str, Any]) -> tuple[RegionInterest, ...]:
    regions: list[RegionInterest] = []
    for row in (payload.get("default") or {}).get("geoMapData") or []:
        if not row.get("hasData", True):
            continue
        name = str(row.get("geoName") or "").strip()
        if not name:
            continue
        regions.append(RegionInterest(region=name, index=_value(row)))
    return tuple(sorted(regions, key=lambda item: item.index, reverse=True))


def parse_related(payload: dict[str, Any]) -> tuple[RelatedQuery, ...]:
    """Top and rising queries, in Google's own order."""
    related: list[RelatedQuery] = []
    ranked = (payload.get("default") or {}).get("rankedList") or []
    for index, block in enumerate(ranked):
        kind = "rising" if index == 1 else "top"
        for row in block.get("rankedKeyword") or []:
            query = str(row.get("query") or "").strip()
            if not query:
                continue
            raw = row.get("value")
            score = raw if isinstance(raw, int) else 0
            related.append(RelatedQuery(query=query, kind=kind, score=score))
    return tuple(related)


async def _get_json(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, Any],
    *,
    attempts: int = 2,
) -> dict[str, Any]:
    for attempt in range(attempts):
        response = await client.get(url, params=params)
        if response.status_code != 429:
            break
        # Trends throttles bursts, and a single retry after a pause usually clears it.
        if attempt + 1 < attempts:
            await asyncio.sleep(2.0)
    if response.status_code == 429:
        raise MarketSourceError(
            "Google Trends is rate-limiting requests right now. Try again in a minute."
        )
    if response.status_code != 200:
        raise MarketSourceError(
            f"Google Trends answered HTTP {response.status_code}."
        )
    try:
        return json.loads(_unprefix(response.text))
    except ValueError as exc:
        raise MarketSourceError("Google Trends returned a page that is not JSON.") from exc


async def fetch_trends(
    keyword: str,
    *,
    geo: str = "BD",
    timeframe: str = "today 5-y",
    client: httpx.AsyncClient | None = None,
) -> TrendSeries:
    """Monthly interest, sub-regions and related queries for one keyword."""
    owns_client = client is None
    client = client or httpx.AsyncClient(
        headers={"User-Agent": _USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        timeout=_TIMEOUT,
        follow_redirects=True,
    )
    params = {"hl": "en-US", "tz": "0"}
    try:
        # The API expects the cookies a normal visit sets.
        await client.get(_HOME, params={"geo": geo})
        request = {
            "comparisonItem": [{"keyword": keyword, "geo": geo, "time": timeframe}],
            "category": 0,
            "property": "",
        }
        explore = await _get_json(
            client, _EXPLORE, {**params, "req": json.dumps(request)}
        )

        points: tuple[TrendPoint, ...] = ()
        timeseries = _widget(explore, "TIMESERIES")
        if timeseries is not None:
            data = await _get_json(
                client,
                _MULTILINE,
                {
                    **params,
                    "req": json.dumps(timeseries["request"]),
                    "token": timeseries["token"],
                },
            )
            points = parse_timeseries(data)
        if not points:
            raise MarketSourceError(
                f"Google Trends returned no interest data for “{keyword}”."
            )

        regions: tuple[RegionInterest, ...] = ()
        geo_widget = _widget(explore, "GEO_MAP")
        if geo_widget is not None:
            data = await _get_json(
                client,
                _COMPARED_GEO,
                {
                    **params,
                    "req": json.dumps(geo_widget["request"]),
                    "token": geo_widget["token"],
                },
            )
            regions = parse_regions(data)

        related: tuple[RelatedQuery, ...] = ()
        related_widget = _widget(explore, "RELATED_QUERIES")
        if related_widget is not None:
            data = await _get_json(
                client,
                _RELATED,
                {
                    **params,
                    "req": json.dumps(related_widget["request"]),
                    "token": related_widget["token"],
                },
            )
            related = parse_related(data)

        return TrendSeries(
            points=points,
            regions=regions,
            related=related,
            fetched_at=datetime.now(UTC),
            source_url=(
                "https://trends.google.com/trends/explore"
                f"?geo={geo}&q={quote_plus(keyword)}"
            ),
        )
    except httpx.HTTPError as exc:
        raise MarketSourceError(
            f"Google Trends did not respond ({exc.__class__.__name__})."
        ) from exc
    finally:
        if owns_client:
            await client.aclose()
