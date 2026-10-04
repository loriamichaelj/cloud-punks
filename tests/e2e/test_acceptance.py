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
    SKU_N,
    api_metrics,
    assert_platform_whole,
    aws,
    bid_status,
    compose,
    metric_by_pod,
    notification_types,
    owner,
    place_bid,
    place_order,
    put_up,
    reset_one_of_a_kind,
    set_stock,
    stock,
    wait_for,
    wait_for_status,
)
from cwlogs import find_log_message, releases_that_logged

# LocalStack's function is named low-stock-alert; the cloud's carries the loria- prefix.
LAMBDA_LOG_GROUP = os.environ.get("E2E_LAMBDA_LOG_GROUP", "/aws/lambda/low-stock-alert")
# Prometheus and Grafana of the monitoring release, port-forwarded by app-deploy (the cloud only).
PROMETHEUS_URL = os.environ.get("E2E_PROMETHEUS_URL", "http://localhost:9090")
GRAFANA_URL = os.environ.get("E2E_GRAFANA_URL", "http://localhost:3000")
ALERTMANAGER_URL = os.environ.get("E2E_ALERTMANAGER_URL", "http://localhost:9093")
# Where Container Insights writes the application containers' logs (the cloud only).
APP_LOG_GROUP = os.environ.get(
    "E2E_APP_LOG_GROUP", "/aws/containerinsights/loria-retail-dev/application"
)


def _logs() -> Any:
    return aws("logs")


def cache_hits(keyspace: str) -> dict[str, float]:
    return metric_by_pod(api_metrics(8001), "cache_hits_total", keyspace=keyspace)


def test_step_1_the_catalog_is_seeded_and_a_second_read_is_a_cache_hit(http: httpx2.Client) -> None:
    listing = http.get("/api/v1/products", params={"size": 5})
    assert listing.status_code == 200
    assert listing.json()["total"] >= 100  # the 100 CloudPunks, plus the suite's own while it runs
    assert http.get("/api/v1/products/CP-0001").json()["currency"] == "ETH"

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


# --- the market: buy, put up for bid, bid, accept, resell (DESIGN.md section 16.8) -----------------


def test_market_a_cloudpunk_is_bought_put_up_for_bid_and_resold_to_the_accepted_bidder(
    http: httpx2.Client, customer: str
) -> None:
    alice, bob, carol = f"{customer}-alice", f"{customer}-bob", f"{customer}-carol"
    reset_one_of_a_kind(http, SKU_N)

    # Red: bought from the platform at its price; the buyer becomes the owner (blue).
    bought = place_order(http, alice, SKU_N, 1)
    assert bought.status_code == 202, bought.text
    first = wait_for_status(http, bought.json()["order_id"], "CONFIRMED")
    assert first["items"][0]["seller"] is None
    assert owner(http, SKU_N) == alice
    again = place_order(http, bob, SKU_N, 1)  # no longer for sale by the platform
    assert (again.status_code, again.json()["error"]["code"]) == (409, "OUT_OF_STOCK")

    # Purple: only the owner can put it up for bid.
    assert put_up(http, bob, SKU_N).json()["error"]["code"] == "NOT_OWNER"
    listing = put_up(http, alice, SKU_N)
    assert (listing.status_code, listing.json()["status"]) == (201, "OPEN")

    low = place_bid(http, bob, SKU_N, "12.00").json()
    high = place_bid(http, carol, SKU_N, "15.00").json()
    assert place_bid(http, alice, SKU_N, "99.00").json()["error"]["code"] == "OWN_ITEM"
    withdrawn = http.delete(f"/api/v1/bids/{low['bid_id']}", params={"customer_id": bob})
    assert withdrawn.json()["status"] == "WITHDRAWN"

    # The owner accepts: the bidder's order, at the bid amount, bought from the owner.
    accepted = http.post(f"/api/v1/bids/{high['bid_id']}/accept", json={"customer_id": alice})
    assert accepted.status_code == 202, accepted.text
    resale = wait_for_status(http, accepted.json()["order_id"], "CONFIRMED")
    assert (resale["customer_id"], resale["total_amount"]) == (carol, "15.00")
    assert resale["items"][0]["seller"] == alice

    # Blue again, for the new owner; the listing and the bids are settled.
    assert owner(http, SKU_N) == carol
    assert http.get("/api/v1/listings", params={"sku": SKU_N}).json()["total"] == 0
    assert bid_status(http, SKU_N, high["bid_id"]) == "FILLED"
    assert bid_status(http, SKU_N, low["bid_id"]) == "WITHDRAWN"
    sales = [
        (e["from"], e["to"], e["amount"])
        for e in http.get("/api/v1/activity", params={"sku": SKU_N}).json()["items"]
        if e["kind"] == "SALE" and e["to"] in (alice, carol)
    ]
    assert sales == [(alice, carol, "15.00"), (None, alice, "10.00")]  # newest first
    wait_for(  # the buyer's notifications arrive through the bus, after the status changes
        "the resale's OrderStatusUpdated notification",
        lambda: "OrderStatusUpdated" in notification_types(http, resale["order_id"]) or None,
    )


