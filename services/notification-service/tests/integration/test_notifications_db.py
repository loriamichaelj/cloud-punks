"""The notification store and API against LocalStack's real DynamoDB."""

import threading
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import new_id
from fastapi.testclient import TestClient

from app.config import Settings
from app.consumer.handler import NotificationHandler
from app.domain.notifications import Notification, NotificationService
from app.main import create_app
from app.repo.dynamodb import DynamoNotificationStore
from retail_common.events.consumer import HandlerOutcome
from retail_common.events.envelope import Envelope
from retail_common.events.schemas import EventType, InventoryReservedData


@pytest.fixture
def store(dynamodb: Any) -> DynamoNotificationStore:
    return DynamoNotificationStore(dynamodb)


def note(order_id: str, event_id: str, text: str = "hello") -> Notification:
    return Notification(order_id, event_id, "InventoryReserved", "email", text, datetime.now(UTC))


def test_a_notification_round_trips(store: DynamoNotificationStore) -> None:
    order_id, event_id = new_id(), new_id()
    original = note(order_id, event_id)

    assert store.add(original) is True

    (found,) = store.for_order(order_id)
    assert (found.event_id, found.type, found.channel, found.message) == (
        event_id,
        "InventoryReserved",
        "email",
        "hello",
    )


def test_the_same_event_is_stored_once_and_the_first_record_stands(
    store: DynamoNotificationStore,
) -> None:
    order_id, event_id = new_id(), new_id()

    first = store.add(note(order_id, event_id, "first"))
    again = store.add(note(order_id, event_id, "second"))

    assert (first, again) == (True, False)
    assert [n.message for n in store.for_order(order_id)] == ["first"]


def test_the_same_event_delivered_concurrently_is_stored_exactly_once(
    store: DynamoNotificationStore,
) -> None:
    order_id, event_id = new_id(), new_id()
    results: list[bool] = []
    barrier = threading.Barrier(10)

    def deliver() -> None:
        barrier.wait(timeout=10)
        results.append(store.add(note(order_id, event_id)))

    threads = [threading.Thread(target=deliver) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert sorted(results) == [False] * 9 + [True]
    assert len(store.for_order(order_id)) == 1


def test_notifications_are_oldest_first_and_scoped_to_their_order(
    store: DynamoNotificationStore,
) -> None:
    order_id, other = new_id(), new_id()
    ids = sorted(new_id() for _ in range(3))
    for event_id in reversed(ids):
        store.add(note(order_id, event_id))
    store.add(note(other, new_id()))

    assert [n.event_id for n in store.for_order(order_id)] == ids


def test_a_ttl_is_stored_in_epoch_seconds(store: DynamoNotificationStore, dynamodb: Any) -> None:
    order_id, event_id = new_id(), new_id()
    notification = note(order_id, event_id)
    store.add(notification)

    raw = dynamodb.get_item(
        TableName="notifications",
        Key={"order_id": {"S": order_id}, "event_id": {"S": event_id}},
        ConsistentRead=True,
    )["Item"]

    assert int(raw["ttl"]["N"]) == int(notification.expires_at.timestamp())


def test_the_handler_end_to_end_on_a_real_envelope(
    store: DynamoNotificationStore, client: TestClient
) -> None:
    order_id = new_id()
    data = InventoryReservedData.model_validate(
        {"order_id": order_id, "items": [{"sku": "ITEST-A", "quantity": 2, "remaining": 8}]}
    )
    envelope = Envelope.create(
        event_type=EventType.INVENTORY_RESERVED,
        producer="inventory-service",
        data=data,
        event_id=new_id(),
    )
    handler = NotificationHandler(NotificationService(store))

    assert handler(envelope, data) is HandlerOutcome.PROCESSED
    assert handler(envelope, data) is HandlerOutcome.DUPLICATE

    body = client.get("/api/v1/notifications", params={"order_id": order_id}).json()
    assert [i["type"] for i in body["items"]] == ["InventoryReserved"]
    assert "2 x ITEST-A" in body["items"][0]["message"]


def test_the_api_answers_503_when_dynamodb_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://127.0.0.1:1")  # nothing listens here
    with TestClient(create_app(Settings(aws_region="us-east-1"))) as dead:  # type: ignore[call-arg]
        response = dead.get("/api/v1/notifications", params={"order_id": new_id()})
        assert response.status_code == 503
        assert dead.get("/health/live").status_code == 200
        assert dead.get("/health/ready").status_code == 503
