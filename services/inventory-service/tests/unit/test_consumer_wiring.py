"""The inventory consumer process's wiring, built without a thread, a signal or a network call."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import ConsumerSettings
from app.consumer.main import SQS_READ_TIMEOUT_S, build_consumer
from retail_common.events.schemas import EventType

ENV = {
    "AWS_REGION": "us-east-1",
    "QUEUE_NAME": "inventory-order-events",
    "EVENT_BUS_NAME": "retail-events",
    "SERVICE_NAME": "inventory-consumer",
}


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> ConsumerSettings:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    return ConsumerSettings()  # type: ignore[call-arg]


class Unreachable:
    """Stands in for a client: any call means the wiring did I/O."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"wiring must not call AWS ({name})")


class DownDynamo:
    def describe_table(self, **_kwargs: Any) -> Any:
        raise ConnectionError("dynamodb down")


def test_queue_and_bus_come_from_the_environment(settings: ConsumerSettings) -> None:
    assert (settings.queue_name, settings.event_bus_name) == (
        "inventory-order-events",
        "retail-events",
    )


@pytest.mark.parametrize("missing", ["QUEUE_NAME", "EVENT_BUS_NAME", "AWS_REGION"])
def test_the_consumer_refuses_to_start_without_its_configuration(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(missing)
    with pytest.raises(ValueError, match=missing.lower()):
        ConsumerSettings()  # type: ignore[call-arg]


def test_it_handles_exactly_OrderCreated(settings: ConsumerSettings) -> None:
    runtime = build_consumer(
        settings, dynamodb=Unreachable(), sqs=Unreachable(), events=Unreachable()
    )

    assert set(runtime.consumer._handlers) == {EventType.ORDER_CREATED}  # type: ignore[attr-defined]


def test_the_sqs_read_timeout_outlasts_long_polling(settings: ConsumerSettings) -> None:
    runtime = build_consumer(settings, dynamodb=Unreachable(), events=Unreachable())

    client = runtime.consumer._client  # type: ignore[attr-defined]
    assert client.meta.config.read_timeout == SQS_READ_TIMEOUT_S
    assert SQS_READ_TIMEOUT_S > 20  # SqsConsumer long-polls for 20 s


def test_publisher_and_consumer_share_one_metrics_registry(settings: ConsumerSettings) -> None:
    runtime = build_consumer(
        settings, dynamodb=Unreachable(), sqs=Unreachable(), events=Unreachable()
    )

    text = TestClient(runtime.side_app).get("/metrics").text

    assert "events_published_total" in text  # the outcome publisher
    assert "events_consumed_total" in text or "events_consumed" in text


def test_readiness_needs_dynamodb_but_liveness_checks_nothing(settings: ConsumerSettings) -> None:
    runtime = build_consumer(
        settings, dynamodb=DownDynamo(), sqs=Unreachable(), events=Unreachable()
    )
    client = TestClient(runtime.side_app)

    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 503
