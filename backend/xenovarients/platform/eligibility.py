"""Channel eligibility rules (OD-05).

The rules live in ``configs/channel_eligibility.json`` — data, not code — so a rule
change is a config edit rather than a release.

The critical property: **eligibility is evaluated at send time, not at schedule
time.** A recipient eligible when the batch was previewed may be ineligible by the
time the batch fires, because the customer opted out, or the provider's free-reply
window closed in between. The send path re-checks and skips with a recorded reason.

This module is pure: it takes the rules and the facts and returns a decision. It
does not touch the database, which is what makes it testable in isolation.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parents[3] / "configs"
CONFIG_FILE = CONFIG_DIR / "channel_eligibility.json"


@dataclass(frozen=True)
class EligibilityDecision:
    """Whether a message may go out, and why not if it may not."""

    eligible: bool
    reason: str | None = None

    @classmethod
    def ok(cls) -> "EligibilityDecision":
        return cls(eligible=True)


def _skip(rules: dict[str, Any], key: str) -> EligibilityDecision:
    return EligibilityDecision(eligible=False, reason=_reason(rules, key))


def load_rules(path: Path | None = None) -> dict[str, Any]:
    """Read the channel eligibility rules."""
    target = path or CONFIG_FILE
    data: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
    return data


def _reason(rules: dict[str, Any], key: str) -> str:
    reasons = rules.get("skip_reasons", {})
    return str(reasons.get(key, key))


def check(
    rules: dict[str, Any],
    *,
    channel: str,
    has_consent: bool,
    has_verified_identity: bool,
    opted_out: bool,
    has_contact_value: bool,
    channel_enabled: bool,
    within_free_reply_window: bool = True,
    requires_template: bool = False,
    has_approved_template: bool = False,
) -> EligibilityDecision:
    """Decide whether a message may be sent on a channel right now.

    The order matters: the most fundamental blocker is reported first, because it is
    the one the operator can act on. A recipient with no consent and no phone number
    should be told "no consent" — that is the reason to fix — not "invalid address".
    """
    channel_rules = rules.get("channels", {}).get(channel)
    if channel_rules is None:
        return _skip(rules, "channel_not_enabled")

    if not channel_enabled:
        return _skip(rules, "channel_not_enabled")

    if opted_out:
        return _skip(rules, "opted_out")

    if channel_rules.get("requires_consent") and not has_consent:
        return _skip(rules, "no_consent")

    if channel_rules.get("requires_verified_identity_link") and not has_verified_identity:
        return _skip(rules, "no_verified_identity")

    if channel_rules.get("requires_approved_template") and not has_approved_template:
        return _skip(rules, "outside_free_reply_window")

    if not within_free_reply_window:
        return _skip(rules, "outside_free_reply_window")

    if not has_contact_value:
        return _skip(rules, "no_valid_contact_value")

    return EligibilityDecision.ok()
