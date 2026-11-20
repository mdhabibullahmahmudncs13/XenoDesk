"""Read-only analytics snapshots: what a module holds right now, shaped for export.

``export_snapshot`` builds the snapshot and reports where it *would* go. Writing it to a
third-party destination is a write outside this platform, so it stays an
owner-confirmed action rather than a tool call: ``persisted`` is always false and the
configured destination is reported, never used. That keeps the project's read-only rule
intact while still giving the agent a real answer to \"what would we export?\".
"""

from datetime import UTC, datetime
from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy import func, select

from xenovarients.models.ads import AdInsightSnapshot
from xenovarients.models.customer import Customer
from xenovarients.models.restock import ProductInterest, RestockBatch, RestockEvent
from xenovarients.models.sourcing import MarketSnapshot
from xenovarients.platform.mcp import external
from xenovarients.platform.mcp.shared import (
    authenticate,
    build_server,
    iso,
    read_only,
    result,
    tenant_session,
)

SOURCES: tuple[str, ...] = ("genome", "sourcing", "ads")

server = build_server(
    name="analytics",
    title="XenoDesk Analytics",
    instructions=(
        "Read-only snapshots of Customer Genome, Market Intelligence and ad intelligence, "
        "shaped for export. The snapshot is returned; nothing is written or pushed to a "
        "destination from here."
    ),
)


@read_only(server)
async def export_snapshot(
    ctx: Context,
    source: str = "genome",
    destination: str | None = None,
) -> dict[str, Any]:
    """A current snapshot of one module, with the export destination's status.

    ``source`` is one of ``genome``, ``sourcing`` or ``ads``. ``destination`` only names
    where an export would go; a configured export source is reported as available, and
    ``persisted`` is always false because pushing the snapshot is an owner decision.
    """
    chosen = source.strip().lower()
    if chosen not in SOURCES:
        return result(
            available=False,
            field="snapshot",
            reason="unknown_source",
            detail=f"source must be one of: {', '.join(SOURCES)}.",
        )

    principal = await authenticate(ctx)
    async with tenant_session(principal.business_id) as session:
        if chosen == "genome":
            snapshot = await _genome_snapshot(session, principal.business_id)
        elif chosen == "sourcing":
            snapshot = await _sourcing_snapshot(session, principal.business_id)
        else:
            snapshot = await _ads_snapshot(session, principal.business_id)

    target = external.status("analytics_export")
    return result(
        source=chosen,
        snapshot=snapshot,
        destination={
            **target,
            "requested": destination,
            "note": (
                "Building a snapshot is read-only. Writing it to a destination is an "
                "owner-confirmed action."
            ),
        },
        persisted=False,
        available=True,
    )


async def _genome_snapshot(session: Any, business_id: Any) -> dict[str, Any]:
    customers = await session.scalar(
        select(func.count(Customer.id)).where(Customer.business_id == business_id)
    )
    waiting = await session.scalar(
        select(func.count(ProductInterest.id)).where(ProductInterest.business_id == business_id)
    )
    restocks = await session.scalar(
        select(func.count(RestockEvent.id)).where(RestockEvent.business_id == business_id)
    )
    batch_rows = (
        await session.execute(
            select(RestockBatch.state, func.count(RestockBatch.id))
            .where(RestockBatch.business_id == business_id)
            .group_by(RestockBatch.state)
        )
    ).all()
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "customers": int(customers or 0),
        "waiting_interests": int(waiting or 0),
        "restock_events": int(restocks or 0),
        "restock_batches": {state: int(count) for state, count in batch_rows},
    }


async def _sourcing_snapshot(session: Any, business_id: Any) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(MarketSnapshot)
            .where(MarketSnapshot.business_id == business_id)
            .order_by(MarketSnapshot.captured_at.desc())
            .limit(50)
        )
    ).scalars()
    readings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if row.keyword in seen:
            continue
        seen.add(row.keyword)
        demand = dict(row.payload or {}).get("demand")
        demand = demand if isinstance(demand, dict) else {}
        readings.append(
            {
                "keyword": row.keyword,
                "captured_at": iso(row.captured_at),
                "expires_at": iso(row.expires_at),
                "demand_level": demand.get("level"),
                "demand_available": bool(demand.get("available")),
            }
        )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "keywords": len(readings),
        "readings": readings,
    }


async def _ads_snapshot(session: Any, business_id: Any) -> dict[str, Any]:
    scope_rows = (
        await session.execute(
            select(AdInsightSnapshot.scope, func.count(AdInsightSnapshot.id))
            .where(AdInsightSnapshot.business_id == business_id)
            .group_by(AdInsightSnapshot.scope)
        )
    ).all()
    tier_rows = (
        await session.execute(
            select(AdInsightSnapshot.source_tier, func.count(AdInsightSnapshot.id))
            .where(AdInsightSnapshot.business_id == business_id)
            .group_by(AdInsightSnapshot.source_tier)
        )
    ).all()
    latest = await session.scalar(
        select(func.max(AdInsightSnapshot.synced_at)).where(
            AdInsightSnapshot.business_id == business_id
        )
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "by_scope": {scope: int(count) for scope, count in scope_rows},
        "by_source_tier": {tier: int(count) for tier, count in tier_rows},
        "latest_synced_at": iso(latest),
    }
