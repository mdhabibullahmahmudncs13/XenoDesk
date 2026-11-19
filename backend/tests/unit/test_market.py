"""Market Intelligence arithmetic: parsing, metrics, quality and risk labels.

The point of these tests is the no-fabrication rule: with no data, a metric must be
absent rather than zero, and every risk must name the measurement behind it.
"""

from datetime import UTC, datetime

from xenovarients.platform.market import metrics
from xenovarients.platform.market.daraz import parse_listings, parse_sold
from xenovarients.platform.market.types import (
    MarketListing,
    RelatedQuery,
    TrendPoint,
    TrendSeries,
)


def listing(**overrides: object) -> MarketListing:
    defaults: dict[str, object] = {
        "listing_id": "1",
        "title": "Wireless earbuds",
        "price_bdt": 1000.0,
        "seller_id": "s1",
        "seller_name": "Shop One",
        "reviews": 10,
        "rating": 4.5,
    }
    defaults.update(overrides)
    return MarketListing(**defaults)  # type: ignore[arg-type]


def trend(points: list[tuple[str, float]]) -> TrendSeries:
    return TrendSeries(
        points=tuple(TrendPoint(period=period, index=index) for period, index in points),
        fetched_at=datetime.now(UTC),
    )


def test_parse_sold_reads_daraz_labels() -> None:
    assert parse_sold("484 sold") == 484
    assert parse_sold("1.2K sold") == 1200
    assert parse_sold("3M+ sold") == 3_000_000
    assert parse_sold("12,345 sold") == 12345
    assert parse_sold("") is None
    assert parse_sold(None) is None
    assert parse_sold("No reviews") is None


def test_parse_listings_maps_fields_and_keeps_unpriced_rows() -> None:
    payload = {
        "mods": {
            "listItems": [
                {
                    "itemId": "111",
                    "name": "Earbuds A",
                    "price": "1279",
                    "originalPrice": "1990",
                    "sellerId": "7",
                    "sellerName": "Shop",
                    "ratingScore": "4.4",
                    "review": "21",
                    "itemSoldCntShow": "484 sold",
                    "location": "Dhaka",
                    "inStock": True,
                },
                {"itemId": "112", "name": "Earbuds B", "price": ""},
                {"itemId": "", "name": "no id"},
            ]
        }
    }
    rows = parse_listings(payload)
    assert len(rows) == 2
    first = rows[0]
    assert first.price_bdt == 1279.0
    assert first.units_sold == 484
    assert first.reviews == 21
    assert first.url.endswith("-i111.html")
    assert rows[1].price_bdt is None


def test_demand_metrics_finds_peak_months_and_direction() -> None:
    months = [f"2024-{month:02d}" for month in range(1, 13)] * 2
    values = [10, 9, 11, 12, 13, 14, 15, 16, 20, 45, 60, 30] * 2
    values[-1] = 70
    result = metrics.demand_metrics(trend(list(zip(months, values, strict=True))))
    assert result["available"] is True
    assert "Nov" in result["peak_months"]
    assert len(result["peak_months"]) == len(set(result["peak_months"]))
    assert result["seasonality"]["label"] in {"moderate", "strong"}
    assert result["direction"] in {"rising", "steady", "falling"}
    assert result["series"]


def test_demand_metrics_refuses_thin_history() -> None:
    result = metrics.demand_metrics(trend([("2026-01", 40), ("2026-02", 42)]))
    assert result["available"] is False
    assert "current_index" not in result
    assert result["reason"]


def test_competition_metrics_counts_sellers_and_establishment() -> None:
    listings = (
        listing(listing_id="1", seller_id="a", reviews=120),
        listing(listing_id="2", seller_id="a", reviews=40),
        listing(listing_id="3", seller_id="b", reviews=5),
        listing(listing_id="4", seller_id="c", reviews=0),
        listing(listing_id="5", seller_id="c", reviews=0),
        listing(listing_id="6", seller_id="d", reviews=0),
    )
    result = metrics.competition_metrics(listings)
    assert result["seller_count"] == 4
    assert result["listing_count"] == 6
    assert result["established_seller_share_pct"] == 25.0
    assert 0 < result["hhi"] <= 10_000
    # Reviews are 0, 0, 0, 5, 40, 120 — an even count, so the median is 2.5 → 2.
    assert result["median_reviews"] == 2


def test_competition_metrics_refuses_small_sample() -> None:
    result = metrics.competition_metrics((listing(), listing(listing_id="2")))
    assert result["available"] is False


def test_price_metrics_reports_percentiles_and_drops_outliers() -> None:
    prices = [100, 200, 300, 400, 500, 100_000]
    listings = tuple(
        listing(listing_id=str(index), price_bdt=float(price))
        for index, price in enumerate(prices)
    )
    result = metrics.price_metrics(listings)
    assert result["available"] is True
    assert result["median"] == 300
    assert result["p25"] == 200
    assert result["p75"] == 400
    assert result["outliers_removed"] == 1
    assert result["max"] == 500


def test_price_metrics_refuses_without_prices() -> None:
    result = metrics.price_metrics(tuple(listing(price_bdt=None) for _ in range(4)))
    assert result["available"] is False
    assert "median" not in result


def test_quality_scores_unavailable_panel_at_zero() -> None:
    result = metrics.panel_quality(available=False, sample=0, min_sample=30, direct=True)
    assert result["score"] == 0
    assert result["label"] == "none"


def test_overall_quality_weights_the_panels() -> None:
    high = {"score": 100}
    result = metrics.overall_quality(high, high, high)
    assert result["score"] == 100
    assert result["label"] == "high"
    assert result["panels"]["prices"] == 100


def test_risks_name_their_evidence_and_never_assess_the_unknown() -> None:
    competition = metrics.competition_metrics(
        tuple(
            listing(listing_id=str(index), seller_id=f"s{index}", reviews=100)
            for index in range(10)
        )
    )
    prices = metrics.price_metrics(
        tuple(
            listing(listing_id=str(index), price_bdt=1000.0 + index)
            for index in range(10)
        )
    )
    demand = metrics.demand_metrics(
        trend([(f"2024-{month:02d}", 20) for month in range(1, 13)])
    )
    quality = metrics.overall_quality({"score": 80}, {"score": 80}, {"score": 80})
    risks = metrics.risk_factors(
        competition=competition, prices=prices, demand=demand, quality=quality
    )
    by_id = {risk["id"]: risk for risk in risks}
    assert by_id["competition"]["level"] == "medium"
    assert "10 sellers" in by_id["competition"]["detail"]
    assert by_id["supplier_cost"]["level"] == "unknown"
    assert by_id["regulation"]["level"] == "unknown"
    assert all(risk["detail"] for risk in risks)


def test_related_queries_are_kept_as_given() -> None:
    series = TrendSeries(related=(RelatedQuery(query="earbuds", kind="top", score=100),))
    result = metrics.demand_metrics(
        TrendSeries(
            points=tuple(
                TrendPoint(period=f"2025-{month:02d}", index=30)
                for month in range(1, 13)
            ),
            related=series.related,
        )
    )
    assert result["related_queries"] == [{"query": "earbuds", "kind": "top"}]
