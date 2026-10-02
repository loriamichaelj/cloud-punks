"""The acceptance test (DESIGN.md section 11, steps 1 to 10)."""

import json
import os
import time
import uuid
from typing import Any

import httpx2
import pytest
from conftest import (
    E2E_CLOUD,
    SKU_A,
    SKU_B,
    api_metrics,
    assert_platform_whole,
    aws,
    compose,
    metric_by_pod,
    notification_types,
    place_order,
    set_stock,
    stock,
    wait_for,
    wait_for_status,
)
from cwlogs import find_log_message

# LocalStack's function is named low-stock-alert; the cloud's carries the loria- prefix.
LAMBDA_LOG_GROUP = os.environ.get("E2E_LAMBDA_LOG_GROUP", "/aws/lambda/low-stock-alert")


def _logs() -> Any:
    return aws("logs")


def cache_hits(keyspace: str) -> dict[str, float]:
    return metric_by_pod(api_metrics(8001), "cache_hits_total", keyspace=keyspace)


def test_step_1_the_catalog_is_seeded_and_a_second_read_is_a_cache_hit(http: httpx2.Client) -> None:
    listing = http.get("/api/v1/products", params={"size": 5})
    assert listing.status_code == 200
    assert listing.json()["total"] >= 20

    http.get(f"/api/v1/products/{SKU_A}")  # may be the miss that fills the cache
    before = cache_hits("product")
    second = http.get(f"/api/v1/products/{SKU_A}")

    assert second.status_code == 200
    after = cache_hits("product")
    # exactly one more hit, on whichever replica answered (pods that came or went are ignored)
    assert sum(after[pod] - before[pod] for pod in before.keys() & after.keys()) == 1


def test_steps_2_to_5_and_8_an_order_is_confirmed_reserves_stock_and_is_idempotent(
    http: httpx2.Client, customer: str
) -> None:
    set_stock(http, SKU_A, 20)  # step 2: a known starting level
    start = stock(http, SKU_A)
    assert start["available"] == 20

    # step 3
    key = f"e2e-key-{customer}"
    created = place_order(http, customer, SKU_A, 2, key)
    assert created.status_code == 202, created.text
    assert created.json()["status"] == "PENDING"
    order_id = created.json()["order_id"]

    # step 4
    confirmed = wait_for_status(http, order_id, "CONFIRMED")
    assert confirmed["status_reason"] is None

    # step 6: one notification per event, in the order the events happened
    wait_for(
        "both notifications",
        lambda: notification_types(http, order_id) == ["InventoryReserved", "OrderStatusUpdated"],
    )

    # step 5: exactly two units, moved from available to reserved
    after = stock(http, SKU_A)
    assert (after["available"], after["reserved"]) == (18, start["reserved"] + 2)

    # step 8: the same key replays the same order and touches nothing
    replay = place_order(http, customer, SKU_A, 2, key)
    assert replay.status_code in (200, 202)
    assert replay.json()["order_id"] == order_id
    assert stock(http, SKU_A)["available"] == 18


def test_a_known_sku_with_too_little_stock_is_refused_synchronously(
    http: httpx2.Client, customer: str
) -> None:
    set_stock(http, SKU_A, 1)

    response = place_order(http, customer, SKU_A, 5)

    assert response.status_code == 409
    assert stock(http, SKU_A)["available"] == 1


def test_step_7_an_order_the_inventory_later_cannot_fill_is_rejected_asynchronously(
    http: httpx2.Client, customer: str
) -> None:
    set_stock(http, SKU_B, 3)
    compose("stop", "inventory-consumer")
    try:
        created = place_order(http, customer, SKU_B, 2)  # the advisory pre-check passes
        assert created.status_code == 202, created.text
        order_id = created.json()["order_id"]
        set_stock(http, SKU_B, 0)  # the stock disappears before the consumer gets to the order
        assert http.get(f"/api/v1/orders/{order_id}").json()["status"] == "PENDING"
    finally:
        compose("start", "inventory-consumer")

    rejected = wait_for_status(http, order_id, "REJECTED")

    assert rejected["status_reason"] == "OUT_OF_STOCK"
    wait_for(
        "the rejection notifications",
        lambda: notification_types(http, order_id) == ["InventoryFailed", "OrderStatusUpdated"],
    )
    assert stock(http, SKU_B)["available"] == 0  # nothing was taken


