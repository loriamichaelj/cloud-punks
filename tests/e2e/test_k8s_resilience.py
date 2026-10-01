"""Deleting any pod loses no order (M10). Runs only on the local cluster: ``make k8s-resilience``.

Steady order traffic runs while one pod of a workload is deleted (``kubectl delete pod``, which is
graceful). A request that fails is retried with the *same* Idempotency-Key, which is what a real
client does and why a retry can never create a second order. Afterwards every order must be
CONFIRMED and the stock must have dropped by exactly the number of orders.
"""

import json
import os
import threading
import time
import uuid

import httpx2
import pytest
from conftest import SKU_A, compose, set_stock, stock, wait_for

pytestmark = pytest.mark.skipif(
    not os.environ.get("E2E_K8S"), reason="needs the local cluster: make k8s-resilience"
)

WORKLOADS = [
    "product-service",
    "inventory-service",
    "order-service",
    "notification-service",
    "inventory-consumer",
    "order-relay",
    "order-consumer",
    "notification-consumer",
    "ui",
]
ORDER_INTERVAL_S = 0.15
ATTEMPTS = 8


class Traffic:
    """Orders placed in a loop, each retried with its own key until accepted."""

    def __init__(self, http: httpx2.Client, customer: str) -> None:
        self._http = http
        self._customer = customer
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.accepted: list[str] = []
        self.retries = 0
        self.never_accepted = 0
        self.page_failures = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=60)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._place()
            try:  # the UI is a workload too: the page must keep loading
                if self._http.get("/", timeout=5).status_code != 200:
                    self.page_failures += 1
            except httpx2.TransportError:
                self.page_failures += 1
            time.sleep(ORDER_INTERVAL_S)

    def _place(self) -> None:
        key = f"k8s-{uuid.uuid4()}"
        body = {"customer_id": self._customer, "items": [{"sku": SKU_A, "quantity": 1}]}
        for attempt in range(ATTEMPTS):
            try:
                response = self._http.post(
                    "/api/v1/orders", json=body, headers={"Idempotency-Key": key}, timeout=5
                )
                if response.status_code in (200, 202):
                    self.accepted.append(response.json()["order_id"])
                    return
                if response.status_code not in (502, 503, 504):
                    pytest.fail(f"unexpected {response.status_code}: {response.text}")
            except httpx2.TransportError:
                pass
            self.retries += 1
            time.sleep(min(0.25 * 2**attempt, 2.0))
        self.never_accepted += 1


def healthy(service: str) -> bool:
    rows = [json.loads(line) for line in compose("ps", "--format", "json").splitlines() if line]
    return any(r["Service"] == service and r["Health"] == "healthy" for r in rows)


@pytest.mark.parametrize("workload", WORKLOADS)
def test_deleting_a_pod_loses_no_orders(http: httpx2.Client, workload: str) -> None:
    set_stock(http, SKU_A, 500)
    start = stock(http, SKU_A)
    traffic = Traffic(http, f"e2e-{uuid.uuid4().hex[:12]}")
    traffic.start()
    try:
        time.sleep(2)
        compose("kill-pod", workload)
        wait_for(f"{workload} to be healthy again", lambda: healthy(workload), timeout_s=90)
        time.sleep(3)
    finally:
        traffic.stop()

    assert traffic.never_accepted == 0
    assert traffic.accepted, "no traffic was generated"

    def all_confirmed() -> bool:
        states = [http.get(f"/api/v1/orders/{i}").json()["status"] for i in traffic.accepted]
        assert "REJECTED" not in states
        return all(s == "CONFIRMED" for s in states)

    wait_for("every order to be CONFIRMED", all_confirmed, timeout_s=90, interval_s=1)
    after = stock(http, SKU_A)
    orders = len(set(traffic.accepted))
    assert orders == len(traffic.accepted)  # a retry never made a second order
    assert after["available"] == start["available"] - orders
    assert after["reserved"] == start["reserved"] + orders
    print(
        f"\n{workload}: {orders} orders, {traffic.retries} retried requests, "
        f"{traffic.page_failures} failed page loads"
    )
