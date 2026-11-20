"""Read-only Meta ad intelligence: competitor ads, one ad's detail and own-ad ranking.

There is no Meta API call here. These tools read what was captured into
``ad_insight_snapshots`` and say plainly where a number is missing: a metric that was
never tracked comes back as ``{"value": null, "reason": "tracking not available"}``,
not as zero.
"""

from datetime import UTC, datetime
from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy import Text, or_, select
from sqlalchemy import cast as sa_cast

from xenovarients.models.ads import AdInsightSnapshot
from xenovarients.platform import ads
from xenovarients.platform.mcp.shared import (
    ADMIN_ROLES,
    authenticate,
    build_server,
    iso,
    not_found,
    parse_uuid,
    read_only,
    result,
    tenant_session,
)

server = build_server(
    name="meta_ads",
    title="XenoDesk Meta Ad Intelligence",
    instructions=(
        "Read-only answers about competitor ads and the business's own ad performance: "
        "search captured competitor ads, inspect one ad, and rank own ads for an "
        "objective. Calls no ad platform and writes nothing."
    ),
)


@read_only(server)
async def search_ads(
    ctx: Context,
    keyword: str = "",
    limit: int = 5,
) -> dict[str, Any]:
    """Captured competitor ads, best score first, with the source tier they came from.

    ``keyword`` matches the visible creative or advertiser name; an empty keyword returns
    the highest-scoring ads regardless. ``source_tier`` is reported honestly so an ad from
    manual intake is never mistaken for a licensed-provider result.
    """
    principal = await authenticate(ctx, roles=ADMIN_ROLES)
    needle = keyword.strip()

    async with tenant_session(principal.business_id) as session:
        statement = select(AdInsightSnapshot).where(
            AdInsightSnapshot.business_id == principal.business_id,
            AdInsightSnapshot.scope == "competitor",
        )
        if needle:
            statement = statement.where(
                or_(
                    AdInsightSnapshot.advertiser_name.ilike(f"%{needle}%"),
                    sa_cast(AdInsightSnapshot.creative, Text).ilike(f"%{needle}%"),
                )
            )
        rows = list(
            (
                await session.execute(
                    statement.order_by(
                        AdInsightSnapshot.score.desc().nullslast(),
                        AdInsightSnapshot.synced_at.desc(),
                    ).limit(min(max(limit, 1), 50))
                )
            )
            .scalars()
            .all()
        )
        payload = [_competitor_payload(row) for row in rows]

    return result(
        keyword=needle or None,
        ads=payload,
        count=len(payload),
    )


@read_only(server)
async def get_ad_details(
    ctx: Context,
    ad_id: str,
) -> dict[str, Any]:
    """One captured ad by its snapshot id, including its score breakdown and metrics.

    A snapshot that does not exist for this business is ``found: false`` — never an empty
    record that looks like an ad with no data.
    """
    principal = await authenticate(ctx, roles=ADMIN_ROLES)
    identifier = parse_uuid(ad_id, kind="ad_id")

    async with tenant_session(principal.business_id) as session:
        row = await session.scalar(
            select(AdInsightSnapshot).where(
                AdInsightSnapshot.business_id == principal.business_id,
                AdInsightSnapshot.id == identifier,
            )
        )
        if row is None:
            return not_found("ad snapshot", identifier)
        payload = _competitor_payload(row)
        payload["metrics"] = ads.metrics_with_unavailable_reasons(row.metrics or {})
        payload["scope"] = row.scope
        payload["objective"] = row.objective
        payload["ad_id"] = row.ad_id

    return result(**payload)


@read_only(server)
async def rank_ads(
    ctx: Context,
    objective: str = "sales",
    since: datetime | None = None,
) -> dict[str, Any]:
    """Rank the business's own ad snapshots for one objective.

    Ads without enough signal are returned under ``unranked`` with their guard reason
    instead of being silently dropped or ranked as if they had zero performance.
    """
    principal = await authenticate(ctx, roles=ADMIN_ROLES)

    async with tenant_session(principal.business_id) as session:
        statement = select(AdInsightSnapshot).where(
            AdInsightSnapshot.business_id == principal.business_id,
            AdInsightSnapshot.scope == "own",
            AdInsightSnapshot.objective == objective,
        )
        if since is not None:
            statement = statement.where(AdInsightSnapshot.synced_at >= since)
        snapshots = list((await session.execute(statement)).scalars().all())

        ranked = ads.rank_own_ads(snapshots, objective=objective)
        now = datetime.now(UTC)
        ranked_payload: list[dict[str, Any]] = []
        unranked_payload: list[dict[str, Any]] = []
        for row in ranked:
            metrics = row.metrics or {}
            payload = {
                "snapshot_id": str(row.id),
                "ad_id": row.ad_id,
                "objective": row.objective,
                "metrics": ads.metrics_with_unavailable_reasons(metrics),
                "synced_at": iso(row.synced_at),
                "stale": ads.is_stale(row.synced_at, now=now),
            }
            if ads.passes_guard(metrics, objective=objective, min_spend=1):
                ranked_payload.append(payload)
            else:
                unranked_payload.append(
                    {
                        **payload,
                        "reason": "insufficient_signal",
                        "detail": "Not enough spend or volume to rank on this objective yet.",
                    }
                )

    return result(
        objective=objective,
        ranked=ranked_payload,
        unranked=unranked_payload,
        ranked_count=len(ranked_payload),
        unranked_count=len(unranked_payload),
    )


def _competitor_payload(row: AdInsightSnapshot) -> dict[str, Any]:
    creative = dict(row.creative or {})
    creative.setdefault("visible_price", "Not visible")
    creative.setdefault("copy", "Not available")
    return {
        "snapshot_id": str(row.id),
        "advertiser_name": row.advertiser_name,
        "ad_url": row.ad_url,
        "creative": creative,
        "score": float(row.score) if row.score is not None else None,
        "score_breakdown": row.score_breakdown,
        "source_tier": row.source_tier,
        "synced_at": iso(row.synced_at),
        "fetched_at": iso(row.fetched_at),
    }

