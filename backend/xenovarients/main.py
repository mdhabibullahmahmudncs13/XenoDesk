"""FastAPI application factory."""

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient

from xenovarients.api import (
    ads,
    auth,
    bubbles,
    events,
    genome,
    notifications,
    restock,
    review_permissions,
    reviews,
    sourcing,
    webhooks,
    workspace,
)
from xenovarients.api.errors import register_exception_handlers
from xenovarients.api.idempotency import IdempotencyMiddleware
from xenovarients.api.middleware import RequestContextMiddleware
from xenovarients.core.config import get_settings
from xenovarients.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    # The MCP servers are an optional extra (``pip install -e ".[mcp]"``). Without it the
    # product is unchanged: same routes, same health checks, no import of the SDK.
    mcp_app = None
    lifespan = None
    try:
        import mcp.server.mcpserver  # noqa: F401 - presence check for the optional extra
    except ImportError:  # pragma: no cover - depends on the installed extras
        pass
    else:
        from xenovarients.platform.mcp.app import create_mcp_app, mcp_lifespan

        mcp_app = create_mcp_app()
        lifespan = mcp_lifespan(mcp_app)

    app = FastAPI(
        lifespan=lifespan,
        title="XenoDesk API",
        version="0.1.0",
        description=(
            "Customer Genome · Creator Commerce · Agent Workspace. "
            "All product endpoints are tenant-scoped; business_id is derived from the "
            "access token and never accepted from the request body."
        ),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    # Starlette wraps middleware in reverse order of addition: the last added is the
    # outermost. The idempotency middleware must run *inside* the request context
    # middleware, because it reads the validated Idempotency-Key off the request
    # state that the context middleware sets.
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        # Any loopback origin: the dev frontend is opened as localhost, 127.0.0.1 or [::1]
        # depending on how the server was reached, and a mismatch here shows up in the
        # browser as "Failed to fetch" rather than as a CORS error.
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id", "Idempotent-Replay"],
    )

    register_exception_handlers(app)
    app.include_router(auth.router)
    app.include_router(ads.router)
    app.include_router(workspace.router)
    app.include_router(events.router)
    app.include_router(bubbles.router)
    app.include_router(genome.router)
    app.include_router(notifications.router)
    app.include_router(restock.router)
    app.include_router(reviews.router)
    app.include_router(review_permissions.router)
    app.include_router(sourcing.router)
    app.include_router(webhooks.router)

    if mcp_app is not None:
        # /mcp/<server> — read-only tools, authenticated by the same bearer token.
        app.mount("/mcp", mcp_app)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["ops"])
    async def ready() -> dict[str, str]:
        """Checks the database round-trip. Used by the container healthcheck."""
        from sqlalchemy import text

        from xenovarients.db.session import engine

        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - the healthcheck only needs the reason
            return {"status": "degraded", "database": str(exc)[:200]}
        return {"status": "ok", "database": "ok"}

    @app.get("/health/dependencies", tags=["ops"])
    async def dependencies() -> dict[str, object]:
        """Report optional dependency status without making core readiness fail."""
        from xenovarients.core.config import get_settings
        from xenovarients.platform.realtime import get_redis

        settings = get_settings()
        result: dict[str, object] = {}
        redis = get_redis()
        try:
            await redis.ping()
            result["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001 - dependency status is explicit
            result["redis"] = f"degraded: {type(exc).__name__}"
        finally:
            await redis.aclose()

        mongo = AsyncIOMotorClient(settings.mongo_uri, serverSelectionTimeoutMS=1000)
        try:
            await mongo.admin.command("ping")
            result["mongo"] = "ok"
        except Exception as exc:  # noqa: BLE001 - dependency status is explicit
            result["mongo"] = f"degraded: {type(exc).__name__}"
        finally:
            mongo.close()

        try:
            async with httpx.AsyncClient(timeout=1) as client:
                response = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
            result["ollama"] = "ok"
        except (httpx.HTTPError, ValueError) as exc:
            result["ollama"] = f"degraded: {type(exc).__name__}"
        return {"status": "ok", "dependencies": result}

    return app


app = create_app()
