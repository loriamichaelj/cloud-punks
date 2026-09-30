"""One factory that wires the shared cross-cutting contract into a FastAPI app (section 8).

Every service calls ``create_service_app`` so logging, correlation ids, metrics, error shape,
health and ``/metrics`` cannot drift between services.

Middleware order matters: ``CorrelationMiddleware`` is outermost so every log line and error
response, including those from the metrics layer and exception handlers, carries the id.
"""

from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI
from prometheus_client import CollectorRegistry, GCCollector, PlatformCollector, ProcessCollector

from retail_common.config import BaseServiceSettings
from retail_common.errors import install_error_handlers
from retail_common.health import ReadinessCheck, build_health_router
from retail_common.logging import CorrelationMiddleware, configure_logging
from retail_common.metrics import EventMetrics, HttpMetrics, MetricsMiddleware, build_metrics_router


def create_service_app(
    settings: BaseServiceSettings,
    *,
    readiness_checks: Sequence[ReadinessCheck] = (),
    registry: CollectorRegistry | None = None,
    **fastapi_kwargs: Any,
) -> FastAPI:
    configure_logging(settings.service_name, settings.environment, settings.log_level)

    if registry is None:
        registry = CollectorRegistry()
        ProcessCollector(registry=registry)
        PlatformCollector(registry=registry)
        GCCollector(registry=registry)

    app = FastAPI(title=settings.service_name, **fastapi_kwargs)
    app.state.settings = settings
    app.state.registry = registry
    app.state.event_metrics = EventMetrics(registry)
    http_metrics = HttpMetrics(registry)

    install_error_handlers(app)
    app.include_router(build_health_router(readiness_checks))
    app.include_router(build_metrics_router(registry))
    app.add_middleware(MetricsMiddleware, metrics=http_metrics)
    app.add_middleware(CorrelationMiddleware)
    return app
