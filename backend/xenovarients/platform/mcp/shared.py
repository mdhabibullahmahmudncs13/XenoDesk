"""Shared plumbing for XenoDesk's read-only MCP servers.

Three rules, enforced here rather than repeated in every tool:

* **Read-only.** A tool gets a session that is rolled back on exit and never committed,
  so a bug in a tool cannot leave a write behind. Writes stay on the owner-confirmed
  HTTP endpoints.
* **Tenant-scoped.** ``business_id`` is re-derived from the bearer token and
  ``X-Business-Id`` header on *every* tool call, using the same chain as the HTTP API.
  No tool takes a tenant argument, so a caller cannot name someone else's business.
* **No invented data.** A missing row is ``found: false``; a missing panel is
  ``available: false`` with a reason. Never a zero that reads like a measurement.

The servers are the official MCP SDK (``mcp`` 2.x, ``MCPServer``), mounted into the API
process. Each one is stateless HTTP: every POST re-authenticates and re-derives the
tenant, which is what makes rule two hold per call rather than per session.
"""

import inspect
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, TypeVar, cast

from mcp.server.mcpserver import Context, MCPServer
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from xenovarients.api.deps import Principal, resolve_principal
from xenovarients.api.errors import AppError
from xenovarients.db.session import SessionLocal
from xenovarients.db.tenant import bind_tenant, clear_tenant, install_tenant_filter, reset_tenant
from xenovarients.models.tenancy import Role

logger = logging.getLogger("xenovarients.mcp")

STAFF_ROLES: tuple[str, ...] = (Role.owner.value, Role.admin.value, Role.staff.value)
ADMIN_ROLES: tuple[str, ...] = (Role.owner.value, Role.admin.value)

F = TypeVar("F", bound=Callable[..., Awaitable[dict[str, Any]]])


class ToolError(Exception):
    """An expected refusal, returned to the client as data rather than a crash."""

    def __init__(self, code: str, detail: str, *, extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.extra = extra or {}

    def as_result(self) -> dict[str, Any]:
        return {
            "read_only": True,
            "ok": False,
            "error": self.code,
            "detail": self.detail,
            **self.extra,
        }


def read_only(server: MCPServer) -> Callable[[F], F]:
    """Register ``fn`` as a tool whose expected failures become explicit results.

    Unexpected exceptions are deliberately left to the SDK: a bug should surface as a
    failed tool call, not be dressed up as an answer.
    """

    def register(fn: F) -> F:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                return await fn(*args, **kwargs)
            except ToolError as exc:
                return exc.as_result()
            except AppError as exc:
                return ToolError(exc.code, exc.detail, extra=exc.extra).as_result()
            except ValueError as exc:
                return ToolError("bad_request", str(exc)).as_result()

        wrapper.__doc__ = inspect.cleandoc(fn.__doc__ or "")
        server.add_tool(wrapper, name=fn.__name__, description=wrapper.__doc__)
        return fn

    return register


def headers_of(ctx: Context) -> Mapping[str, str]:
    """The inbound HTTP headers, lower-cased by the ASGI server."""
    return {key.lower(): value for key, value in (ctx.headers or {}).items()}


async def authenticate(ctx: Context, *, roles: tuple[str, ...] = STAFF_ROLES) -> Principal:
    """The caller's principal, or a refusal.

    The token → membership chain is the API's own, so a revoked role or a business the
    user does not belong to fails here exactly as it would on an endpoint.
    """
    headers = headers_of(ctx)
    try:
        principal = await resolve_principal(
            authorization=headers.get("authorization"),
            x_business_id=headers.get("x-business-id"),
        )
    except AppError as exc:
        raise ToolError(exc.code, exc.detail, extra=exc.extra) from exc

    if principal.role not in roles:
        raise ToolError(
            "forbidden",
            f"This tool requires role: {', '.join(roles)}.",
            extra={"required_roles": list(roles), "actual_role": principal.role},
        )
    return principal


@asynccontextmanager
async def tenant_session(business_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """A tenant-bound session that is always rolled back."""
    async with SessionLocal() as session:
        install_tenant_filter(session)
        try:
            await bind_tenant(session, str(business_id))
            yield session
        finally:
            await session.rollback()
            await clear_tenant(session)
            reset_tenant()


def build_server(*, name: str, title: str, instructions: str) -> MCPServer:
    """One MCP server with a description the client shows to its user.

    Also exposes ``/health`` beside the MCP endpoint, so a probe can tell a mounted
    server from a missing route without holding a token.
    """
    server = MCPServer(
        name=name,
        title=title,
        description=instructions,
        instructions=instructions,
        version="0.1.0",
    )

    @server.custom_route("/health", methods=["GET"])  # type: ignore[misc]
    async def _health(_: Request) -> Response:
        return JSONResponse({"status": "ok", "server": name, "read_only": True})

    return server


def result(**data: Any) -> dict[str, Any]:
    """A successful read-only answer."""
    return {"read_only": True, "ok": True, **data}


def not_found(kind: str, identifier: Any) -> dict[str, Any]:
    """A resource that does not exist in this tenant — never an empty stand-in."""
    return {
        "read_only": True,
        "ok": True,
        "found": False,
        "kind": kind,
        "id": str(identifier),
        "reason": f"No {kind} with that id exists for this business.",
    }


def unavailable(field: str, reason: str, **extra: Any) -> dict[str, Any]:
    """A value that exists in the product but has not been captured yet."""
    return {"available": False, "field": field, "reason": reason, **extra}


def iso(value: Any) -> str | None:
    """A timestamp as ISO-8601 text, or ``None``."""
    if value is None:
        return None
    return cast(str, value.isoformat())


def parse_uuid(value: str, *, kind: str = "id") -> uuid.UUID:
    """Parse a caller-supplied id, refusing rather than guessing."""
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise ToolError("bad_request", f"'{value}' is not a valid {kind}.") from exc
