"""Channel eligibility (OD-05).

The engine is pure: rules in, decision out. These tests pin down the *ordering* of
the blockers, because the order is the operator-facing part — "no consent" tells the
operator what to fix, "invalid address" does not.
"""

from typing import Any

import pytest

from xenovarients.platform.eligibility import (
    EligibilityDecision,
    check,
    load_rules,
    reason_text,
)


@pytest.fixture(scope="module")
def rules() -> dict[str, Any]:
    return load_rules()


def _check(rules: dict[str, Any], **overrides: Any) -> EligibilityDecision:
    base: dict[str, Any] = {
        "channel": "email",
        "has_consent": True,
        "has_verified_identity": True,
        "opted_out": False,
        "has_contact_value": True,
        "channel_enabled": True,
    }
    base.update(overrides)
    return check(rules, **base)


def test_eligible_recipient_passes(rules: dict[str, Any]) -> None:
    assert _check(rules).eligible is True


def test_unknown_channel_is_not_enabled(rules: dict[str, Any]) -> None:
    decision = _check(rules, channel="telegram")
    assert decision.eligible is False
    assert decision.reason == "channel_not_enabled"


def test_disabled_channel_is_reported(rules: dict[str, Any]) -> None:
    decision = _check(rules, channel_enabled=False)
    assert decision.eligible is False
    assert decision.reason == "channel_not_enabled"


def test_opt_out_beats_missing_consent(rules: dict[str, Any]) -> None:
    """Opt-out is the most fundamental blocker: nothing else matters if the
    customer said no."""
    decision = _check(rules, opted_out=True, has_consent=False, has_contact_value=False)
    assert decision.reason == "opted_out"


def test_missing_consent_is_reported(rules: dict[str, Any]) -> None:
    decision = _check(rules, has_consent=False)
    assert decision.eligible is False
    assert decision.reason == "no_consent"


def test_messenger_requires_a_verified_identity_link(rules: dict[str, Any]) -> None:
    decision = _check(rules, channel="messenger", has_verified_identity=False)
    assert decision.eligible is False
    assert decision.reason == "no_verified_identity"


def test_messenger_is_not_eligible_outside_the_free_reply_window(rules: dict[str, Any]) -> None:
    decision = _check(rules, channel="messenger", within_free_reply_window=False)
    assert decision.eligible is False
    assert decision.reason == "outside_free_reply_window"


def test_whatsapp_requires_an_approved_template(rules: dict[str, Any]) -> None:
    decision = _check(rules, channel="whatsapp", requires_template=True)
    assert decision.eligible is False
    assert decision.reason == "outside_free_reply_window"


def test_whatsapp_passes_with_an_approved_template(rules: dict[str, Any]) -> None:
    decision = _check(
        rules,
        channel="whatsapp",
        requires_template=True,
        has_approved_template=True,
    )
    assert decision.eligible is True


def test_missing_contact_value_is_reported(rules: dict[str, Any]) -> None:
    decision = _check(rules, has_contact_value=False)
    assert decision.eligible is False
    assert decision.reason == "no_valid_contact_value"


def test_contact_value_is_reported_after_consent(rules: dict[str, Any]) -> None:
    """Consent is the more fundamental blocker, so it wins the report."""
    decision = _check(rules, has_consent=False, has_contact_value=False)
    assert decision.reason == "no_consent"


def test_the_reason_is_a_code_that_fits_the_skip_reason_column(
    rules: dict[str, Any],
) -> None:
    """The reason lands in ``outbound_messages.skip_reason``, a String(32).

    The sentence in the config is 40-odd characters, so storing it there would
    overflow the column. The code is what gets stored; the sentence is looked up
    separately for display.
    """
    for key in rules["skip_reasons"]:
        assert len(key) <= 32, f"skip reason code '{key}' does not fit the column"


def test_the_sentence_is_available_for_display(rules: dict[str, Any]) -> None:
    """The human-readable sentence is one lookup away from the code."""
    decision = _check(rules, opted_out=True)
    assert decision.reason == "opted_out"
    assert reason_text(rules, decision.reason) == rules["skip_reasons"]["opted_out"]


def test_every_rule_key_is_one_the_engine_reads(rules: dict[str, Any]) -> None:
    """A rule key the engine does not recognise is a rule that never fires.

    A typo in the config is silent: the channel simply becomes permissive. This
    pins the set of keys the engine understands.
    """
    known = {
        "requires_consent",
        "requires_verified_identity_link",
        "requires_approved_template",
        "requires_authenticated_domain",
        "max_message_length",
        "can_reach_unresponsive_customer",
        "free_reply_window_hours",
        "honours_stop_keyword",
        "notes",
    }
    for channel, channel_rules in rules["channels"].items():
        unknown = set(channel_rules) - known
        assert not unknown, f"channel '{channel}' has unrecognised rules: {unknown}"


def test_messenger_is_ineligible_without_a_verified_link(rules: dict[str, Any]) -> None:
    """The whole point of the ``requires_verified_identity_link`` rule."""
    assert rules["channels"]["messenger"]["requires_verified_identity_link"] is True
    decision = _check(rules, channel="messenger", has_verified_identity=False)
    assert decision.eligible is False
    assert decision.reason == "no_verified_identity"
