"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from xenovarients.api import auth, bubbles, events, genome, notifications, webhooks
from xenovarients.api.errors import register_exception_handlers
from xenovarients.api.idempotency import IdempotencyMiddleware
from xenovarients.api.middleware import RequestContextMiddleware
from xenovarients.core.config import get_settings
from xenovarients.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Xenovarients API",
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
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id", "Idempotent-Replay"],
    )

    register_exception_handlers(app)
    app.include_router(auth.router)
    app.include_router(events.router)
    app.include_router(bubbles.router)
    app.include_router(genome.router)
    app.include_router(notifications.router)
    app.include_router(webhooks.router)

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

    return app


app = create_app()
