"""The consumer process's wiring, built without a thread, a signal handler or a connection."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import ConsumerSettings
from app.consumer.main import SQS_READ_TIMEOUT_S, build_consumer
from retail_common.events.schemas import EventType

ENV = {
    "DB_HOST": "127.0.0.1",
    "DB_PORT": "1",  # nothing listens here: the wiring must not need a live database
    "DB_NAME": "order_db",
    "DB_USER": "order_app",
    "DB_PASSWORD": "not-a-real-password",
    "AWS_REGION": "us-east-1",
    "QUEUE_NAME": "order-inventory-events",
    "SERVICE_NAME": "order-consumer",
}


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> ConsumerSettings:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    return ConsumerSettings()  # type: ignore[call-arg]


class IdleSqs:
    def __getattr__(self, name: str) -> Any:  # pragma: no cover - never called while wiring
        raise AssertionError(f"wiring must not call SQS ({name})")


def test_the_queue_comes_from_the_environment(settings: ConsumerSettings) -> None:
    assert settings.queue_name == "order-inventory-events"


def test_a_consumer_without_a_queue_name_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in ENV.items():
        if name != "QUEUE_NAME":
            monkeypatch.setenv(name, value)
    monkeypatch.delenv("QUEUE_NAME", raising=False)
    with pytest.raises(ValueError, match="queue_name"):
        ConsumerSettings()  # type: ignore[call-arg]


def test_it_handles_exactly_the_inventory_outcomes(settings: ConsumerSettings) -> None:
    runtime = build_consumer(settings, sqs=IdleSqs())

    assert set(runtime.consumer._handlers) == {  # type: ignore[attr-defined]
        EventType.INVENTORY_RESERVED,
        EventType.INVENTORY_FAILED,
    }


def test_the_sqs_read_timeout_outlasts_long_polling(settings: ConsumerSettings) -> None:
    runtime = build_consumer(settings)  # builds the real boto3 client; makes no call
    client = runtime.consumer._client  # type: ignore[attr-defined]
    assert client.meta.config.read_timeout == SQS_READ_TIMEOUT_S
    assert SQS_READ_TIMEOUT_S > 20


def test_the_side_app_exposes_order_and_event_metrics_without_collisions(
    settings: ConsumerSettings,
) -> None:
    runtime = build_consumer(settings, sqs=IdleSqs())

    text = TestClient(runtime.side_app).get("/metrics").text

    assert "events_consumed_total" in text or "events_consumed" in text
    assert "order_time_to_terminal_seconds" in text


def test_liveness_checks_nothing_but_readiness_needs_postgres(settings: ConsumerSettings) -> None:
    runtime = build_consumer(settings, sqs=IdleSqs())
    client = TestClient(runtime.side_app)

    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 503  # nothing listens on the DB port
