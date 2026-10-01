"""Error model and exception handlers shared by all services (DESIGN.md section 4).

Every error response has the shape::

    {"error": {"code": "OUT_OF_STOCK", "message": "...", "correlation_id": "..."}}

Clients never see exception text from unexpected failures, and validation errors never echo the
submitted values (they may be customer data).
"""

from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any, cast

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from retail_common.logging import CORRELATION_HEADER, get_correlation_id

_log = structlog.get_logger("retail_common.errors")

MAX_VALIDATION_DETAILS = 5


class ErrorBody(BaseModel):
    code: str
    message: str
    correlation_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    """Base class for errors that map to an HTTP response."""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.headers = headers or {}


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class UnprocessableError(AppError):
    status_code = 422
    code = "UNPROCESSABLE"


class ServiceUnavailableError(AppError):
    """503 with ``Retry-After`` so clients back off instead of hammering."""

    status_code = 503
    code = "SERVICE_UNAVAILABLE"

    def __init__(self, message: str, *, code: str | None = None, retry_after_s: int = 1) -> None:
        super().__init__(message, code=code, headers={"Retry-After": str(retry_after_s)})


class UpstreamUnavailableError(ServiceUnavailableError):
    """A synchronous dependency (another service) is unreachable or returned 5xx."""

    code = "UPSTREAM_UNAVAILABLE"


class PoisonMessage(Exception):
    """A message that can never succeed (malformed or invalid). Never retried in-process."""


def describe_validation_errors(errors: Sequence[Mapping[str, Any]], limit: int = 5) -> str:
    """Summarize pydantic errors as ``path: message`` pairs, never including input values."""
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in errors[:limit]
    )


def error_response(
    status_code: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, correlation_id=get_correlation_id())
    )
    return JSONResponse(body.model_dump(), status_code=status_code, headers=headers)


def store_unavailable_response(message: str) -> JSONResponse:
    """The one response every service gives when its backing store cannot serve a request.

    503 with ``Retry-After`` and a generic message (driver exception text can contain hostnames),
    never a 500: callers retry a 503 and back off, and the outage is not a bug in the service.
    """
    return error_response(503, "STORE_UNAVAILABLE", message, {"Retry-After": "1"})


def _http_status_code_name(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).name
    except ValueError:
        return "HTTP_ERROR"


# Starlette types exception handlers as taking a bare ``Exception``; each handler is registered
# for exactly one exception class, so ``cast`` only narrows what the registry already guarantees.
async def _handle_app_error(_request: Request, exc: Exception) -> JSONResponse:
    error = cast("AppError", exc)
    if error.status_code >= 500:
        _log.warning("app_error", code=error.code, status=error.status_code, error=error.message)
    return error_response(error.status_code, error.code, error.message, error.headers)


async def _handle_validation_error(_request: Request, exc: Exception) -> JSONResponse:
    error = cast("RequestValidationError", exc)
    message = describe_validation_errors(error.errors(), MAX_VALIDATION_DETAILS)
    return error_response(422, "VALIDATION_ERROR", message or "invalid request")


async def _handle_http_exception(_request: Request, exc: Exception) -> JSONResponse:
    error = cast("StarletteHTTPException", exc)
    return error_response(
        error.status_code,
        _http_status_code_name(error.status_code),
        str(error.detail),
        dict(error.headers) if error.headers else None,
    )


async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
    _log.error("unhandled_exception", exc_info=exc)
    # Starlette runs this handler in its outermost layer, outside CorrelationMiddleware, so the
    # middleware never sees this response and cannot add the header itself.
    correlation_id = get_correlation_id()
    headers = {CORRELATION_HEADER: correlation_id} if correlation_id else None
    return error_response(500, "INTERNAL_ERROR", "internal server error", headers)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unexpected)
