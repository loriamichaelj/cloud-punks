from datetime import UTC, datetime

import pytest
from fakes import ORDER_ID, FakeStore, make_settings
from fastapi.testclient import TestClient

from app.domain.notifications import Notification
from app.main import create_app


def note(event_id: str, kind: str, text: str, order_id: str = ORDER_ID) -> Notification:
    return Notification(
        order_id, event_id, kind, "email", text, datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    )


@pytest.fixture
def store() -> FakeStore:
    store = FakeStore()
    store.add(note("01J9Z6R0C4BBBBBBBBBBBBBBBB", "OrderStatusUpdated", "later"))
    store.add(note("01J9Z6R0C4AAAAAAAAAAAAAAAB", "InventoryReserved", "earlier"))
    store.add(
        note(
            "01J9Z6R0C4AAAAAAAAAAAAAAAC", "InventoryReserved", "other", "01J9Z6R0C4CCCCCCCCCCCCCCCC"
        )
    )
    return store


@pytest.fixture
def client(store: FakeStore) -> TestClient:
    return TestClient(create_app(make_settings(), store=store))


def test_lists_one_orders_notifications_oldest_first(client: TestClient) -> None:
    response = client.get("/api/v1/notifications", params={"order_id": ORDER_ID})

    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["message"] for i in items] == ["earlier", "later"]
    assert set(items[0]) == {"event_id", "type", "channel", "message", "created_at"}
    assert items[0]["created_at"].endswith("Z")


def test_an_order_without_notifications_is_an_empty_list(client: TestClient) -> None:
    response = client.get(
        "/api/v1/notifications", params={"order_id": "01J9Z6R0C4ZZZZZZZZZZZZZZZZ"}
    )
    assert (response.status_code, response.json()) == (200, {"items": []})


@pytest.mark.parametrize("params", [{}, {"order_id": "nope"}, {"order_id": ""}])
def test_order_id_is_required_and_must_be_a_ulid(
    client: TestClient, params: dict[str, str]
) -> None:
    response = client.get("/api/v1/notifications", params=params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_a_store_outage_is_a_503_with_retry_after(client: TestClient, store: FakeStore) -> None:
    store.down = True

    response = client.get("/api/v1/notifications", params={"order_id": ORDER_ID})

    assert response.status_code == 503
    assert "Retry-After" in response.headers
    assert client.get("/health/live").status_code == 200