def test_market_taking_a_cloudpunk_off_the_market_closes_its_bids(
    http: httpx2.Client, customer: str
) -> None:
    alice, bob = f"{customer}-alice", f"{customer}-bob"
    reset_one_of_a_kind(http, SKU_N)
    wait_for_status(http, place_order(http, alice, SKU_N, 1).json()["order_id"], "CONFIRMED")
    put_up(http, alice, SKU_N)
    bid = place_bid(http, bob, SKU_N, "11.00").json()

    off = http.delete(f"/api/v1/listings/{SKU_N}", params={"customer_id": alice})

    assert off.json()["status"] == "CANCELLED"
    assert bid_status(http, SKU_N, bid["bid_id"]) == "CLOSED"
    late = place_bid(http, bob, SKU_N, "12.00")
    assert (late.status_code, late.json()["error"]["code"]) == (409, "NOT_LISTED")
    assert owner(http, SKU_N) == alice


def test_market_two_buyers_race_for_one_unsold_cloudpunk_and_exactly_one_owns_it(
    http: httpx2.Client, customer: str
) -> None:
    reset_one_of_a_kind(http, SKU_N)
    buyers = [f"{customer}-{i}" for i in range(4)]

    responses = [place_order(http, b, SKU_N, 1) for b in buyers]  # the pre-check may pass several

    accepted = [r.json() for r in responses if r.status_code == 202]
    finals = [
        wait_for(
            f"order {o['order_id']} to settle",
            lambda o=o: (
                body
                if (body := http.get(f"/api/v1/orders/{o['order_id']}").json())["status"]
                != "PENDING"
                else None
            ),
        )
        for o in accepted
    ]
    confirmed = [f for f in finals if f["status"] == "CONFIRMED"]
    assert len(confirmed) == 1
    assert owner(http, SKU_N) == confirmed[0]["customer_id"]
    assert all(r.status_code in (202, 409) for r in responses)


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


@pytest.mark.skipif(
    not E2E_CLOUD, reason="Container Insights ships logs to CloudWatch only in the cloud"
)
def test_cloud_one_order_is_traced_across_the_services_in_cloudwatch(
    http: httpx2.Client, customer: str
) -> None:
    """P4.2 done-when: one correlation id, found in CloudWatch in every process that handled the order."""
    correlation_id = f"e2e-corr-{uuid.uuid4().hex[:12]}"
    started_s = int(time.time()) - 60
    set_stock(http, SKU_A, 20)
    created = http.post(
        "/api/v1/orders",
        json={"customer_id": customer, "items": [{"sku": SKU_A, "quantity": 1}]},
        headers={"Idempotency-Key": f"e2e-{uuid.uuid4()}", "X-Correlation-ID": correlation_id},
    )
    wait_for_status(http, created.json()["order_id"], "CONFIRMED")
    expected = {
        "order-service",
        "inventory-service",
        "inventory-consumer",
        "order-consumer",
        "notification-consumer",
    }
    last: dict[str, int] = {}

    def traced() -> dict[str, int] | None:
        nonlocal last
        last = releases_that_logged(
            _logs(), APP_LOG_GROUP, correlation_id, start_s=started_s, end_s=int(time.time()) + 60
        )
        return last if expected <= last.keys() else None

    # Fluent Bit ships in batches and Logs Insights lags behind it, so allow a few minutes.
    try:
        wait_for("the correlation id in CloudWatch", traced, timeout_s=300, interval_s=15)
    except AssertionError as error:
        raise AssertionError(
            f"{error}; releases seen: {sorted(last)}; missing: {sorted(expected - last.keys())}"
        ) from None


