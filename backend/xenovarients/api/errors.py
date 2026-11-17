"""RFC 7807 problem+json errors.

Every error response has the same shape: ``{type, title, status, detail, code, request_id}``.
``code`` is the stable machine-readable value the frontend switches on.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorCode:
    """Stable error codes. The frontend branches on these, never on ``detail`` text."""

    bad_request = "bad_request"
    validation_failed = "validation_failed"
    unauthorized = "unauthorized"
    forbidden = "forbidden"
    not_found = "not_found"
    conflict = "conflict"
    idempotency_conflict = "idempotency_conflict"
    eligibility_failed = "eligibility_failed"
    unavailable = "unavailable"
    internal_error = "internal_error"


_STATUS_TO_CODE = {
    400: ErrorCode.bad_request,
    401: ErrorCode.unauthorized,
    403: ErrorCode.forbidden,
    404: ErrorCode.not_found,
    409: ErrorCode.conflict,
    422: ErrorCode.validation_failed,
    503: ErrorCode.unavailable,
}

PROBLEM_BASE = "https://xenovarients.com/problems/"


class AppError(Exception):
    """Base class for errors that should become a problem+json response."""

    code = ErrorCode.internal_error
    status_code = 500
    title = "Internal Server Error"

    def __init__(self, detail: str, *, extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or {}


class BadRequest(AppError):
    code = ErrorCode.bad_request
    status_code = 400
    title = "Bad Request"


class NotFound(AppError):
    code = ErrorCode.not_found
    status_code = 404
    title = "Not Found"


class Forbidden(AppError):
    code = ErrorCode.forbidden
    status_code = 403
    title = "Forbidden"


class Unauthorized(AppError):
    code = ErrorCode.unauthorized
    status_code = 401
    title = "Unauthorized"


class Conflict(AppError):
    code = ErrorCode.conflict
    status_code = 409
    title = "Conflict"


class IdempotencyConflict(AppError):
    code = ErrorCode.idempotency_conflict
    status_code = 409
    title = "Idempotency Conflict"


class EligibilityFailed(AppError):
    code = ErrorCode.eligibility_failed
    status_code = 422
    title = "Eligibility Failed"


class Unavailable(AppError):
    """Used for the 'no fabricated data' contract: the data exists but is not available yet."""

    code = ErrorCode.unavailable
    status_code = 503
    title = "Unavailable"


def _request_id(request: Request) -> str | None:
    from xenovarients.core.logging import request_id_var

    return request_id_var.get()


def problem_response(
    request: Request,
    *,
    status: int,
    title: str,
    detail: str,
    code: str,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"{PROBLEM_BASE}{code}",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "request_id": _request_id(request),
    }
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status, content=body, media_type="application/problem+json")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return problem_response(
            request,
            status=exc.status_code,
            title=exc.title,
            detail=exc.detail,
            code=exc.code,
            extra=exc.extra,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return problem_response(
            request,
            status=422,
            title="Validation Failed",
            detail="The request body or parameters failed validation.",
            code=ErrorCode.validation_failed,
            extra={"errors": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.internal_error)
        return problem_response(
            request,
            status=exc.status_code,
            title=exc.detail or "Error",
            detail=str(exc.detail),
            code=code,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Log with the request id; the client gets no internals.
        import logging

        logging.getLogger("xenovarients.api").exception(
            "unhandled error", extra={"request_id": _request_id(request)}
        )
        return problem_response(
            request,
            status=500,
            title="Internal Server Error",
            detail="An unexpected error occurred.",
            code=ErrorCode.internal_error,
        )
