"""The acceptance test (DESIGN.md section 11, steps 1 to 8; 9 and 10 arrive with M7 and M9).

Step 6 needs the notification service's consumer, so it is not here until M7.
"""

import re

import httpx2
import pytest
from conftest import (
    PRODUCT_METRICS,
    SKU_A,
    SKU_B,
    compose,
    place_order,
    set_stock,
    stock,
    wait_for,
    wait_for_status,
)


def cache_hits(keyspace: str) -> float:
    text = httpx2.get(PRODUCT_METRICS, timeout=5).text
    match = re.search(
        rf'^cache_hits_total{{keyspace="{keyspace}"}} ([0-9.e+]+)$', text, re.MULTILINE
    )
    return float(match.group(1)) if match else 0.0


def test_step_1_the_catalog_is_seeded_and_a_second_read_is_a_cache_hit(http: httpx2.Client) -> None:
    listing = http.get("/api/v1/products", params={"size": 5})
    assert listing.status_code == 200
    assert listing.json()["total"] >= 20

    http.get(f"/api/v1/products/{SKU_A}")  # may be the miss that fills the cache
    before = cache_hits("product")
    second = http.get(f"/api/v1/products/{SKU_A}")

    assert second.status_code == 200
    assert cache_hits("product") == before + 1


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
