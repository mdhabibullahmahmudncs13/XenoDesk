"""Agent Workspace routing and safety rules."""

import pytest

from xenovarients.platform.workspace import (
    TOOL_REGISTRY,
    blocked_intent,
    normalise,
)


def test_normaliser_handles_case_punctuation_and_unicode():
    assert normalise("  Delivery?!  ") == "delivery"
    assert normalise("বাংলা") == "বাংলা"


@pytest.mark.parametrize("question", ["delete that order", "please send a message"])
def test_write_intents_are_blocked(question):
    assert blocked_intent(question)


def test_tool_registry_is_read_only():
    assert TOOL_REGISTRY
    assert all(not name.startswith(("write_", "delete_", "update_")) for name in TOOL_REGISTRY)
