"""The relay process's wiring, built without starting a thread, a signal handler or a connection.

This exists because the first real start crashed: the publisher's metrics and the app's metrics
were both registered on one Prometheus registry, which raises DuplicateTimeseries. Nothing in
the unit suite constructed the relay, so nothing noticed until the container restart-looped.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import RelaySettings
from app.relay.main import build_relay

ENV = {
    "DB_HOST": "127.0.0.1",
    "DB_PORT": "1",  # nothing listens here: the wiring must not need a live database
    "DB_NAME": "order_db",
    "DB_USER": "order_app",
    "DB_PASSWORD": "not-a-real-password",
    "AWS_REGION": "us-east-1",
    "EVENT_BUS_NAME": "retail-events",
    "SERVICE_NAME": "order-relay",
}


class RecordingEvents:
    def put_events(self, *, Entries: list[dict[str, Any]]) -> dict[str, Any]:
        return {"FailedEntryCount": 0, "Entries": [{"EventId": "x"} for _ in Entries]}


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> RelaySettings:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    return RelaySettings()  # type: ignore[call-arg]


def test_the_relay_can_be_wired_without_registry_collisions(settings: RelaySettings) -> None:
    runtime = build_relay(settings, events_client=RecordingEvents())
    try:
        assert runtime.relay.stopping is False
    finally:
        runtime.engine.dispose()


def test_the_side_server_app_exposes_the_outbox_gauges_and_event_metrics(
    settings: RelaySettings,
) -> None:
    runtime = build_relay(settings, events_client=RecordingEvents())
    try:
        text = TestClient(runtime.side_app).get("/metrics").text
    finally:
        runtime.engine.dispose()

    assert "outbox_unpublished" in text
    assert "outbox_oldest_unpublished_age_seconds" in text
    assert "events_published_total" in text  # the publisher shares the app's metrics
    assert "events_publish_failures_total" in text


def test_a_scrape_survives_the_database_being_down(settings: RelaySettings) -> None:
    """The gauges query PostgreSQL on every scrape; an outage must not turn /metrics into a 500."""
    runtime = build_relay(settings, events_client=RecordingEvents())
    try:
        response = TestClient(runtime.side_app).get("/metrics")
    finally:
        runtime.engine.dispose()

    assert response.status_code == 200
    assert "outbox_unpublished NaN" in response.text


def test_liveness_ignores_the_database_but_readiness_requires_it(settings: RelaySettings) -> None:
    runtime = build_relay(settings, events_client=RecordingEvents())
    try:
        client = TestClient(runtime.side_app)
        assert client.get("/health/live").status_code == 200
        ready = client.get("/health/ready")
    finally:
        runtime.engine.dispose()

    assert ready.status_code == 503
    assert set(ready.json()["dependencies"]) == {"postgres"}  # the bus is deliberately not checked


def test_the_publisher_uses_the_configured_bus(settings: RelaySettings) -> None:
    runtime = build_relay(settings, events_client=RecordingEvents())
    try:
        assert runtime.relay._publisher._bus_name == "retail-events"
    finally:
        runtime.engine.dispose()
