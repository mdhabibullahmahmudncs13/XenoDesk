"""The read-only MCP contract.

These tests hold the parts that must not drift: the seven server names and twenty-three
tool names, that no tool takes a tenant, that no tool is a write, and that a missing value
is reported as missing rather than as zero. They need no database — the DB-backed
behaviour is covered by the integration suite.
"""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from xenovarients.core.config import get_settings
from xenovarients.platform.mcp import external
from xenovarients.platform.mcp.app import SERVERS, create_mcp_app, mcp_lifespan
from xenovarients.platform.mcp.faq_server import ENV_BUSINESS_ID, _business_id
from xenovarients.platform.mcp.faq_server import server as faq_server
from xenovarients.platform.mcp.shared import ToolError, not_found, result, unavailable

EXTERNAL_ENV = (
    "MCP_OUTBOUND_GATEWAY_URL",
    "MCP_OUTBOUND_GATEWAY_TOKEN",
    "MCP_DEMAND_SIGNAL_URL",
    "MCP_DEMAND_SIGNAL_TOKEN",
    "MCP_SOCIAL_LISTENING_URL",
    "MCP_SOCIAL_LISTENING_TOKEN",
    "MCP_ANALYTICS_EXPORT_URL",
    "MCP_ANALYTICS_EXPORT_TOKEN",
)


@pytest.fixture(autouse=True)
def _no_external_sources_configured(monkeypatch):
    """Integration is opt-in; a stray .env must not change what these tests assert."""
    for name in EXTERNAL_ENV:
        monkeypatch.setenv(name, "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

EXPECTED_TOOLS = {
    "customer_genome": {
        "get_customer_history",
        "list_repeat_buyers",
        "get_returning_bubbles",
        "link_identity",
        "resolve_customer",
    },
    "restock": {
        "list_waiting_lists",
        "list_restock_events",
        "preview_batch",
        "check_eligibility",
        "list_sendable_batches",
        "get_batch_status",
    },
    "reviews": {
        "list_reviews",
        "review_consent",
        "preview_card",
        "get_social_sentiment",
    },
    "meta_ads": {"search_ads", "get_ad_details", "rank_ads"},
    "sourcing": {"get_market_prices", "refresh_demand", "get_enriched_demand"},
    "analytics": {"export_snapshot"},
    "faq": {"match_faq"},
}


async def test_every_server_exposes_its_documented_tools():
    names = {server.name for server in SERVERS} | {faq_server.name}
    assert names == set(EXPECTED_TOOLS)

    registered: dict[str, set[str]] = {}
    for server in (*SERVERS, faq_server):
        registered[server.name] = {tool.name for tool in await server.list_tools()}

    assert registered == EXPECTED_TOOLS
    assert sum(len(tools) for tools in registered.values()) == 23


async def test_no_tool_accepts_a_tenant_argument():
    """business_id comes from the token, never from a caller-supplied argument."""
    for server in (*SERVERS, faq_server):
        for tool in await server.list_tools():
            properties = set(tool.input_schema.get("properties", {}))
            assert "business_id" not in properties, tool.name


async def test_every_tool_explains_itself():
    for server in (*SERVERS, faq_server):
        for tool in await server.list_tools():
            assert tool.description, tool.name


def test_expected_failure_is_data_not_a_crash():
    payload = ToolError("forbidden", "nope", extra={"actual_role": "staff"}).as_result()
    assert payload == {
        "read_only": True,
        "ok": False,
        "error": "forbidden",
        "detail": "nope",
        "actual_role": "staff",
    }


def test_missing_data_is_explicit_and_carries_no_fabricated_zero():
    missing = not_found("customer", "abc")
    assert missing["found"] is False
    assert missing["id"] == "abc"
    assert "0" not in missing.values()

    panel = unavailable("demand", "no_research_yet")
    assert panel == {"available": False, "field": "demand", "reason": "no_research_yet"}


def test_a_result_is_always_marked_read_only():
    assert result(count=0)["read_only"] is True


def test_faq_requires_the_tenant_from_the_environment(monkeypatch):
    monkeypatch.delenv(ENV_BUSINESS_ID, raising=False)
    with pytest.raises(ToolError) as missing:
        _business_id()
    assert missing.value.code == "not_configured"

    monkeypatch.setenv(ENV_BUSINESS_ID, "not-a-uuid")
    with pytest.raises(ToolError):
        _business_id()


def test_an_unconfigured_external_capability_explains_itself():
    panel = external.status("demand_signal")
    assert panel["available"] is False
    assert panel["reason"] == "not_configured"
    assert panel["capability"] == "demand_signal"
    assert "MCP_DEMAND_SIGNAL_URL" in panel["detail"]
    assert "token" not in panel


async def test_an_unconfigured_source_makes_no_request():
    payload = await external.call("social_listening", "get_sentiment", {"keyword": "x"})
    assert payload == {**external.status("social_listening"), "tool": "get_sentiment"}
    assert payload["available"] is False


async def test_a_third_party_write_tool_is_out_of_reach(monkeypatch):
    """The allowlist is checked before connecting: the URL here answers nothing."""
    monkeypatch.setenv("MCP_ANALYTICS_EXPORT_URL", "http://127.0.0.1:9/mcp")
    get_settings.cache_clear()

    payload = await external.call("analytics_export", "drop_table", {})
    assert payload["available"] is False
    assert payload["reason"] == "tool_not_allowed"
    assert "export_snapshot" in payload["detail"]


def test_an_unknown_capability_is_a_programming_error():
    with pytest.raises(ValueError):
        external.capability("not_a_source")


def _client() -> TestClient:
    mcp_app = create_mcp_app()
    app = FastAPI(lifespan=mcp_lifespan(mcp_app))
    app.mount("/mcp", mcp_app)
    return TestClient(app)


def test_each_mounted_server_has_a_health_route():
    with _client() as client:
        for name in EXPECTED_TOOLS:
            if name == "faq":
                continue
            response = client.get(f"/mcp/{name}/health")
            assert response.status_code == 200, name
            assert response.json() == {"status": "ok", "server": name, "read_only": True}


def test_tools_list_is_served_over_http():
    with _client() as client:
        response = client.post(
            "/mcp/reviews/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert response.status_code == 200
        names = {tool["name"] for tool in response.json()["result"]["tools"]}
        assert names == EXPECTED_TOOLS["reviews"]


def test_a_tool_call_without_a_token_is_refused():
    with _client() as client:
        response = client.post(
            "/mcp/reviews/",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "list_reviews", "arguments": {}},
            },
        )
        assert response.status_code == 200
        body = response.json()["result"]["content"][0]["text"]
        assert '"ok": false' in body
        assert '"error": "unauthorized"' in body
        assert "reviews" not in body
