"""End-to-end fixtures: the whole platform through the gateway (DESIGN.md section 11).

Run with ``make e2e`` against a running stack (``make up && make seed``). Everything here talks
HTTP to the gateway, except two things the gateway does not expose: the product service's
``/metrics`` (cache counters) and ``docker compose`` (to stop and start a consumer).

Each test creates its own orders under a unique ``e2e-*`` customer, so runs never collide.
"""

import os
import shlex
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx2
import pytest

GATEWAY = os.environ.get("E2E_GATEWAY_URL", "http://localhost:8080")
PRODUCT_METRICS = os.environ.get("E2E_PRODUCT_METRICS_URL", "http://localhost:8001/metrics")
COMPOSE = os.environ.get("E2E_COMPOSE")  # the Makefile's compose command; unset = no drills

POLL_INTERVAL_S = 0.25
POLL_TIMEOUT_S = 15.0

# Seeded products (local/seed/catalog.py). Their stock is set explicitly by each test.
SKU_A = "SKU-BELT-BLK-95"
SKU_B = "SKU-BOOT-BRN-43"


@pytest.fixture(scope="session")
def http() -> Iterator[httpx2.Client]:
    with httpx2.Client(base_url=GATEWAY, timeout=10.0) as client:
        try:
            client.get("/api/v1/products", params={"size": 1}).raise_for_status()
        except (httpx2.TransportError, httpx2.HTTPStatusError) as exc:
            pytest.exit(
                f"the platform is not answering on {GATEWAY}: `make up && make seed` ({exc})"
            )
        yield client


@pytest.fixture
def customer() -> str:
    return f"e2e-{uuid.uuid4().hex[:12]}"


def set_stock(http: httpx2.Client, sku: str, available: int) -> None:
    response = http.put(f"/api/v1/inventory/{sku}", json={"available": available})
    assert response.status_code == 200, response.text


def stock(http: httpx2.Client, sku: str) -> dict[str, Any]:
    response = http.get(f"/api/v1/inventory/{sku}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def place_order(
    http: httpx2.Client, customer: str, sku: str, quantity: int, key: str | None = None
) -> httpx2.Response:
    return http.post(
        "/api/v1/orders",
        json={"customer_id": customer, "items": [{"sku": sku, "quantity": quantity}]},
        headers={"Idempotency-Key": key or f"e2e-{uuid.uuid4()}"},
    )


def wait_for(
    description: str,
    probe: Callable[[], Any],
    *,
    timeout_s: float = POLL_TIMEOUT_S,
    interval_s: float = POLL_INTERVAL_S,
) -> Any:
    """Poll until ``probe`` returns something truthy; fail with the last value if it never does."""
    deadline = time.monotonic() + timeout_s
    last: Any = None
    while time.monotonic() < deadline:
        last = probe()
        if last:
            return last
        time.sleep(interval_s)
    raise AssertionError(f"timed out after {timeout_s}s waiting for {description}; last: {last!r}")


def wait_for_status(http: httpx2.Client, order_id: str, wanted: str) -> dict[str, Any]:
    def probe() -> dict[str, Any] | None:
        body: dict[str, Any] = http.get(f"/api/v1/orders/{order_id}").json()
        return body if body.get("status") == wanted else None

    result: dict[str, Any] = wait_for(f"order {order_id} to become {wanted}", probe)
    return result


def compose(*args: str) -> None:
    if not COMPOSE:
        pytest.skip("E2E_COMPOSE is not set: run through `make e2e`")
    subprocess.run([*shlex.split(COMPOSE), *args], check=True, capture_output=True, timeout=120)  # noqa: S603
