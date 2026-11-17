"""Read-only ad intelligence and deterministic own-ad ranking."""

from datetime import datetime
from typing import Any, Protocol

from xenovarients.models.ads import AdObjective, AdSourceTier


class AdSource(Protocol):
    """A source of competitor ads; implementations must identify their tier."""

    tier: AdSourceTier

    async def search(self, *, keyword: str, country: str) -> list[dict[str, Any]]:
        ...


def score_ad(creative: dict[str, Any] | None, *, keyword: str) -> tuple[float, dict[str, Any]]:
    """Score only visible creative attributes, retaining evidence for each score."""
    data = creative or {}
    copy = str(data.get("copy") or "")
    relevance = 40.0 if keyword.lower() in copy.lower() else 0.0
    clarity = 25.0 if copy else 0.0
    offer = 20.0 if data.get("visible_price") or data.get("offer") else 0.0
    cta = 15.0 if data.get("cta") else 0.0
    breakdown = {
        "relevance": {"score": relevance, "evidence": "keyword in visible copy"}
        if relevance
        else {"score": 0.0, "evidence": "keyword not found in visible copy"},
        "message_clarity": {"score": clarity, "evidence": "visible copy present"},
        "offer_readability": {
            "score": offer,
            "evidence": "visible offer present" if offer else "offer not visible",
        },
        "cta_strength": {"score": cta, "evidence": "CTA present" if cta else "CTA not available"},
    }
    return relevance + clarity + offer + cta, breakdown


def rank_own_ads(
    snapshots: list[Any],
    *,
    objective: str,
    min_spend: float = 0.0,
    min_impressions: int = 0,
    min_leads: int = 0,
) -> list[Any]:
    """Rank one objective with visible guards; guarded rows remain valid but unranked."""
    if objective not in {item.value for item in AdObjective}:
        raise ValueError(f"Unknown ad objective '{objective}'.")

    def key(snapshot: Any) -> tuple[bool, tuple[float, ...]]:
        metrics = snapshot.metrics or {}
        if objective == AdObjective.sales.value:
            eligible = float(metrics.get("spend") or 0) >= min_spend
            return eligible, (
                float(metrics.get("roas") or -1),
                -float(metrics.get("cpa") or 10**12),
                float(metrics.get("conversions") or 0),
            )
        if objective == AdObjective.traffic.value:
            eligible = int(metrics.get("impressions") or 0) >= min_impressions
            return eligible, (
                float(metrics.get("ctr") or 0),
                -float(metrics.get("cpc") or 10**12),
            )
        eligible = int(metrics.get("leads") or 0) >= min_leads
        return eligible, (
            -float(metrics.get("cost_per_lead") or 10**12),
            float(metrics.get("leads") or 0),
        )

    return sorted(snapshots, key=key, reverse=True)


def passes_guard(
    metrics: dict[str, Any],
    *,
    objective: str,
    min_spend: float = 1,
    min_impressions: int = 100,
    min_leads: int = 1,
) -> bool:
    """Return whether a snapshot has enough signal to be ranked."""
    if objective == AdObjective.sales.value:
        return float(metrics.get("spend") or 0) >= min_spend
    if objective == AdObjective.traffic.value:
        return int(metrics.get("impressions") or 0) >= min_impressions
    if objective == AdObjective.leads.value:
        return int(metrics.get("leads") or 0) >= min_leads
    raise ValueError(f"Unknown ad objective '{objective}'.")


def metrics_with_unavailable_reasons(metrics: dict[str, Any]) -> dict[str, Any]:
    """Make missing conversion metrics explicit instead of inventing zeros."""
    result = dict(metrics)
    for field in ("roas", "cpa", "conversions"):
        if result.get(field) is None:
            result[field] = {"value": None, "reason": "tracking not available"}
    return result


def is_stale(synced_at: datetime, *, now: datetime, max_age_hours: int = 24) -> bool:
    return (now - synced_at).total_seconds() > max_age_hours * 3600
