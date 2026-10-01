"""The order API against real PostgreSQL: what is written, atomically, and what is not."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any

import pytest
from conftest import CUSTOMER, FakeCatalog, FakeStock, count, order_body, post, settings_for
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app import main as app_main
from app.config import Settings
from app.domain.models import OutboxEvent
from app.main import create_app
from retail_common.events.envelope import Envelope
from retail_common.events.schemas import OrderCreatedData, validate_data

pytestmark = pytest.mark.usefixtures("exclusive_outbox")  # asserts rows stay unpublished


def rows(engine: Engine, sql: str, **params: object) -> list[Any]:
    with engine.connect() as connection:
        return list(connection.execute(text(sql), params))


# --- the M5 done-when: POST /orders -> a row in orders AND a row in outbox ----------------------


def test_post_writes_the_order_its_items_and_one_unpublished_outbox_row(
    client: TestClient, engine: Engine, key: str
) -> None:
    response = post(client, key, order_body(**{"ITEST-SKU-A": 2, "ITEST-SKU-B": 3}))

    assert response.status_code == 202
    body = response.json()
    (order,) = rows(engine, "SELECT * FROM orders WHERE order_id = :o", o=body["order_id"])
    assert (order.customer_id, order.status, order.currency, order.version) == (
        CUSTOMER,
        "PENDING",
        "USD",
        1,
    )
    assert order.total_amount == Decimal("65.48")  # 2 x 19.99 + 3 x 8.50, exact in NUMERIC(12,2)
    assert (order.idempotency_key, len(order.request_hash)) == (key, 64)
    items = rows(
        engine,
        "SELECT sku, quantity, unit_price FROM order_items WHERE order_id = :o ORDER BY sku",
        o=body["order_id"],
    )
    assert [(i.sku, i.quantity, i.unit_price) for i in items] == [
        ("ITEST-SKU-A", 2, Decimal("19.99")),
        ("ITEST-SKU-B", 3, Decimal("8.50")),
    ]
    (outbox,) = rows(
        engine, "SELECT * FROM outbox WHERE payload->'data'->>'order_id' = :o", o=body["order_id"]
    )
    assert outbox.published_at is None  # the API never publishes; the relay does
    assert (outbox.detail_type, outbox.attempts, outbox.last_error) == ("OrderCreated", 0, None)


def test_the_stored_event_is_a_valid_order_created_envelope_for_that_order(
    client: TestClient, engine: Engine, key: str
) -> None:
    body = post(client, key).json()

    (outbox,) = rows(
        engine,
        "SELECT event_id, payload FROM outbox WHERE payload->'data'->>'order_id' = :o",
        o=body["order_id"],
    )

    envelope = Envelope.model_validate(outbox.payload)
    assert envelope.event_id == outbox.event_id
    data = validate_data(envelope)
    assert isinstance(data, OrderCreatedData)
    assert (data.order_id, data.customer_id, data.total_amount) == (
        body["order_id"],
        CUSTOMER,
        Decimal("39.98"),
    )
    assert outbox.payload["data"]["total_amount"] == "39.98"  # JSONB holds a string, not a float


def test_the_event_carries_the_requests_correlation_id(
    client: TestClient, engine: Engine, key: str
) -> None:
    response = client.post(
        "/api/v1/orders",
        json=order_body(),
        headers={"Idempotency-Key": key, "X-Correlation-ID": "corr-itest-1"},
    )
    (outbox,) = rows(
        engine,
        "SELECT payload FROM outbox WHERE payload->'data'->>'order_id' = :o",
        o=response.json()["order_id"],
    )
    assert outbox.payload["correlation_id"] == "corr-itest-1"


def test_the_response_matches_what_the_database_holds(client: TestClient, key: str) -> None:
    created = post(client, key).json()
    fetched = client.get(f"/api/v1/orders/{created['order_id']}").json()
    assert fetched == created


# --- idempotency ------------------------------------------------------------------------------


def test_a_replay_returns_the_original_and_writes_nothing_more(
    client: TestClient, engine: Engine, key: str
) -> None:
    first = post(client, key)
    replay = post(client, key)

    assert (first.status_code, replay.status_code) == (202, 200)
    assert replay.json() == first.json()
    assert count(engine, "SELECT count(*) FROM orders WHERE customer_id LIKE 'itest-%'") == 1
    assert (
        count(
            engine,
            "SELECT count(*) FROM outbox WHERE payload->'data'->>'customer_id' LIKE 'itest-%'",
        )
        == 1
    )


def test_a_replay_is_answered_even_when_the_dependencies_are_down(
    client: TestClient, catalog: FakeCatalog, stock: FakeStock, key: str
) -> None:
    first = post(client, key)
    catalog.down = stock.down = True

    replay = post(client, key)

    assert replay.status_code == 200
    assert replay.json() == first.json()


def test_the_same_key_with_a_different_body_is_422_and_writes_nothing(
    client: TestClient, engine: Engine, key: str
) -> None:
    post(client, key)

    response = post(client, key, order_body(**{"ITEST-SKU-A": 9}))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert count(engine, "SELECT count(*) FROM orders WHERE customer_id LIKE 'itest-%'") == 1


def test_concurrent_requests_with_one_key_create_exactly_one_order(
    client: TestClient, engine: Engine, key: str
) -> None:
    """The unique constraint, not luck, decides the winner; the losers become replays."""
    barrier = threading.Barrier(8)

    def attempt(_: int) -> Any:
        barrier.wait()
        return post(client, key)

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(attempt, range(8)))

    assert sorted(r.status_code for r in responses) == [200] * 7 + [202]
    assert len({r.json()["order_id"] for r in responses}) == 1
    assert count(engine, "SELECT count(*) FROM orders WHERE customer_id LIKE 'itest-%'") == 1
    assert (
        count(
            engine,
            "SELECT count(*) FROM order_items WHERE order_id IN (SELECT order_id FROM orders WHERE customer_id LIKE 'itest-%')",
        )
        == 1
    )
    assert (
        count(
            engine,
            "SELECT count(*) FROM outbox WHERE payload->'data'->>'customer_id' LIKE 'itest-%'",
        )
        == 1
    )


# --- atomicity: the order and its event commit together or not at all (ADR-04) ------------------


def test_if_the_outbox_insert_fails_the_whole_order_is_rolled_back(
    client: TestClient,
    engine: Engine,
    catalog: FakeCatalog,
    stock: FakeStock,
    monkeypatch: pytest.MonkeyPatch,
    key: str,
) -> None:
    first = post(client, key).json()
    (existing,) = rows(
        engine,
        "SELECT event_id FROM outbox WHERE payload->'data'->>'order_id' = :o",
        o=first["order_id"],
    )

    def colliding_event(order: Any) -> OutboxEvent:
        return OutboxEvent(
            event_id=existing.event_id,
            detail_type="OrderCreated",
            payload={"data": {"customer_id": CUSTOMER}},
        )

    monkeypatch.setattr(app_main, "order_created_event", colliding_event)
    with TestClient(
        create_app(settings_for(), catalog=catalog, stock=stock), raise_server_exceptions=False
    ) as broken:
        response = post(broken, f"{key}-second", order_body(**{"ITEST-SKU-B": 1}))

    assert response.status_code == 500  # a bug, correctly not disguised as an outage
    assert count(engine, "SELECT count(*) FROM orders WHERE customer_id LIKE 'itest-%'") == 1
    assert (
        count(engine, "SELECT count(*) FROM order_items WHERE sku = 'ITEST-SKU-B'") == 0
    )  # no orphans


# --- failures before the write leave no trace ---------------------------------------------------


def test_out_of_stock_writes_no_order_and_no_event(
    client: TestClient, engine: Engine, stock: FakeStock, key: str
) -> None:
    stock.levels["ITEST-SKU-A"] = 1

    response = post(client, key, order_body(**{"ITEST-SKU-A": 2}))

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "ITEST-SKU-A: requested 2, available 1"
    assert count(engine, "SELECT count(*) FROM orders WHERE customer_id LIKE 'itest-%'") == 0
    assert (
        count(
            engine,
            "SELECT count(*) FROM outbox WHERE payload->'data'->>'customer_id' LIKE 'itest-%'",
        )
        == 0
    )


@pytest.mark.parametrize("dependency", ["catalog", "stock"])
def test_an_unreachable_dependency_is_a_503_and_writes_nothing(
    client: TestClient,
    engine: Engine,
    catalog: FakeCatalog,
    stock: FakeStock,
    key: str,
    dependency: str,
) -> None:
    (catalog if dependency == "catalog" else stock).down = True

    response = post(client, key)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert count(engine, "SELECT count(*) FROM orders WHERE customer_id LIKE 'itest-%'") == 0

    (catalog if dependency == "catalog" else stock).down = False
    assert post(client, key).status_code == 202  # the same key works once the dependency is back


# --- reads ------------------------------------------------------------------------------------


def test_listing_is_newest_first_paginated_and_per_customer(client: TestClient, key: str) -> None:
    ids = [post(client, f"{key}-{n}").json()["order_id"] for n in range(5)]
    post(client, f"{key}-other", order_body("itest-someone-else"))

    page1 = client.get(f"/api/v1/orders?customer_id={CUSTOMER}&size=2&page=1").json()
    page3 = client.get(f"/api/v1/orders?customer_id={CUSTOMER}&size=2&page=3").json()

    assert page1["total"] == 5
    assert [o["order_id"] for o in page1["items"]] == [ids[4], ids[3]]  # newest first
    assert [o["order_id"] for o in page3["items"]] == [ids[0]]
    assert all(o["customer_id"] == CUSTOMER for o in page1["items"])
    assert page1["items"][0]["items"][0]["unit_price"] == "19.99"


def test_unknown_order_is_404(client: TestClient) -> None:
    response = client.get("/api/v1/orders/01J9Z6Q4W8K3M2N1P0R7S5T4V3")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ORDER_NOT_FOUND"


# --- database unavailable -----------------------------------------------------------------------


def test_postgres_unreachable_is_a_503_and_liveness_survives(
    catalog: FakeCatalog, stock: FakeStock, key: str
) -> None:
    dead: Settings = settings_for(db_port=1)  # nothing listens on port 1
    with TestClient(create_app(dead, catalog=catalog, stock=stock)) as client:
        response = post(client, key)
        listing = client.get(f"/api/v1/orders?customer_id={CUSTOMER}")

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "STORE_UNAVAILABLE"
        assert listing.status_code == 503
        assert "127.0.0.1" not in response.text
        assert client.get("/health/ready").status_code == 503
        assert client.get("/health/live").status_code == 200


def test_readiness_is_green_with_a_real_database(client: TestClient) -> None:
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["dependencies"]["postgres"]["status"] == "ok"


def test_json_round_trips_through_the_documented_example_shape(
    client: TestClient, key: str
) -> None:
    body = post(client, key).json()
    assert set(body) >= {"order_id", "status", "total_amount", "currency", "items", "created_at"}
    assert json.dumps(body)  # serializable, no Decimal leaking through
