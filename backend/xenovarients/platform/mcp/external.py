"""Optional third-party MCP capabilities (see docs/future implementation/future-mcp-plan.md).

The four external sources the plan proposes — an outbound gateway, a demand signal, a
social-listening source and an analytics destination — are reached over MCP Streamable
HTTP with the SDK that is already pinned for the local servers. No vendor SDK is added,
because no vendor has been chosen yet; a URL is the only thing that changes when one is.

That is also why every answer here is a *panel*: an unconfigured source is
``available: false`` with ``reason: "not_configured"``, never an empty list or a zero.
A source that is slow, refuses or answers with prose is reported the same way, so a
broken third party degrades one tool call instead of failing it.

Each capability declares the tools this platform may call on it. A tool outside that
set is refused before any request is made: the third-party server may well expose write
tools, and the agent does not get to reach them through XenoDesk.
"""

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from xenovarients.core.config import get_settings

logger = logging.getLogger("xenovarients.mcp.external")

# A third-party call must not hold a chat turn open: the local answer is already there.
CALL_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class Capability:
    """One optional external source, its endpoint and the tools it may be asked for."""

    name: str
    title: str
    url: str | None
    token: str | None
    url_env: str
    tools: tuple[str, ...]

    @property
    def configured(self) -> bool:
        return bool(self.url)


def capability(name: str) -> Capability:
    """The capability's current configuration, or ``ValueError`` for an unknown name."""
    settings = get_settings()
    known = {
        "outbound_gateway": Capability(
            name="outbound_gateway",
            title="Outbound messaging gateway",
            url=(settings.mcp_outbound_gateway_url or "").strip() or None,
            token=settings.mcp_outbound_gateway_token,
            url_env="MCP_OUTBOUND_GATEWAY_URL",
            tools=("list_sendable_batches", "get_batch_status"),
        ),
        "demand_signal": Capability(
            name="demand_signal",
            title="Demand / product-discovery signal",
            url=(settings.mcp_demand_signal_url or "").strip() or None,
            token=settings.mcp_demand_signal_token,
            url_env="MCP_DEMAND_SIGNAL_URL",
            tools=("get_enriched_demand",),
        ),
        "social_listening": Capability(
            name="social_listening",
            title="Review / social-listening source",
            url=(settings.mcp_social_listening_url or "").strip() or None,
            token=settings.mcp_social_listening_token,
            url_env="MCP_SOCIAL_LISTENING_URL",
            tools=("get_sentiment", "list_social_mentions"),
        ),
        "analytics_export": Capability(
            name="analytics_export",
            title="Analytics / export destination",
            url=(settings.mcp_analytics_export_url or "").strip() or None,
            token=settings.mcp_analytics_export_token,
            url_env="MCP_ANALYTICS_EXPORT_URL",
            tools=("export_snapshot", "export_insights"),
        ),
    }
    try:
        return known[name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown external capability '{name}'. Known: {', '.join(sorted(known))}."
        ) from exc


def status(name: str) -> dict[str, Any]:
    """Whether this capability is configured. Makes no request and never reports a token."""
    item = capability(name)
    if not item.configured:
        return {
            "available": False,
            "capability": item.name,
            "title": item.title,
            "reason": "not_configured",
            "detail": f"Set {item.url_env} to enable the {item.title} source.",
        }
    return {
        "available": True,
        "capability": item.name,
        "title": item.title,
        "tools": list(item.tools),
    }


async def call(
    name: str,
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    timeout_seconds: float = CALL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Ask a configured third-party server for one read-only tool result.

    Always returns a panel: ``available`` says whether an answer arrived, and ``reason``
    says why not. A tool that is not on the capability's allowlist is refused without a
    request, so a write tool on the third-party server stays out of reach.
    """
    item = capability(name)
    if tool not in item.tools:
        return {
            "available": False,
            "capability": item.name,
            "tool": tool,
            "reason": "tool_not_allowed",
            "detail": f"{item.title} may be asked for: {', '.join(item.tools)}.",
        }
    if not item.configured:
        return {**status(name), "tool": tool}

    try:
        async with asyncio.timeout(timeout_seconds):
            payload, is_error = await _dispatch(item, tool, arguments or {})
    except TimeoutError:
        return {
            "available": False,
            "capability": item.name,
            "tool": tool,
            "reason": "timeout",
            "detail": f"No answer within {timeout_seconds:.0f}s; the local answer stands.",
        }
    except Exception as exc:  # noqa: BLE001 - a third party's failure is data, not a crash
        logger.warning("external %s/%s failed: %s", item.name, tool, exc)
        return {
            "available": False,
            "capability": item.name,
            "tool": tool,
            "reason": "source_unavailable",
            "detail": f"{exc.__class__.__name__}: {exc}"[:300],
        }

    panel: dict[str, Any] = {
        "available": not is_error,
        "capability": item.name,
        "tool": tool,
        "data": payload,
    }
    if is_error:
        panel["reason"] = "tool_error"
    return panel


async def _dispatch(
    item: Capability, tool: str, arguments: dict[str, Any]
) -> tuple[Any, bool]:
    """One Streamable HTTP round trip to the third-party server."""
    assert item.url is not None  # narrowed by the caller's configured check
    headers = {"Authorization": f"Bearer {item.token}"} if item.token else None
    http_client = create_mcp_http_client(headers=headers) if headers else None
    transport = streamable_http_client(item.url, http_client=http_client)

    async with contextlib.AsyncExitStack() as stack:
        if http_client is not None:
            # A caller-supplied client is not managed by the transport.
            await stack.enter_async_context(http_client)
        client = await stack.enter_async_context(Client(transport))
        result = await client.call_tool(tool, arguments)

    return _payload(result), bool(getattr(result, "isError", False))


def _payload(result: Any) -> Any:
    """The tool's answer: parsed JSON when the text is JSON, otherwise the text itself."""
    texts = [
        item.text
        for item in getattr(result, "content", ())
        if isinstance(getattr(item, "text", None), str) and item.text
    ]
    for text in texts:
        try:
            return json.loads(text)
        except ValueError:
            continue
    if texts:
        return {"text": "\n".join(texts)}
    return None
