"""Deterministic Market Intelligence metrics and data-quality scoring.

Every number the screen shows is computed here from source records. A metric whose
sample is too small, or whose source failed, is returned as ``available: False`` with a
reason — never as a zero, a default or an estimate. That is what makes the "no
fabricated data" rule checkable rather than a promise.
"""

import math
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from xenovarients.platform.market.types import MarketListing, TrendSeries

# Below these sample sizes a metric is not reported at all.
MIN_TREND_MONTHS = 6
MIN_COMPETITION_LISTINGS = 5
MIN_PRICE_LISTINGS = 3

MIN_SAMPLE = {"demand": 24, "competition": 30, "prices": 20}


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolated percentile of an already sorted list."""
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return values[low]
    return values[low] + (values[high] - values[low]) * (position - low)


def _round(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def _month_label(period: str) -> str:
    try:
        return datetime.strptime(period, "%Y-%m").strftime("%b")
    except ValueError:
        return period


def unavailable(reason: str, **extra: Any) -> dict[str, Any]:
    """A metric that was not measured, with the reason it was not."""
    return {"available": False, "reason": reason, **extra}


def monthly_series(series: TrendSeries) -> list[dict[str, Any]]:
    """Monthly averages of the weekly points, in order."""
    buckets: dict[str, list[float]] = {}
    for point in series.points:
        buckets.setdefault(point.period, []).append(point.index)
    return [
        {"month": month, "index": round(sum(values) / len(values), 1)}
        for month, values in sorted(buckets.items())
    ]


def demand_metrics(series: TrendSeries) -> dict[str, Any]:
    """Demand level, direction, seasonality and geography from Google's index."""
    months = monthly_series(series)
    if len(months) < MIN_TREND_MONTHS:
        return unavailable(
            "Google Trends returned too little history for a demand read.",
            series=months,
        )
    values = [row["index"] for row in months]
    current = _mean(values[-3:]) or 0.0
    previous = _mean(values[-6:-3])
    peak = max(values)
    overall = _mean(values) or 0.0
    change_pct = (
        round((current - previous) / previous * 100, 1)
        if previous
        else None
    )
    if change_pct is None:
        direction = "unknown"
    elif change_pct > 5:
        direction = "rising"
    elif change_pct < -5:
        direction = "falling"
    else:
        direction = "steady"

    share_of_peak = current / peak if peak else 0.0
    if share_of_peak < 0.35:
        level = "low"
    elif share_of_peak < 0.65:
        level = "moderate"
    else:
        level = "high"

    peak_rows = sorted(
        (row for row in months if row["index"] >= overall * 1.15),
        key=lambda row: row["index"],
        reverse=True,
    )
    # The same month can peak in several years; the reader wants the months, not repeats.
    peak_months: list[str] = []
    for row in peak_rows:
        label = _month_label(row["month"])
        if label not in peak_months:
            peak_months.append(label)
        if len(peak_months) == 3:
            break
    seasonality_ratio = round(peak / overall, 2) if overall else None
    if seasonality_ratio is None:
        seasonality = "unknown"
    elif seasonality_ratio >= 1.5:
        seasonality = "strong"
    elif seasonality_ratio >= 1.25:
        seasonality = "moderate"
    else:
        seasonality = "flat"

    related = [item for item in series.related if item.kind == "top"][:6]
    rising = [item for item in series.related if item.kind == "rising"][:4]

    return {
        "available": True,
        "level": level,
        "current_index": _round(current),
        "peak_index": _round(peak),
        "recent_12_month_average": _round(_mean(values[-12:])),
        "change_pct": change_pct,
        "direction": direction,
        "peak_months": peak_months,
        "seasonality": {"label": seasonality, "ratio": seasonality_ratio},
        "regions": [
            {"region": item.region, "index": _round(item.index)}
            for item in series.regions[:5]
        ],
        "related_queries": [
            {"query": item.query, "kind": item.kind} for item in related
        ],
        "rising_queries": [{"query": item.query} for item in rising],
        "series": months,
        "window": {"months": len(months), "from": months[0]["month"], "to": months[-1]["month"]},
        "source": "Google Trends (relative interest, 0-100)",
    }


def _seller_key(listing: MarketListing) -> str:
    return listing.seller_id or listing.seller_name or listing.listing_id