@pytest.mark.parametrize("quantity", [1, 3])
def test_stock_is_never_oversold_by_a_burst_of_orders(
    http: httpx2.Client, customer: str, quantity: int
) -> None:
    """Five orders race for stock that fits only some of them: the books must balance."""
    set_stock(http, SKU_A, 4)
    before = stock(http, SKU_A)
    orders = [place_order(http, f"{customer}-{i}", SKU_A, quantity) for i in range(5)]
    accepted = [o.json()["order_id"] for o in orders if o.status_code == 202]

    def all_terminal() -> list[str] | None:
        states = [http.get(f"/api/v1/orders/{oid}").json()["status"] for oid in accepted]
        return states if all(s != "PENDING" for s in states) else None

    states = wait_for("every order to reach a terminal status", all_terminal, timeout_s=30)

    confirmed = states.count("CONFIRMED")
    assert confirmed * quantity <= 4
    after = stock(http, SKU_A)
    assert after["available"] == 4 - confirmed * quantity
    assert after["reserved"] == before["reserved"] + confirmed * quantity


def test_notifications_for_an_unknown_order_are_an_empty_list(http: httpx2.Client) -> None:
    response = http.get("/api/v1/notifications", params={"order_id": "01J9Z6R0C4ZZZZZZZZZZZZZZZZ"})
    assert (response.status_code, response.json()) == (200, {"items": []})


def test_a_low_stock_reservation_triggers_the_lambda(http: httpx2.Client, customer: str) -> None:
    """Stock 3, order 1: 2 remain, below the threshold of 5. The Lambda logs a `low_stock` record
    (EMF) that LocalStack's CloudWatch Logs keeps."""
    # Records older than this test cannot be ours; two minutes of margin covers clock skew.
    since_ms = int(time.time() * 1000) - 120_000
    set_stock(http, SKU_A, 3)
    order_id = place_order(http, customer, SKU_A, 1).json()["order_id"]
    wait_for_status(http, order_id, "CONFIRMED")

    def logged() -> str | None:
        return find_log_message(_logs(), LAMBDA_LOG_GROUP, order_id, since_ms=since_ms)

    # Real CloudWatch ingests a cold Lambda's first record slower than LocalStack does, and rate-limits
    # FilterLogEvents (about 5 a second), so the cloud polls every 3 s for up to 90 s.
    record = json.loads(
        wait_for(
            "the low_stock log record",
            logged,
            timeout_s=90 if E2E_CLOUD else 30,
            interval_s=3 if E2E_CLOUD else 0.25,
        )
    )
    assert (record["event"], record["sku"], record["remaining"]) == ("low_stock", SKU_A, 2)
    assert record["LowStockDetected"] == 1


def test_step_9_every_process_is_ready_and_no_dead_letters_exist(http: httpx2.Client) -> None:
    assert_platform_whole(http)


def test_step_10_one_correlation_id_runs_through_every_service(
    http: httpx2.Client, customer: str
) -> None:
    correlation_id = f"e2e-corr-{uuid.uuid4().hex[:12]}"
    set_stock(http, SKU_A, 20)
    created = http.post(
        "/api/v1/orders",
        json={"customer_id": customer, "items": [{"sku": SKU_A, "quantity": 1}]},
        headers={"Idempotency-Key": f"e2e-{uuid.uuid4()}", "X-Correlation-ID": correlation_id},
    )
    order_id = created.json()["order_id"]
    wait_for_status(http, order_id, "CONFIRMED")
    wait_for(
        "the status notification",
        lambda: "OrderStatusUpdated" in notification_types(http, order_id),
    )
    expected = {
        "order-service",  # the request itself
        "inventory-service",  # the availability pre-check
        "inventory-consumer",  # the reservation
        "order-consumer",  # the status change
        "notification-consumer",  # both notifications
    }

    def services_that_logged() -> set[str] | None:
        logs = compose("logs", "--no-color", "--since", "2m")
        seen = {
            line.split("|", 1)[0].strip().removesuffix("-1").removeprefix("retail-")
            for line in logs.splitlines()
            if correlation_id in line
        }
        return seen if expected <= seen else None

    assert wait_for("the correlation id in every service's logs", services_that_logged)
