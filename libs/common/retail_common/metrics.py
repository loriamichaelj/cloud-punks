"""Prometheus metrics shared by all services (DESIGN.md section 8).

Metrics live on an explicit ``CollectorRegistry`` rather than the process-global one, so every
app (and every test) gets its own and there are no duplicate-registration errors. Service-specific
metrics (outbox, orders, cache) are added by the service that owns them.

Label values are bounded: ``route`` is the route *template* (``/api/v1/orders/{order_id}``),
never the raw path, and requests that match no route use the fixed label ``unmatched``.
"""

import time

from fastapi import APIRouter, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.types import ASGIApp, Message, Receive, Scope, Send

UNMATCHED_ROUTE = "unmatched"
METRICS_PATH = "/metrics"


class HttpMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.requests_total = Counter(
            "http_requests_total",
            "HTTP requests by method, route template and status code.",
            ["method", "route", "status"],
            registry=registry,
        )
        self.request_duration = Histogram(
            "http_request_duration_seconds",
            "HTTP request latency by method and route template.",
            ["method", "route"],
            registry=registry,
        )


class EventMetrics:
    """Counters for event publishing and consumption (labels: event_type, outcome)."""

    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    POISON = "poison"
    ERROR = "error"

    def __init__(self, registry: CollectorRegistry) -> None:
        self.published_total = Counter(
            "events_published_total",
            "Events accepted by the event bus.",
            ["event_type"],
            registry=registry,
        )
        self.publish_failures_total = Counter(
            "events_publish_failures_total",
            "Events the event bus rejected or that could not be sent.",
            ["event_type"],
            registry=registry,
        )
        self.consumed_total = Counter(
            "events_consumed_total",
            "Events consumed by outcome: processed, duplicate, poison or error.",
            ["event_type", "outcome"],
            registry=registry,
        )
        self.handler_duration = Histogram(
            "event_handler_duration_seconds",
            "Time spent in an event handler.",
            ["event_type"],
            registry=registry,
        )


class MetricsMiddleware:
    """Pure ASGI middleware recording request count and latency."""

    def __init__(self, app: ASGIApp, metrics: HttpMetrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == METRICS_PATH:
            await self.app(scope, receive, send)
            return

        status = 500  # stays 500 if the app raises before sending a response
        started = time.perf_counter()

        async def capture_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        finally:
            # The router sets scope["route"] on this same dict while handling the request.
            route = getattr(scope.get("route"), "path", UNMATCHED_ROUTE)
            method = scope["method"]
            self.metrics.requests_total.labels(method, route, str(status)).inc()
            self.metrics.request_duration.labels(method, route).observe(
                time.perf_counter() - started
            )


def build_metrics_router(registry: CollectorRegistry) -> APIRouter:
    router = APIRouter()

    @router.get(METRICS_PATH, include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    return router
