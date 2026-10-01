"""``python -m app consumer``: apply inventory outcomes to orders."""

from typing import Any

import boto3
from botocore.config import Config
from sqlalchemy import Engine

from app.config import ConsumerSettings
from app.consumer.handler import InventoryOutcomeHandler
from app.domain.transitions import TransitionService
from app.events import order_status_updated_event
from app.metrics import OrderMetrics
from app.repo.transitions import PostgresTransitionStore
from retail_common.consumer_runtime import ConsumerRuntime, build_consumer_runtime
from retail_common.database import build_engine, ping
from retail_common.events.schemas import EventType
from retail_common.health import ReadinessCheck

# SQS long polling waits up to 20 s, so the HTTP read timeout must be longer.
SQS_READ_TIMEOUT_S = 30


def build_consumer(
    settings: ConsumerSettings, *, engine: Engine | None = None, sqs: Any = None
) -> ConsumerRuntime:
    """Wire the consumer. Starts no thread and opens no connection, so it can be unit-tested."""
    engine = engine or build_engine(settings)
    sqs = sqs or boto3.client(
        "sqs",
        region_name=settings.aws_region,
        config=Config(
            connect_timeout=settings.http_timeout_connect_s,
            read_timeout=SQS_READ_TIMEOUT_S,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )
    # Readiness checks PostgreSQL only; the queue is what the consumer retries through.
    runtime = build_consumer_runtime(
        settings,
        sqs,
        settings.queue_name,
        readiness_checks=[ReadinessCheck("postgres", lambda: ping(engine))],
    )
    handler = InventoryOutcomeHandler(
        TransitionService(PostgresTransitionStore(engine), order_status_updated_event),
        OrderMetrics(runtime.side_app.state.registry),
    )
    runtime.consumer.register(EventType.INVENTORY_RESERVED, handler.on_reserved)
    runtime.consumer.register(EventType.INVENTORY_FAILED, handler.on_failed)
    return runtime


def main() -> int:
    settings = ConsumerSettings()  # type: ignore[call-arg]  # values come from the environment
    build_consumer(settings).run()
    return 0
