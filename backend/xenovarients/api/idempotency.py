"""The Idempotency-Key middleware.

A request that carries an ``Idempotency-Key`` header has its response stored, and
a repeat of the same request replays that stored response instead of performing
the action again.

**The middleware runs outside the route**, so it cannot use the route's dependency
injection. It resolves the caller and the tenant itself, from the bearer token.

**Only successful, JSON responses are stored.** A 500 is not a result worth
replaying — the client should retry, and the retry should get a fresh attempt. A
4xx is stored too, because a 4xx is a deterministic answer to a deterministic
request and replaying it is correct.

**A different body with the same key is a 409.** Replaying would perform the first
request's action for the second request's intent.
"""

import logging
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from xenovarients.api.errors import ErrorCode, problem_response
from xenovarients.core.security import decode_access_token
from xenovarients.db.session import SessionLocal
from xenovarients.db.tenant import bind_tenant, clear_tenant, install_tenant_filter, reset_tenant
from xenovarients.platform.idempotency import (
    IdempotencyConflict as StoreConflict,
)
from xenovarients.platform.idempotency import (
    StoredResponse,
    as_stored,
    claim,
    fingerprint,
    parse_body,
    store_response,
)

logger = logging.getLogger(__name__)

# Only methods that create something are worth replaying.
REPLAYABLE_METHODS = frozenset({"POST", "PUT", "PATCH"})

# The header that tells the client the response was replayed rather than fresh.
REPLAY_HEADER = "Idempotent-Replay"


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Stores and replays responses for requests carrying an Idempotency-Key."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        key = getattr(request.state, "idempotency_key", None)
        if not key or request.method not in REPLAYABLE_METHODS:
            return await call_next(request)

        business_id = await self._business_id(request)
        if business_id is None:
            # Not authenticated: the route will reject it. Do not store anything —
            # a 401 is not a result worth replaying, and we have no tenant to
            # attribute the record to.
            return await call_next(request)

        body = await request.body()
        request._body = body  # noqa: SLF001 — the route still needs to read it
        endpoint = request.url.path
        request_fingerprint = fingerprint(request.method, endpoint, body)

        async with SessionLocal() as session:
            install_tenant_filter(session)
            try:
                await bind_tenant(session, str(business_id))
                try:
                    record, is_new = await claim(
                        session,
                        business_id=business_id,
                        key=key,
                        endpoint=endpoint,
                        request_fingerprint=request_fingerprint,
                    )
                except StoreConflict as exc:
                    await session.rollback()
                    return problem_response(
                        request,
                        status=409,
                        title="Idempotency Conflict",
                        detail=str(exc),
                        code=ErrorCode.idempotency_conflict,
                    )

                if not is_new:
                    # Snapshot before the rollback: the rollback expires the ORM
                    # instance, and reading it afterwards would need IO outside the
                    # greenlet.
                    stored = as_stored(record)
                    await session.rollback()
                    return self._replay(request, stored)

                response = await call_next(request)

                if self._is_storable(response):
                    await store_response(
                        session,
                        record=record,
                        status_code=response.status_code,
                        body=parse_body(self._body(response)),
                        headers={
                            "content-type": response.headers.get("content-type", ""),
                        },
                    )
                    await session.commit()
                else:
                    # A 500 or a non-JSON response is not a replayable result. Drop
                    # the record so a retry gets a fresh attempt.
                    await session.rollback()
                return response
            finally:
                await session.rollback()
                await clear_tenant(session)
                reset_tenant()

    def _replay(self, request: Request, stored: StoredResponse) -> Response:
        """Return the stored response for a repeated key."""
        from starlette.responses import JSONResponse
        from starlette.responses import Response as StarletteResponse

        headers = dict(stored.headers or {})
        headers[REPLAY_HEADER] = "true"

        if stored.status_code == 204:
            # A 204 has no body. Replaying it as a 200 with an empty JSON object
            # would tell the client something different about what happened.
            return StarletteResponse(status_code=204, headers=headers)

        return JSONResponse(
            status_code=stored.status_code,
            content=stored.body or {},
            headers=headers,
        )

    @staticmethod
    def _body(response: Response) -> bytes:
        """The response body, if it has one.

        A plain ``Response`` carries ``body``; a ``StreamingResponse`` — which is
        what a 204 becomes — does not, and has no body to store.
        """
        raw = getattr(response, "body", None)
        if raw is None:
            return b""
        return bytes(raw)

    @staticmethod
    def _is_storable(response: Response) -> bool:
        """Whether this response is worth storing for a later replay.

        A 5xx is not: the client should retry and get a fresh attempt, and
        replaying a server error would pin the client to a failure.

        A 204 has no body and no content type, but it is a perfectly good result to
        replay — the action succeeded, and repeating it should not succeed twice.
        """
        if response.status_code >= 500:
            return False
        if response.status_code == 204:
            return True
        content_type = response.headers.get("content-type", "")
        return content_type.startswith("application/json")

    @staticmethod
    async def _business_id(request: Request) -> str | None:
        """The tenant this request acts in, from the bearer token.

        Returns None when the request is not authenticated. The route will reject
        it; the middleware just does not try to store anything.
        """
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        try:
            claims = decode_access_token(token)
        except Exception:  # noqa: BLE001 — an invalid token is the route's problem
            return None
        business_id = claims.get("bid")
        if not business_id:
            return None
        return str(business_id)
