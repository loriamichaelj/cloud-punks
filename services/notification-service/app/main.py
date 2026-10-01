"""notification-service application factory."""

from fastapi import FastAPI

from app.api.errors import install_domain_error_handlers
from app.api.routes import router
from app.config import Settings
from app.domain.notifications import NotificationService, NotificationStore
from app.repo.dynamodb import DynamoNotificationStore, build_dynamodb_client, ping
from retail_common.health import ReadinessCheck
from retail_common.service import create_service_app


def create_app(
    settings: Settings | None = None,
    *,
    store: NotificationStore | None = None,
    readiness_probes: tuple[ReadinessCheck, ...] | None = None,
) -> FastAPI:
    """Build the app. Tests inject a ``store``; production passes nothing and the DynamoDB
    adapter is built from the environment."""
    settings = settings or Settings()  # type: ignore[call-arg]  # values come from the environment
    probes: list[ReadinessCheck] = []

    if store is None:
        client = build_dynamodb_client(settings)
        store = DynamoNotificationStore(client)
        probes.append(ReadinessCheck("dynamodb", lambda: ping(client)))
    if readiness_probes is not None:
        probes = list(readiness_probes)

    app = create_service_app(settings, readiness_checks=probes)
    app.state.notification_service = NotificationService(store)
    install_domain_error_handlers(app)
    app.include_router(router)
    return app
