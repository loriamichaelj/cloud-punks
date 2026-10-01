"""order-service API application factory.

The API never publishes events (CLAUDE.md: never call PutEvents from a request handler). It has
no event-bus client at all; events leave only through the outbox relay process.
"""

from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from sqlalchemy import Engine
from ulid import ULID

from app.api.errors import install_domain_error_handlers
from app.api.routes import router
from app.clients.http import MAX_PARALLEL_LOOKUPS, HttpPriceCatalog, HttpStockChecker
from app.config import Settings
from app.domain.ports import OrderRepository, PriceCatalog, StockChecker
from app.domain.service import OrderService
from app.events import order_created_event
from app.repo.orders import PostgresOrderRepository
from retail_common.database import build_engine, ping
from retail_common.health import ReadinessCheck
from retail_common.http_client import ServiceHttpClient
from retail_common.service import create_service_app


def create_app(
    settings: Settings | None = None,
    *,
    repository: OrderRepository | None = None,
    catalog: PriceCatalog | None = None,
    stock: StockChecker | None = None,
    readiness_probes: tuple[ReadinessCheck, ...] | None = None,
) -> FastAPI:
    """Build the app. Tests inject fakes; production passes nothing and real adapters are built
    from settings."""
    settings = settings or Settings()  # type: ignore[call-arg]  # values come from the environment
    engine: Engine | None = None
    executor = ThreadPoolExecutor(max_workers=MAX_PARALLEL_LOOKUPS, thread_name_prefix="lookup")
    clients: list[ServiceHttpClient] = []
    probes: list[ReadinessCheck] = []

    def http_client(url: str, upstream: str) -> ServiceHttpClient:
        client = ServiceHttpClient(
            url,
            upstream=upstream,
            connect_timeout_s=settings.http_timeout_connect_s,
            read_timeout_s=settings.http_timeout_read_s,
        )
        clients.append(client)
        return client

    if repository is None:
        engine = build_engine(settings)
        repository = PostgresOrderRepository(engine)
        probes.append(ReadinessCheck("postgres", lambda: ping(engine)))
    if catalog is None:
        catalog = HttpPriceCatalog(
            http_client(settings.product_service_url, "product-service"), executor
        )
    if stock is None:
        stock = HttpStockChecker(http_client(settings.inventory_service_url, "inventory-service"))
    if readiness_probes is not None:
        probes = list(readiness_probes)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        executor.shutdown(wait=False)
        for client in clients:
            client.close()
        if engine is not None:
            engine.dispose()

    app = create_service_app(settings, readiness_checks=probes, lifespan=lifespan)
    app.state.order_service = OrderService(
        repository,
        catalog,
        stock,
        new_order_id=lambda: str(ULID()),
        make_event=order_created_event,
        now=lambda: datetime.now(UTC),
    )
    install_domain_error_handlers(app)
    app.include_router(router)
    return app