@pytest.mark.skipif(not E2E_CLOUD, reason="the monitoring release runs only in the cloud cluster")
def test_cloud_prometheus_scrapes_every_process() -> None:
    """P4.3: Prometheus discovers all eight application processes, and the SLI source metric exists."""
    expected = {
        "product-service",
        "inventory-service",
        "order-service",
        "notification-service",
        "inventory-consumer",
        "order-consumer",
        "order-relay",
        "notification-consumer",
    }

    def query(expression: str) -> list[dict[str, Any]]:
        response = httpx2.get(
            f"{PROMETHEUS_URL}/api/v1/query", params={"query": expression}, timeout=10
        )
        assert response.status_code == 200, response.text
        result: list[dict[str, Any]] = response.json()["data"]["result"]
        return result

    def all_up() -> set[str] | None:
        up = {series["metric"].get("service", "") for series in query('up{job="retail"} == 1')}
        return up if expected <= up else None

    # The pods are new after a deploy and Prometheus scrapes every 15 s.
    wait_for("Prometheus to scrape every process", all_up, timeout_s=180, interval_s=5)
    # The requests the earlier tests made are the SLIs' source.
    assert query('http_requests_total{route=~"/api/.*"}'), "no /api request metrics were scraped"


@pytest.mark.skipif(not E2E_CLOUD, reason="the monitoring release runs only in the cloud cluster")
def test_cloud_grafana_serves_the_dashboard_view_only() -> None:
    """P4.3: Grafana is up under /grafana with the provisioned dashboard, and changes nothing."""
    health = httpx2.get(f"{GRAFANA_URL}/grafana/api/health", timeout=10)
    assert health.status_code == 200, health.text
    assert health.json()["database"] == "ok"
    dashboard = httpx2.get(f"{GRAFANA_URL}/grafana/api/dashboards/uid/retail-platform", timeout=10)
    assert dashboard.status_code == 200, dashboard.text
    titles = {panel["title"] for panel in dashboard.json()["dashboard"]["panels"]}
    assert "Availability (target 99.5%)" in titles
    # View only: no admin login, and an anonymous write is refused.
    assert (
        httpx2.get(
            f"{GRAFANA_URL}/grafana/api/user", auth=("admin", "admin"), timeout=10
        ).status_code
        == 401
    )
    write = httpx2.post(f"{GRAFANA_URL}/grafana/api/folders", json={"title": "x"}, timeout=10)
    assert write.status_code == 403, write.text


@pytest.mark.skipif(not E2E_CLOUD, reason="the monitoring release runs only in the cloud cluster")
def test_cloud_alert_rules_are_loaded_and_alertmanager_is_connected() -> None:
    """P4.4: the four rules are in Prometheus and healthy, and Prometheus reaches a ready Alertmanager."""
    rules = httpx2.get(f"{PROMETHEUS_URL}/api/v1/rules", timeout=10).json()["data"]["groups"]
    loaded = {rule["name"]: rule for group in rules for rule in group["rules"]}
    assert {"OutboxLag", "OrdersStuck", "PodRestartingRepeatedly", "TargetDown"} <= loaded.keys()
    assert all(rule["health"] == "ok" for rule in loaded.values()), loaded

    managers = httpx2.get(f"{PROMETHEUS_URL}/api/v1/alertmanagers", timeout=10).json()["data"]
    assert managers["activeAlertmanagers"], "Prometheus has no Alertmanager to send to"

    assert httpx2.get(f"{ALERTMANAGER_URL}/-/ready", timeout=10).status_code == 200
