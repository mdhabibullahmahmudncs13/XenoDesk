"""Request-level middleware: correlation IDs, timing, and idempotency-key plumbing."""

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from xenovarients.api.errors import BadRequest, problem_response
from xenovarients.core.logging import request_id_var

REQUEST_ID_HEADER = "X-Request-Id"
IDEMPOTENCY_HEADER = "Idempotency-Key"
MAX_IDEMPOTENCY_KEY_LENGTH = 128


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, echoes it back, and logs the outcome.

    An inbound ``X-Request-Id`` is trusted (a gateway may set one) but sanitised to a
    bounded length so a caller cannot inject newlines into the logs.

    The ``Idempotency-Key`` header is validated here and attached to the request state.
    Endpoints that create a side effect read ``request.state.idempotency_key``; an
    invalid key is rejected outright rather than silently ignored, because a client
    that sends a malformed key believes it is protected against duplicate effects.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming[:128] if incoming else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            request.state.idempotency_key = self._idempotency_key(request)
            response = await call_next(request)
        except BadRequest as exc:
            # Middleware runs outside the route, so the app's exception handlers never
            # see this. Format the problem response here.
            response = problem_response(
                request,
                status=exc.status_code,
                title=exc.title,
                detail=exc.detail,
                code=exc.code,
                extra=exc.extra,
            )
        finally:
            request_id_var.reset(token)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
        return response

    @staticmethod
    def _idempotency_key(request: Request) -> str | None:
        raw = request.headers.get(IDEMPOTENCY_HEADER, "").strip()
        if not raw:
            return None
        if len(raw) > MAX_IDEMPOTENCY_KEY_LENGTH:
            raise BadRequest(
                f"{IDEMPOTENCY_HEADER} must be at most {MAX_IDEMPOTENCY_KEY_LENGTH} characters."
            )
        return raw
