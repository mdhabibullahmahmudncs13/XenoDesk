"""Deterministic Creator Commerce ad rules."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from xenovarients.platform.ads import (
    is_stale,
    metrics_with_unavailable_reasons,
    passes_guard,
    rank_own_ads,
    score_ad,
)


def test_competitor_score_keeps_component_evidence_and_no_price_guess():
    score, breakdown = score_ad({"copy": "Cotton kurti", "cta": "Shop now"}, keyword="kurti")

    assert score == 80
    assert breakdown["relevance"]["score"] == 40
    assert breakdown["offer_readability"]["evidence"] == "offer not visible"


def test_own_ad_ranking_is_objective_specific_and_guarded():
    rows = [
        SimpleNamespace(metrics={"spend": 100, "roas": 2, "cpa": 10, "conversions": 2}),
        SimpleNamespace(metrics={"spend": 1, "roas": 10, "cpa": 1, "conversions": 1}),
    ]

    ranked = rank_own_ads(rows, objective="sales", min_spend=50)

    assert ranked[0] is rows[0]
    assert ranked[1] is rows[1]
    assert passes_guard(rows[0].metrics, objective="sales", min_spend=50)
    assert not passes_guard(rows[1].metrics, objective="sales", min_spend=50)


def test_missing_conversion_metrics_are_explicit_and_freshness_is_measurable():
    metrics = metrics_with_unavailable_reasons({"spend": 20})
    now = datetime.now(UTC)

    assert metrics["roas"] == {"value": None, "reason": "tracking not available"}
    assert is_stale(now - timedelta(hours=25), now=now)
    assert not is_stale(now - timedelta(hours=1), now=now)


def test_unknown_objective_is_rejected():
    with pytest.raises(ValueError, match="Unknown ad objective"):
        rank_own_ads([], objective="awareness")
