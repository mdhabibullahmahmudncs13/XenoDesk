"""The qualifying-order rule set (OD-02).

The rule set is data — ``configs/qualifying_order_rules.json`` — so a rule change is
a config edit, not a release. What matters here is that the mapping is *versioned*
and that each case in OD-02 lands the way the plan says it does.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from xenovarients.platform.source import SourceOrder
from xenovarients.platform.sync import load_rules


def _order(**overrides: Any) -> SourceOrder:
    base: dict[str, Any] = {
        "source_order_id": "ord-x",
        "source_customer_id": "cus-x",
        "status": "paid",
        "ordered_at": datetime(2026, 11, 1, tzinfo=UTC),
        "total_amount": Decimal("1000.00"),
    }
    base.update(overrides)
    return SourceOrder(**base)


def test_the_shipped_rules_are_versioned() -> None:
    rules = load_rules()
    assert rules.version
    assert rules.qualifying_statuses == frozenset({"paid", "completed"})
    assert rules.excluded_statuses == frozenset({"cancelled", "returned"})


@pytest.mark.parametrize("status", ["paid", "completed"])
def test_a_paid_or_completed_order_qualifies(status: str) -> None:
    assert load_rules().qualifies(_order(status=status)) is True


@pytest.mark.parametrize("status", ["cancelled", "returned"])
def test_a_cancelled_or_returned_order_does_not_qualify(status: str) -> None:
    assert load_rules().qualifies(_order(status=status)) is False


def test_a_pending_order_does_not_qualify() -> None:
    """Not in the qualifying set, so it does not count."""
    assert load_rules().qualifies(_order(status="pending")) is False


def test_a_fully_refunded_order_does_not_qualify() -> None:
    """OD-02: fully refunded orders are excluded."""
    order = _order(status="refunded", is_refunded=True, refund_amount=Decimal("1000.00"))
    assert load_rules().qualifies(order) is False


def test_a_cancelled_flag_excludes_the_order_even_when_the_status_says_paid() -> None:
    """The flag and the status must agree; when they do not, the flag wins."""
    order = _order(status="paid", is_cancelled=True)
    assert load_rules().qualifies(order) is False


def test_a_partially_refunded_order_still_qualifies() -> None:
    """OD-02: a partial refund counts, net of the refund."""
    order = _order(status="completed", refund_amount=Decimal("200.00"))
    assert load_rules().qualifies(order) is True


def test_the_status_comparison_ignores_case_and_padding() -> None:
    """The source may write ``"Paid"``; the rules are written in lowercase."""
    assert load_rules().qualifies(_order(status="Paid")) is True
    assert load_rules().qualifies(_order(status=" PAID ")) is True


def test_the_repeat_buyer_threshold_is_two_orders() -> None:
    assert load_rules().repeat_buyer_min_orders == 2
