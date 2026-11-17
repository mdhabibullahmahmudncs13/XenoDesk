"""Config files are read at runtime by services — validate they load and agree with
the settings module.

These are JSON, not Python, so nothing checks them at import. A typo in a rule name
would otherwise surface as a runtime lookup miss in the middle of a send.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from xenovarients.core.config import get_settings

CONFIGS = Path(__file__).resolve().parents[3] / "configs"


def _load(name: str) -> dict[str, Any]:
    path = CONFIGS / name
    assert path.exists(), f"missing config: {path}"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_channel_eligibility_loads_and_covers_every_channel():
    config = _load("channel_eligibility.json")
    channels = config["channels"]
    # Every channel the models know about must have a rule set, or the eligibility
    # engine silently treats it as unrestricted.
    for channel in ("email", "sms", "messenger", "whatsapp"):
        assert channel in channels, f"no eligibility rules for {channel}"
        assert "requires_consent" in channels[channel]


def test_channel_eligibility_skip_reasons_match_channel_rules():
    config = _load("channel_eligibility.json")
    # A rule that can skip a recipient needs a reason string to show in the preview.
    assert config["skip_reasons"]
    assert "no_consent" in config["skip_reasons"]


def test_qualifying_order_rules_agree_with_settings_defaults():
    config = _load("qualifying_order_rules.json")
    assert config["version"]
    assert config["qualifying_statuses"]
    assert "cancelled" in config["excluded_statuses"]
    # The rule file is the source of truth for the rule version stamped on each order.
    assert config["definitions"]["repeat_buyer"]["min_qualifying_orders"] == 2


def test_review_defaults_agree_with_settings_defaults():
    config = _load("review_defaults.json")
    settings = get_settings()
    assert config["delay_days"] == settings.review_delay_days
    assert config["send_window_start"] == settings.review_send_window_start
    assert config["send_window_end"] == settings.review_send_window_end
    assert config["reply_window_days"] == settings.review_reply_window_days


@pytest.mark.parametrize(
    "name",
    ["channel_eligibility.json", "qualifying_order_rules.json", "review_defaults.json"],
)
def test_every_config_is_valid_json(name):
    json.loads((CONFIGS / name).read_text(encoding="utf-8"))
