"""inventory-service application factory."""

from fastapi import FastAPI

from app.api.errors import install_domain_error_handlers
from app.api.middleware import NoStoreMiddleware
from app.api.routes import INVENTORY_PREFIX, router
from app.config import Settings
from app.domain.ports import InventoryRepository
from app.domain.service import InventoryService
from app.repo.dynamodb import DynamoInventoryRepository, build_dynamodb_client, ping
from retail_common.health import ReadinessCheck
from retail_common.service import create_service_app


def create_app(
    settings: Settings | None = None,
    *,
    repository: InventoryRepository | None = None,
    readiness_probes: tuple[ReadinessCheck, ...] | None = None,
) -> FastAPI:
    """Build the app. Tests inject a ``repository`` (and ``readiness_probes``); production passes
    nothing and the DynamoDB adapter is built from the environment."""
    settings = settings or Settings()  # type: ignore[call-arg]  # values come from the environment
    probes: list[ReadinessCheck] = []

    if repository is None:
        client = build_dynamodb_client(settings)
        repository = DynamoInventoryRepository(client)
        probes.append(ReadinessCheck("dynamodb", lambda: ping(client)))
    if readiness_probes is not None:
        probes = list(readiness_probes)

    app = create_service_app(settings, readiness_checks=probes)
    app.state.inventory_service = InventoryService(repository)
    install_domain_error_handlers(app)
    app.add_middleware(NoStoreMiddleware, prefix=INVENTORY_PREFIX)
    app.include_router(router)
    return app
