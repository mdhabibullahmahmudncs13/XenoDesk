"""Mount the HTTP MCP servers into the API process.

One process, one auth chain: the servers are mounted at ``/mcp/<server>`` so a client
points at a stable URL and the tenant checks are the same ones every endpoint uses.
Every server is stateless and answers JSON, because each call is a single request that
re-authenticates — there is no session to keep warm.

``python -m xenovarients.platform.mcp.faq_server`` is the one exception: it runs over
stdio as its own process.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from typing import Any, cast

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Mount

from xenovarients.platform.mcp.customer_genome.server import server as customer_genome
from xenovarients.platform.mcp.meta_ads.server import server as meta_ads
from xenovarients.platform.mcp.restock.server import server as restock
from xenovarients.platform.mcp.reviews.server import server as reviews
from xenovarients.platform.mcp.sourcing.server import server as sourcing

SERVERS: tuple[MCPServer, ...] = (customer_genome, restock, reviews, meta_ads, sourcing)

MCP_PREFIX = "/mcp"


def _http_app(server: MCPServer) -> Starlette:
    return server.streamable_http_app(
        # Mounted under /mcp/<name>, so the sub-app owns "/" inside its mount.
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        # The API's own Bearer-token check is the auth here; DNS-rebinding host pinning
        # would reject legitimate hosts behind a proxy.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


def create_mcp_app() -> Starlette:
    """The Starlette app that holds every HTTP MCP server."""
    return Starlette(
        routes=[Mount(f"/{server.name}", app=_http_app(server)) for server in SERVERS]
    )


def mcp_lifespan(
    mcp_app: Starlette | None,
) -> Callable[[Any], AbstractAsyncContextManager[None]]:
    """A FastAPI lifespan that starts the mounted servers' session managers.

    A mounted sub-app's lifespan is not run by Starlette, and without it the streamable
    HTTP handler refuses every request. The API's lifespan therefore enters each one.
    """

    @asynccontextmanager
    async def lifespan(_: Any) -> AsyncIterator[None]:
        if mcp_app is None:
            yield
            return
        async with AsyncExitStack() as stack:
            for route in mcp_app.routes:
                if isinstance(route, Mount):
                    child = cast(Starlette, route.app)
                    await stack.enter_async_context(child.router.lifespan_context(child))
            yield

    return lifespan