def competition_metrics(listings: tuple[MarketListing, ...]) -> dict[str, Any]:
    """Seller density, concentration and how established the sellers are."""
    if len(listings) < MIN_COMPETITION_LISTINGS:
        return unavailable(
            f"Only {len(listings)} listings were readable; too few to describe competition.",
            sample=len(listings),
        )
    sellers: Counter[str] = Counter(_seller_key(listing) for listing in listings)
    total = sum(sellers.values())
    shares = [count / total for count in sellers.values()]
    hhi = round(sum(share * share for share in shares) * 10_000)
    top_seller, top_count = sellers.most_common(1)[0]

    reviews_by_seller: dict[str, int] = {}
    for listing in listings:
        key = _seller_key(listing)
        reviews_by_seller[key] = max(
            reviews_by_seller.get(key, 0), listing.reviews or 0
        )
    established = [key for key, reviews in reviews_by_seller.items() if reviews >= 50]

    review_values = sorted(
        listing.reviews for listing in listings if listing.reviews is not None
    )
    rating_values = sorted(
        listing.rating for listing in listings if listing.rating is not None
    )

    priced = sorted(
        listing.price_bdt for listing in listings if listing.price_bdt is not None
    )
    dispersion = None
    if len(priced) >= MIN_PRICE_LISTINGS:
        median = _percentile(priced, 0.5) or 0.0
        iqr = (_percentile(priced, 0.75) or 0.0) - (_percentile(priced, 0.25) or 0.0)
        dispersion = round(iqr / median, 2) if median else None

    seller_count = len(sellers)
    if seller_count < 5:
        density = "thin"
    elif seller_count < 15:
        density = "moderate"
    elif seller_count < 40:
        density = "busy"
    else:
        density = "crowded"

    return {
        "available": True,
        "seller_count": seller_count,
        "listing_count": len(listings),
        "density": density,
        "hhi": hhi,
        "top_seller_share_pct": round(top_count / total * 100, 1),
        "top_seller_is_single_listing": top_count == 1,
        "established_seller_share_pct": round(len(established) / seller_count * 100, 1),
        "median_reviews": int(_percentile(review_values, 0.5)) if review_values else None,
        "median_rating": _round(_percentile(rating_values, 0.5), 2) if rating_values else None,
        "price_dispersion": dispersion,
        "sample": len(listings),
        "source": "Daraz Bangladesh listings",
        "_top_seller_id": top_seller,
    }


def price_metrics(listings: tuple[MarketListing, ...]) -> dict[str, Any]:
    """Local retail BDT range, with discount depth and outlier removal."""
    prices = sorted(
        listing.price_bdt for listing in listings if listing.price_bdt is not None
    )
    if len(prices) < MIN_PRICE_LISTINGS:
        return unavailable(
            f"Only {len(prices)} priced listings were readable; no range is shown.",
            sample=len(prices),
        )
    q1 = _percentile(prices, 0.25) or 0.0
    q3 = _percentile(prices, 0.75) or 0.0
    iqr = q3 - q1
    low_fence = q1 - 1.5 * iqr
    high_fence = q3 + 1.5 * iqr
    kept = [price for price in prices if low_fence <= price <= high_fence] or prices
    removed = len(prices) - len(kept)

    discounts = []
    for listing in listings:
        if (
            listing.price_bdt
            and listing.original_price_bdt
            and listing.original_price_bdt > listing.price_bdt
        ):
            discounts.append(1 - listing.price_bdt / listing.original_price_bdt)
    sold_values = [
        listing.units_sold for listing in listings if listing.units_sold is not None
    ]

    return {
        "available": True,
        "currency": "BDT",
        "median": _round(_percentile(kept, 0.5), 0),
        "p25": _round(_percentile(kept, 0.25), 0),
        "p75": _round(_percentile(kept, 0.75), 0),
        "min": _round(kept[0], 0),
        "max": _round(kept[-1], 0),
        "median_discount_pct": (
            round(_percentile(sorted(discounts), 0.5) * 100, 1) if discounts else None
        ),
        "median_units_sold": (
            int(_percentile(sorted(sold_values), 0.5)) if sold_values else None
        ),
        "sample": len(kept),
        "outliers_removed": removed,
        "basis": "Displayed Daraz retail price, including live discounts.",
        "source": "Daraz Bangladesh listings",
    }


def panel_quality(
    *,
    available: bool,
    sample: int,
    min_sample: int,
    direct: bool,
    age_hours: float = 0.0,
) -> dict[str, Any]:
    """Why a panel is trustworthy, on a 0-100 scale that adds up visibly."""
    if not available:
        return {
            "score": 0,
            "label": "none",
            "parts": {"coverage": 0, "sample": 0, "freshness": 0},
            "reasons": ["No source returned usable data for this panel."],
        }
    coverage = 55
    sample_part = round(30 * min(1.0, sample / min_sample)) if min_sample else 30
    if age_hours <= 24:
        freshness = 15
    elif age_hours <= 72:
        freshness = 9
    elif age_hours <= 168:
        freshness = 5
    else:
        freshness = 0
    raw = coverage + sample_part + freshness
    if not direct:
        raw *= 0.9
    score = max(0, min(100, int(round(raw))))
    label = "high" if score >= 75 else "moderate" if score >= 50 else "low"
    reasons = [
        f"Source returned data ({coverage} pts).",
        f"{sample} records read against a {min_sample}-record target ({sample_part} pts).",
        f"Captured {age_hours:.0f}h ago ({freshness} pts).",
    ]
    if not direct:
        reasons.append("Relative index, not an absolute count (10% penalty).")
    return {
        "score": score,
        "label": label,
        "parts": {
            "coverage": coverage,
            "sample": sample_part,
            "freshness": freshness,
        },
        "reasons": reasons,
    }


