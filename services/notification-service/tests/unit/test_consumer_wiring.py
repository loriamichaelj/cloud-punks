"""The consumer process's wiring, built without a thread, a signal or a network call."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import ConsumerSettings
from app.consumer.main import SQS_READ_TIMEOUT_S, build_consumer
from retail_common.events.schemas import EventType

ENV = {
    "AWS_REGION": "us-east-1",
    "QUEUE_NAME": "notification-events",
    "SERVICE_NAME": "notification-consumer",
}


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> ConsumerSettings:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    return ConsumerSettings()  # type: ignore[call-arg]


class Unreachable:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"wiring must not call AWS ({name})")


class DownDynamo:
    def describe_table(self, **_kwargs: Any) -> Any:
        raise ConnectionError("dynamodb down")


@pytest.mark.parametrize("missing", ["QUEUE_NAME", "AWS_REGION"])
def test_refuses_to_start_without_its_configuration(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(missing)
    with pytest.raises(ValueError, match=missing.lower()):
        ConsumerSettings()  # type: ignore[call-arg]


def test_it_handles_the_three_notified_events(settings: ConsumerSettings) -> None:
    runtime = build_consumer(settings, dynamodb=Unreachable(), sqs=Unreachable())

    assert set(runtime.consumer._handlers) == {  # type: ignore[attr-defined]
        EventType.INVENTORY_RESERVED,
        EventType.INVENTORY_FAILED,
        EventType.ORDER_STATUS_UPDATED,
    }


def test_the_sqs_read_timeout_outlasts_long_polling(settings: ConsumerSettings) -> None:
    runtime = build_consumer(settings, dynamodb=Unreachable())

    assert runtime.consumer._client.meta.config.read_timeout == SQS_READ_TIMEOUT_S  # type: ignore[attr-defined]
    assert SQS_READ_TIMEOUT_S > 20


def test_readiness_needs_dynamodb_but_liveness_checks_nothing(settings: ConsumerSettings) -> None:
    runtime = build_consumer(settings, dynamodb=DownDynamo(), sqs=Unreachable())
    client = TestClient(runtime.side_app)

    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 503
    assert "events_consumed" in client.get("/metrics").text


class RecordingDynamo:
    """Remembers which table readiness asked about."""

    def __init__(self) -> None:
        self.tables: list[str] = []

    def describe_table(self, *, TableName: str) -> Any:
        self.tables.append(TableName)
        return {}


def test_the_table_name_defaults_to_the_local_name(settings: ConsumerSettings) -> None:
    assert settings.notifications_table == "notifications"


def test_readiness_checks_the_configured_table(
    monkeypatch: pytest.MonkeyPatch, settings: ConsumerSettings
) -> None:
    monkeypatch.setenv("NOTIFICATIONS_TABLE", "loria-notifications")
    dynamo = RecordingDynamo()
    runtime = build_consumer(
        ConsumerSettings(),  # type: ignore[call-arg]
        dynamodb=dynamo,
        sqs=Unreachable(),
    )

    assert TestClient(runtime.side_app).get("/health/ready").status_code == 200
    assert dynamo.tables == ["loria-notifications"]
