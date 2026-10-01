"""``python -m app consumer``: reserve stock for each OrderCreated event."""

from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.config import Config

from app.config import ConsumerSettings
from app.consumer.handler import OrderCreatedHandler
from app.domain.reservations import ReservationService
from app.repo.dynamodb import DynamoInventoryRepository, build_dynamodb_client, ping
from app.repo.reservations import DynamoReservationStore
from retail_common.consumer_runtime import ConsumerRuntime, build_consumer_runtime
from retail_common.events.envelope import new_event_id
from retail_common.events.publisher import EventBridgePublisher
from retail_common.events.schemas import EventType
from retail_common.health import ReadinessCheck

# SQS long polling waits up to 20 s, so the HTTP read timeout must be longer or every idle poll
# would fail with a read timeout.
SQS_READ_TIMEOUT_S = 30


def build_consumer(
    settings: ConsumerSettings,
    *,
    dynamodb: Any = None,
    sqs: Any = None,
    events: Any = None,
) -> ConsumerRuntime:
    """Wire the consumer. Starts no thread and opens no connection, so it can be unit-tested.

    Clients are built from the environment (AWS_ENDPOINT_URL, default credential chain)."""
    dynamodb = dynamodb or build_dynamodb_client(settings)
    sqs = sqs or boto3.client(
        "sqs",
        region_name=settings.aws_region,
        config=Config(
            connect_timeout=settings.http_timeout_connect_s,
            read_timeout=SQS_READ_TIMEOUT_S,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )
    events = events or boto3.client(
        "events",
        region_name=settings.aws_region,
        config=Config(
            connect_timeout=settings.http_timeout_connect_s,
            read_timeout=settings.http_timeout_read_s,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )

    # Readiness checks the required store only. The queue and the bus are exactly what the
    # consumer retries through when they fail, so they must not take it out of rotation.
    runtime = build_consumer_runtime(
        settings,
        sqs,
        settings.queue_name,
        readiness_checks=[ReadinessCheck("dynamodb", lambda: ping(dynamodb))],
    )
    service = ReservationService(
        DynamoReservationStore(dynamodb),
        DynamoInventoryRepository(dynamodb),
        new_event_id=new_event_id,
        now=lambda: datetime.now(UTC),
    )
    publisher = EventBridgePublisher(
        events, settings.event_bus_name, runtime.side_app.state.event_metrics
    )
    runtime.consumer.register(EventType.ORDER_CREATED, OrderCreatedHandler(service, publisher))
    return runtime


def main() -> int:
    settings = ConsumerSettings()  # type: ignore[call-arg]  # values come from the environment
    build_consumer(settings).run()
    return 0