def overall_quality(
    demand: dict[str, Any],
    competition: dict[str, Any],
    prices: dict[str, Any],
) -> dict[str, Any]:
    weights = {"demand": 0.35, "competition": 0.40, "prices": 0.25}
    scores = {
        "demand": demand.get("score", 0),
        "competition": competition.get("score", 0),
        "prices": prices.get("score", 0),
    }
    score = int(round(sum(scores[name] * weights[name] for name in weights)))
    label = "high" if score >= 75 else "moderate" if score >= 50 else "low"
    return {
        "score": score,
        "label": label,
        "panels": scores,
        "weights": weights,
    }


def _level(value: float, high_at: float, medium_at: float) -> str:
    """A three-way label, with the cut-offs named at the call site."""
    if value >= high_at:
        return "high"
    return "medium" if value >= medium_at else "low"


def risk_factors(
    *,
    competition: dict[str, Any],
    prices: dict[str, Any],
    demand: dict[str, Any],
    quality: dict[str, Any],
) -> list[dict[str, Any]]:
    """Risks with the measurement behind each. Unmeasured risks say so."""
    risks: list[dict[str, Any]] = []

    if competition.get("available"):
        density = competition["density"]
        level = {
            "crowded": "high",
            "busy": "high",
            "moderate": "medium",
        }.get(density, "low")
        risks.append(
            {
                "id": "competition",
                "label": "Shelf competition",
                "level": level,
                "detail": (
                    f"{competition['seller_count']} sellers across "
                    f"{competition['listing_count']} listings"
                ),
            }
        )
        if competition.get("price_dispersion") is not None:
            spread = competition["price_dispersion"]
            risks.append(
                {
                    "id": "price_spread",
                    "label": "Price positioning",
                    "level": _level(spread, 0.8, 0.45),
                    "detail": f"Interquartile price spread is {spread:.0%} of the median",
                }
            )
        established = competition.get("established_seller_share_pct")
        if established is not None:
            risks.append(
                {
                    "id": "entrenched_sellers",
                    "label": "Entrenched sellers",
                    "level": _level(established, 60, 30),
                    "detail": f"{established:.0f}% of sellers already have 50+ reviews",
                }
            )

    if demand.get("available"):
        seasonality = demand["seasonality"]
        ratio = seasonality.get("ratio")
        risks.append(
            {
                "id": "seasonality",
                "label": "Seasonal demand",
                "level": {"strong": "high", "moderate": "medium"}.get(
                    seasonality["label"], "low"
                ),
                "detail": (
                    f"Peak month is {ratio:.2f}× the average month"
                    if ratio
                    else "Seasonality could not be measured"
                ),
            }
        )
        regions = demand.get("regions") or []
        if regions:
            top = regions[0]
            risks.append(
                {
                    "id": "regional_concentration",
                    "label": "Demand concentration",
                    "level": "medium" if top["index"] >= 60 else "low",
                    "detail": f"{top['region']} is the top interest region (index {top['index']})",
                }
            )

    if prices.get("available") and prices.get("median_discount_pct") is not None:
        discount = prices["median_discount_pct"]
        risks.append(
            {
                "id": "discount_dependence",
                "label": "Discount-led pricing",
                "level": _level(discount, 35, 20),
                "detail": f"Median listed discount is {discount:.0f}% off the struck-through price",
            }
        )

    if quality["score"] < 50:
        risks.append(
            {
                "id": "thin_evidence",
                "label": "Thin evidence",
                "level": "high",
                "detail": f"Data quality score is {quality['score']}/100",
            }
        )

    # Deliberately unmeasured: there is no free supplier-cost or customs source yet.
    for risk_id, label, reason in (
        (
            "supplier_cost",
            "Supplier cost and landed price",
            "No free supplier-price source is connected; BDT figures here are retail prices.",
        ),
        (
            "regulation",
            "Import and certification",
            "Customs duty and product certification are not assessed.",
        ),
    ):
        risks.append(
            {
                "id": risk_id,
                "label": label,
                "level": "unknown",
                "detail": reason,
            }
        )
    return risks


def expiry(ttl_hours: int = 12) -> datetime:
    return datetime.now(UTC) + timedelta(hours=ttl_hours)
