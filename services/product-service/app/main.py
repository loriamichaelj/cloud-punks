"""product-service application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine

from app.api.errors import install_domain_error_handlers
from app.api.routes import router
from app.cache import CacheMetrics, ValkeyProductCache
from app.config import Settings
from app.domain.ports import ProductCache, ProductRepository
from app.domain.service import ProductService
from app.repo.db import build_engine, ping
from app.repo.products import PostgresProductRepository
from retail_common.health import ReadinessCheck
from retail_common.metrics import build_registry
from retail_common.service import create_service_app


def create_app(
    settings: Settings | None = None,
    *,
    repository: ProductRepository | None = None,
    cache: ProductCache | None = None,
    readiness_probes: tuple[ReadinessCheck, ...] | None = None,
) -> FastAPI:
    """Build the app. Tests inject fakes (``repository``/``cache``/``readiness_probes``);
    production passes nothing and the real PostgreSQL and Valkey adapters are built from settings.
    """
    settings = settings or Settings()  # type: ignore[call-arg]  # values come from the environment
    registry = build_registry()
    engine: Engine | None = None
    valkey: ValkeyProductCache | None = None
    probes: list[ReadinessCheck] = []

    if repository is None:
        engine = build_engine(settings)
        repository = PostgresProductRepository(engine)
        probes.append(ReadinessCheck("postgres", lambda: ping(engine)))
    if cache is None:
        valkey = ValkeyProductCache.from_url(settings.cache_url, CacheMetrics(registry))
        cache = valkey
        # The cache is optional: reported in /health/ready but never able to fail it.
        probes.append(ReadinessCheck("valkey", valkey.ping, required=False))
    if readiness_probes is not None:
        probes = list(readiness_probes)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        if valkey is not None:
            valkey.close()
        if engine is not None:
            engine.dispose()

    app = create_service_app(
        settings, readiness_checks=probes, registry=registry, lifespan=lifespan
    )
    app.state.product_service = ProductService(repository, cache)
    install_domain_error_handlers(app)
    app.include_router(router)
    return app
