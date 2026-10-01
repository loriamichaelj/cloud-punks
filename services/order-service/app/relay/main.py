"""``python -m app relay``: the outbox relay process (ADR-04)."""

import signal
import types
from dataclasses import dataclass
from typing import Any

import boto3
import structlog
from botocore.config import Config
from fastapi import FastAPI
from prometheus_client import Gauge
from sqlalchemy import Engine

from app.config import RelaySettings
from app.relay.core import OutboxRelay
from app.relay.store import PostgresOutboxStore
from retail_common.database import build_engine, ping
from retail_common.events.publisher import EventBridgePublisher
from retail_common.health import ReadinessCheck
from retail_common.metrics import build_registry
from retail_common.service import create_service_app
from retail_common.side_server import SideServer

_log = structlog.get_logger("outbox_relay")


@dataclass
class RelayRuntime:
    """Everything the relay process needs, wired but not started."""

    relay: OutboxRelay
    store: PostgresOutboxStore
    side_app: FastAPI
    engine: Engine


def build_relay(settings: RelaySettings, *, events_client: Any = None) -> RelayRuntime:
    """Wire the relay. No thread, signal handler or connection is created here, so this is
    testable; ``main`` starts the pieces."""
    engine = build_engine(settings)
    store = PostgresOutboxStore(engine)
    registry = build_registry()

    # Readiness checks PostgreSQL only: a bus outage is exactly when the relay must stay up and
    # keep retrying, not be taken out of rotation.
    side_app = create_service_app(
        settings,
        readiness_checks=[ReadinessCheck("postgres", lambda: ping(engine))],
        registry=registry,
    )

    # The endpoint and credentials come from the environment (AWS_ENDPOINT_URL, default chain).
    events = events_client or boto3.client(
        "events",
        region_name=settings.aws_region,
        config=Config(
            connect_timeout=settings.http_timeout_connect_s,
            read_timeout=settings.http_timeout_read_s,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )
    # create_service_app already registered the event metrics on this registry; share them.
    publisher = EventBridgePublisher(events, settings.event_bus_name, side_app.state.event_metrics)

    def unpublished() -> float:
        try:
            return float(store.unpublished_stats()[0])
        except Exception:  # noqa: BLE001 - a scrape must never fail because the database is down
            return float("nan")

    def oldest_age() -> float:
        try:
            age = store.unpublished_stats()[1]
        except Exception:  # noqa: BLE001
            return float("nan")
        return age if age is not None else 0.0

    Gauge("outbox_unpublished", "Outbox rows not yet published.", registry=registry).set_function(
        unpublished
    )
    Gauge(
        "outbox_oldest_unpublished_age_seconds",
        "Age of the oldest unpublished outbox row.",
        registry=registry,
    ).set_function(oldest_age)

    return RelayRuntime(OutboxRelay(store, publisher), store, side_app, engine)


def main() -> int:
    settings = RelaySettings()  # type: ignore[call-arg]  # values come from the environment
    runtime = build_relay(settings)
    side_server = SideServer(runtime.side_app)

    def shutdown(signum: int, _frame: types.FrameType | None) -> None:
        _log.info("relay_shutdown_requested", signal=signal.Signals(signum).name)
        runtime.relay.stop()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    side_server.start()
    _log.info("relay_started", bus=settings.event_bus_name)
    try:
        runtime.relay.run()
    finally:
        side_server.stop()
        runtime.engine.dispose()
        _log.info("relay_stopped")
    return 0
