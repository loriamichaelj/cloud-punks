"""structlog setup and the correlation-id / request-log middleware (DESIGN.md section 8).

Every log line is one JSON object with ``timestamp, level, service, environment, message,
correlation_id`` plus any bound fields (``event_id``, ``order_id``, ...). Standard-library
loggers (uvicorn, boto3, ...) are routed through the same renderer.

The correlation id lives in a ``ContextVar``. The ASGI middleware sets it per request and never
resets it: each request runs in its own task, and the last-resort 500 handler runs *outside*
every middleware, so a reset would drop the id from exactly the log line that matters most.
"""

import logging
import re
import sys
import time
from collections.abc import MutableMapping
from contextvars import ContextVar, Token
from typing import Any

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from ulid import ULID

CORRELATION_HEADER = "X-Correlation-ID"

# Inbound ids are echoed into logs and outbound headers, so accept only a safe charset.
_SAFE_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_QUIET_PATHS = ("/health/", "/metrics")

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_log = structlog.get_logger("retail_common.http")


def new_correlation_id() -> str:
    return str(ULID())


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def set_correlation_id(value: str) -> Token[str | None]:
    """Set the id; keep the returned token to restore the previous value with ``reset``."""
    return _correlation_id.set(value)


def reset_correlation_id(token: Token[str | None]) -> None:
    _correlation_id.reset(token)


def ensure_correlation_id() -> str:
    """Return the current correlation id, creating one if this context has none."""
    current = _correlation_id.get()
    if current is None:
        current = new_correlation_id()
        _correlation_id.set(current)
    return current


def is_valid_correlation_id(value: str) -> bool:
    return _SAFE_CORRELATION_ID.fullmatch(value) is not None


def _add_correlation_id(
    _logger: object, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    correlation_id = _correlation_id.get()
    if correlation_id is not None:
        event_dict.setdefault("correlation_id", correlation_id)
    return event_dict


def _rename_event_to_message(
    _logger: object, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    event_dict["message"] = event_dict.pop("event", "")
    return event_dict


def configure_logging(service_name: str, environment: str, level: str = "INFO") -> None:
    """Configure structlog and the root logger for JSON output on stdout. Safe to call twice."""

    def add_service(
        _logger: object, _method: str, event_dict: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        event_dict["service"] = service_name
        event_dict["environment"] = environment
        return event_dict

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        add_service,
        _add_correlation_id,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        cache_logger_on_first_use=False,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            _rename_event_to_message,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
    )
    handler = _StdoutHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


class _StdoutHandler(logging.Handler):
    """Writes to whatever ``sys.stdout`` is *at emit time*.

    A ``StreamHandler(sys.stdout)`` pins the stream object it saw at configuration time, which
    silently goes stale if the process (or a test runner) later replaces ``sys.stdout``.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stream = sys.stdout
            stream.write(self.format(record) + "\n")
            stream.flush()
        except Exception:  # noqa: BLE001 - logging must never raise; handleError reports it
            self.handleError(record)


class CorrelationMiddleware:
    """Pure ASGI middleware: correlation id in/out, plus one request log line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied = dict(scope["headers"]).get(CORRELATION_HEADER.lower().encode(), b"").decode()
        correlation_id = supplied if is_valid_correlation_id(supplied) else new_correlation_id()
        set_correlation_id(correlation_id)

        status = 500
        started = time.perf_counter()

        async def send_with_header(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((CORRELATION_HEADER.lower().encode(), correlation_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            route = scope.get("route")
            path = scope["path"]
            emit = _log.debug if path.startswith(_QUIET_PATHS) else _log.info
            emit(
                "request_completed",
                method=scope["method"],
                route=getattr(route, "path", "unmatched"),
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
