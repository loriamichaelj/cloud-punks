"""``python -m app consumer``: turn inventory and order events into notifications."""

from typing import Any

import boto3
from botocore.config import Config

from app.config import ConsumerSettings
from app.consumer.handler import NotificationHandler
from app.domain.notifications import NOTIFIED_EVENTS, NotificationService
from app.repo.dynamodb import DynamoNotificationStore, build_dynamodb_client, ping
from retail_common.consumer_runtime import ConsumerRuntime, build_consumer_runtime
from retail_common.health import ReadinessCheck

# SQS long polling waits up to 20 s, so the HTTP read timeout must be longer.
SQS_READ_TIMEOUT_S = 30


def build_consumer(
    settings: ConsumerSettings, *, dynamodb: Any = None, sqs: Any = None
) -> ConsumerRuntime:
    """Wire the consumer. Starts no thread and opens no connection, so it can be unit-tested."""
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
    # Readiness checks the one required store; the queue is what the loop retries through.
    runtime = build_consumer_runtime(
        settings,
        sqs,
        settings.queue_name,
        readiness_checks=[
            ReadinessCheck("dynamodb", lambda: ping(dynamodb, settings.notifications_table))
        ],
    )
    handler = NotificationHandler(
        NotificationService(DynamoNotificationStore(dynamodb, settings.notifications_table))
    )
    for event_type in NOTIFIED_EVENTS:
        runtime.consumer.register(event_type, handler)
    return runtime


def main() -> int:
    settings = ConsumerSettings()  # type: ignore[call-arg]  # values come from the environment
    build_consumer(settings).run()
    return 0
