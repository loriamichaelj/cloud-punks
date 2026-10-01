"""The inventory API against real DynamoDB, including the strongly-consistent-read guarantee."""

import time
from typing import Any

from conftest import DEAD_ENDPOINT, ReadRecorder, put_raw
from fastapi.testclient import TestClient


def availability(client: TestClient, *lines: tuple[str, int]) -> Any:
    return client.post(
        "/api/v1/inventory/availability",
        json={"items": [{"sku": s, "quantity": q} for s, q in lines]},
    )


# --- strong consistency: the M4 done-when -------------------------------------------------------


def test_every_read_sent_to_dynamodb_is_strongly_consistent(
    client: TestClient, sku: str, dynamodb: Any, recorder: ReadRecorder
) -> None:
    """Checked on the wire. LocalStack is always strongly consistent, so a behavioural test
    alone could not tell whether the code asked for it; the request parameters can."""
    put_raw(dynamodb, sku, 10)

    client.get(f"/api/v1/inventory/{sku}")
    client.get("/api/v1/inventory/ITEST-NOT-THERE")  # even a miss must be a consistent read
    availability(client, (sku, 1))
    availability(client, (sku, 1), ("ITEST-NOT-THERE", 1))

    assert [op for op, _ in recorder.reads] == [
        "GetItem",
        "GetItem",
        "BatchGetItem",
        "BatchGetItem",
    ]
    assert all(consistent for _, consistent in recorder.reads), recorder.reads


def test_a_write_is_visible_to_the_very_next_read_every_time(client: TestClient, sku: str) -> None:
    for quantity in range(50):
        assert (
            client.put(f"/api/v1/inventory/{sku}", json={"available": quantity}).status_code == 200
        )
        assert client.get(f"/api/v1/inventory/{sku}").json()["available"] == quantity
        assert availability(client, (sku, 1)).json()["items"][0]["available"] == quantity


def test_a_reservation_made_behind_the_apis_back_is_seen_immediately(
    client: TestClient, sku: str, dynamodb: Any
) -> None:
    """What the inventory consumer will do: an atomic decrement of `available`, increment of
    `reserved`. The order service's pre-check must never read the stock from before it."""
    put_raw(dynamodb, sku, 10)
    assert availability(client, (sku, 10)).json()["available"] is True

    dynamodb.update_item(
        TableName="inventory",
        Key={"sku": {"S": sku}},
        UpdateExpression="SET available = available - :q, reserved = reserved + :q",
        ConditionExpression="available >= :q",
        ExpressionAttributeValues={":q": {"N": "7"}},
    )

    body = client.get(f"/api/v1/inventory/{sku}").json()
    assert (body["available"], body["reserved"]) == (3, 7)
    assert availability(client, (sku, 10)).json()["available"] is False
    assert availability(client, (sku, 3)).json()["available"] is True


# --- behaviour against the real store -----------------------------------------------------------


def test_set_then_get_round_trips_types_and_timestamps(client: TestClient, sku: str) -> None:
    created = client.put(f"/api/v1/inventory/{sku}", json={"available": 25})

    assert created.status_code == 200
    body = client.get(f"/api/v1/inventory/{sku}").json()
    assert body == created.json()
    assert (body["available"], body["reserved"]) == (25, 0)
    assert isinstance(body["available"], int)
    assert body["updated_at"].endswith("+00:00") or body["updated_at"].endswith("Z")


def test_put_keeps_what_is_already_reserved(client: TestClient, sku: str, dynamodb: Any) -> None:
    put_raw(dynamodb, sku, available=10, reserved=6)

    body = client.put(f"/api/v1/inventory/{sku}", json={"available": 99}).json()

    assert (body["available"], body["reserved"]) == (99, 6)


def test_put_zero_takes_a_product_out_of_stock(client: TestClient, sku: str) -> None:
    client.put(f"/api/v1/inventory/{sku}", json={"available": 5})
    client.put(f"/api/v1/inventory/{sku}", json={"available": 0})
    assert availability(client, (sku, 1)).json()["items"][0]["reason"] == "OUT_OF_STOCK"


def test_unknown_sku_is_404_and_stays_404_after_it_is_created(client: TestClient, sku: str) -> None:
    missing = client.get(f"/api/v1/inventory/{sku}")
    assert missing.status_code == 404
    assert missing.headers["Cache-Control"] == "no-store"

    client.put(f"/api/v1/inventory/{sku}", json={"available": 1})

    assert client.get(f"/api/v1/inventory/{sku}").status_code == 200  # no stale 404


def test_batch_availability_through_the_real_batch_get_item(
    client: TestClient, sku: str, dynamodb: Any
) -> None:
    put_raw(dynamodb, f"{sku}-a", 10)
    put_raw(dynamodb, f"{sku}-b", 1)

    body = availability(client, (f"{sku}-b", 5), (f"{sku}-a", 2), (f"{sku}-zzz", 1)).json()

    assert body["available"] is False
    assert [(i["sku"], i["sufficient"], i["reason"], i["available"]) for i in body["items"]] == [
        (f"{sku}-b", False, "OUT_OF_STOCK", 1),  # request order is preserved
        (f"{sku}-a", True, None, 10),
        (f"{sku}-zzz", False, "UNKNOWN_SKU", 0),
    ]


def test_twenty_lines_in_one_batch(client: TestClient, sku: str, dynamodb: Any) -> None:
    lines = [(f"{sku}-{n:02d}", 1) for n in range(20)]
    for line_sku, _ in lines:
        put_raw(dynamodb, line_sku, 5)

    body = availability(client, *lines).json()

    assert body["available"] is True
    assert len(body["items"]) == 20


def test_every_response_is_no_store(client: TestClient, sku: str) -> None:
    client.put(f"/api/v1/inventory/{sku}", json={"available": 1})
    for response in (
        client.get(f"/api/v1/inventory/{sku}"),
        availability(client, (sku, 1)),
        client.put(f"/api/v1/inventory/{sku}", json={"available": 2}),
        client.put(f"/api/v1/inventory/{sku}", json={"available": -1}),
    ):
        assert response.headers["Cache-Control"] == "no-store"


def test_readiness_describes_the_real_table(client: TestClient) -> None:
    ready = client.get("/health/ready")

    assert ready.status_code == 200
    assert ready.json()["dependencies"]["dynamodb"]["status"] == "ok"
    assert ready.json()["dependencies"]["dynamodb"]["required"] is True


# --- DynamoDB unavailable -----------------------------------------------------------------------


def test_dynamodb_unreachable_is_a_503_everywhere_and_liveness_survives(
    monkeypatch: Any, sku: str
) -> None:
    from app.config import Settings
    from app.main import create_app

    monkeypatch.setenv("AWS_ENDPOINT_URL", DEAD_ENDPOINT)  # boto3 reads this at client creation
    with TestClient(create_app(Settings(aws_region="us-east-1"))) as dead:  # type: ignore[call-arg]
        started = time.perf_counter()
        responses = [
            dead.get(f"/api/v1/inventory/{sku}"),
            availability(dead, (sku, 1)),
            dead.put(f"/api/v1/inventory/{sku}", json={"available": 1}),
        ]
        elapsed = time.perf_counter() - started

        for response in responses:
            assert response.status_code == 503
            assert response.headers["Retry-After"] == "1"
            assert response.json()["error"]["code"] == "STORE_UNAVAILABLE"
            assert "127.0.0.1" not in response.text  # no connection details leak to the client
        assert dead.get("/health/ready").status_code == 503
        assert dead.get("/health/live").status_code == 200
        assert elapsed < 15, f"three failed requests took {elapsed:.1f}s"
