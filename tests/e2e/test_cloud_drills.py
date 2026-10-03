"""The failure drills on the dev EKS cluster (DESIGN.md sections 11 and 13, Phase 4): break one thing by
configuration, see the platform notice, put it back, see it recover.

Run one at a time through the "Drills" workflow. They take minutes on purpose: the platform is judged by
its real timings (the sweeper counts an order stuck after five minutes, an alert waits its `for`), not by
shortened ones. Each restores what it changed in a ``finally``. Besides what the drill asserts through
Prometheus, a person should see the emails the alarms and alerts send, listed in the workflow's summary.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import httpx2
import pytest
from cloud_drills import alert_state, env_override, prom_value
from conftest import (
    E2E_CLOUD,
    SKU_A,
    assert_platform_whole,
    compose,
    place_order,
    set_stock,
    stock,
    wait_for,
)

pytestmark = pytest.mark.skipif(
    not E2E_CLOUD, reason="the cloud drills run on the dev EKS cluster only"
)


@contextmanager
def stopped(*services: str) -> Iterator[None]:
    """Scale processes to zero for the length of the block and back up, however it ends."""
    compose("stop", *services)
    try:
        yield
    finally:
        compose("start", *services)


def statuses(http: httpx2.Client, ids: list[str]) -> set[str]:
    return {http.get(f"/api/v1/orders/{i}").json()["status"] for i in ids}


def all_decided(http: httpx2.Client, ids: list[str]) -> bool:
    return "PENDING" not in statuses(http, ids)


def test_cloud_drill_consumer_down(http: httpx2.Client, customer: str) -> None:
    """Orders wait while the inventory consumer is away; the platform notices; nothing is lost on return."""
    set_stock(http, SKU_A, 50)
    start = stock(http, SKU_A)
    stuck_before = prom_value('orders_stuck{service="order-relay"}') or 0

    with stopped("inventory-consumer"):
        created = [place_order(http, f"{customer}-{i}", SKU_A, 1) for i in range(5)]
        assert [c.status_code for c in created] == [202] * 5  # the platform keeps accepting orders
        ids = [c.json()["order_id"] for c in created]
        assert statuses(http, ids) == {"PENDING"}  # and decides none of them

        # Detection. After five minutes the relay's sweeper counts them, and the alert needs two more.
        # (The queue-age alarm in CloudWatch sends its own email a few minutes in.)
        wait_for(
            "orders_stuck to rise by five",
            lambda: (prom_value('orders_stuck{service="order-relay"}') or 0) - stuck_before >= 5,
            timeout_s=540,
            interval_s=15,
        )
        wait_for(
            "the OrdersStuck alert to fire",
            lambda: alert_state("OrdersStuck") == "firing",
            timeout_s=300,
            interval_s=15,
        )

    # Recovery: the queue drains, every order is confirmed once, the alert clears.
    wait_for(
        "every order to be decided", lambda: all_decided(http, ids), timeout_s=180, interval_s=5
    )
    assert statuses(http, ids) == {"CONFIRMED"}
    after = stock(http, SKU_A)
    assert (after["available"], after["reserved"]) == (
        start["available"] - 5,
        start["reserved"] + 5,
    )
    wait_for(
        "orders_stuck to return to its starting value",
        lambda: (prom_value('orders_stuck{service="order-relay"}') or 0) <= stuck_before,
        timeout_s=240,
        interval_s=15,
    )
    wait_for(
        "the OrdersStuck alert to resolve",
        lambda: alert_state("OrdersStuck") == "inactive",
        timeout_s=300,
        interval_s=15,
    )
    assert_platform_whole(http)


def test_cloud_drill_bus_down(http: httpx2.Client, customer: str) -> None:
    """ADR-04: with the bus unreachable for the relay only, POST /orders still answers 202 and nothing is lost."""
    set_stock(http, SKU_A, 20)
    start = stock(http, SKU_A)
    failures_before = prom_value('events_publish_failures_total{service="order-relay"}') or 0

    # The relay publishes to a bus that does not exist, so every PutEvents fails; the API is untouched.
    with env_override("order-relay", EVENT_BUS_NAME=f"e2e-no-such-bus-{uuid.uuid4().hex[:8]}"):
        created = [place_order(http, f"{customer}-{i}", SKU_A, 1) for i in range(3)]
        assert [c.status_code for c in created] == [202] * 3  # the outbox absorbed them
        ids = [c.json()["order_id"] for c in created]

        # Detection: rows pile up unpublished, failures are counted, and the relay stays ready (a bus
        # outage must not take it out of rotation). The OutboxLag alert follows once the oldest row is
        # a minute old and has stayed so for a minute.
        wait_for(
            "three unpublished outbox rows",
            lambda: (prom_value('outbox_unpublished{service="order-relay"}') or 0) >= 3,
            timeout_s=120,
            interval_s=10,
        )
        wait_for(
            "publish failures to be counted",
            lambda: (
                (prom_value('events_publish_failures_total{service="order-relay"}') or 0)
                - failures_before
                >= 3
            ),
            timeout_s=120,
            interval_s=10,
        )
        assert prom_value('up{service="order-relay"}') == 1
        assert statuses(http, ids) == {"PENDING"}
        wait_for(
            "the OutboxLag alert to fire",
            lambda: alert_state("OutboxLag") == "firing",
            timeout_s=300,
            interval_s=15,
        )

    # Recovery: the relay is back on the real bus and drains the outbox; each order is decided once.
    wait_for(
        "every order to be decided", lambda: all_decided(http, ids), timeout_s=240, interval_s=5
    )
    assert statuses(http, ids) == {"CONFIRMED"}
    assert stock(http, SKU_A)["available"] == start["available"] - 3
    wait_for(
        "the outbox to be empty",
        lambda: (prom_value('outbox_unpublished{service="order-relay"}') or 0) == 0,
        timeout_s=120,
        interval_s=10,
    )
    wait_for(
        "the OutboxLag alert to resolve",
        lambda: alert_state("OutboxLag") == "inactive",
        timeout_s=300,
        interval_s=15,
    )
    assert_platform_whole(http)
