"""End-to-end fixtures: the whole platform through the gateway (DESIGN.md section 11).

Run with ``make e2e`` against a running stack (``make up && make seed``). Everything here talks
HTTP to the gateway, except two things the gateway does not expose: the product service's
``/metrics`` (cache counters) and ``docker compose`` (to stop and start a consumer).

Each test creates its own orders under a unique ``e2e-*`` customer, so runs never collide.
"""

import json
import os
import re
import shlex
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import boto3
import httpx2
import pytest

GATEWAY = os.environ.get("E2E_GATEWAY_URL", "http://localhost:8080")
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


def compose(*args: str) -> str:
    """Run a docker compose command (needs ``make e2e``) and return its stdout."""
    if not COMPOSE:
        pytest.skip("E2E_COMPOSE is not set: run through `make e2e`")
    done = subprocess.run(  # noqa: S603
        [*shlex.split(COMPOSE), *args], check=True, capture_output=True, text=True, timeout=120
    )
    return done.stdout


def notification_types(http: httpx2.Client, order_id: str) -> list[str]:
    response = http.get("/api/v1/notifications", params={"order_id": order_id})
    assert response.status_code == 200, response.text
    return [item["type"] for item in response.json()["items"]]


QUEUES = ("inventory-order-events", "order-inventory-events", "notification-events")
DEAD_LETTER_QUEUES = tuple(f"{queue}-dlq" for queue in QUEUES)


def aws(service: str) -> Any:
    """LocalStack with dummy credentials, whatever the shell exports (this suite never reaches AWS)."""
    return boto3.client(
        service,
        region_name="us-east-1",
        endpoint_url=os.environ.get("E2E_AWS_ENDPOINT", "http://localhost:4566"),
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def queue_counts(queue: str) -> dict[str, int]:
    """Messages waiting and in flight (a count is not a receive: nothing moves)."""
    sqs = aws("sqs")
    attributes = sqs.get_queue_attributes(
        QueueUrl=sqs.get_queue_url(QueueName=queue)["QueueUrl"],
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]
    return {
        "visible": int(attributes["ApproximateNumberOfMessages"]),
        "in_flight": int(attributes["ApproximateNumberOfMessagesNotVisible"]),
    }


def metric(text: str, name: str, **labels: str) -> float:
    """Sum of the samples of ``name`` whose labels include ``labels`` (0 if there are none)."""
    total = 0.0
    for line in text.splitlines():
        if not line.startswith((name + "{", name + " ")):
            continue
        sample_labels = dict(re.findall(r'(\w+)="([^"]*)"', line))
        if all(sample_labels.get(k) == v for k, v in labels.items()):
            total += float(line.rsplit(" ", 1)[1])
    return total


API_SERVICES = {
    8001: "product-service",
    8002: "inventory-service",
    8003: "order-service",
    8004: "notification-service",
}


def metric_by_pod(text: str, name: str, **labels: str) -> dict[str, float]:
    """``metric`` per pod, from a scrape whose blocks start with ``# pod=<name>`` (Kubernetes);
    one entry, ``""``, for a single process. Pods come and go (the HPA), so a before/after
    comparison must use only the pods present in both."""
    blocks = re.split(r"^# pod=(\S+)$", text, flags=re.MULTILINE)
    if len(blocks) == 1:
        return {"": metric(text, name, **labels)}
    return {
        pod: metric(body, name, **labels)
        for pod, body in zip(blocks[1::2], blocks[2::2], strict=True)
    }


def api_metrics(port: int) -> str:
    """``/metrics`` of an API. On Kubernetes it has several replicas behind one Service, so the
    shim reads every pod and the samples add up (``metric`` sums them)."""
    if os.environ.get("E2E_K8S"):
        return compose("scrape", API_SERVICES[port], str(port))
    return httpx2.get(f"http://localhost:{port}/metrics", timeout=5).text


def process_metrics(service: str) -> str:
    """``/metrics`` of a consumer or relay: port 9000 is internal, so ask from inside."""
    return compose(
        "exec",
        "-T",
        service,
        "python",
        "-c",
        "import urllib.request as u;print(u.urlopen('http://127.0.0.1:9000/metrics').read().decode())",
    )


def psql(database: str, sql: str) -> str:
    """Run SQL as the superuser inside the Compose postgres (never the app roles)."""
    return compose(
        "exec", "-T", "postgres", "psql", "-U", "postgres", "-d", database, "-At", "-c", sql
    ).strip()


def order_ids_sql(ids: list[str]) -> str:
    assert all(re.fullmatch(r"[0-9A-Z]{26}", i) for i in ids), ids  # ULIDs only: safe to inline
    return ", ".join(f"'{i}'" for i in ids)


def container_restarts(service: str) -> int:
    if os.environ.get("E2E_K8S"):  # the cluster shim answers; there is no container id to inspect
        return int(compose("restarts", service).strip())
    container = compose("ps", "-q", service).strip()
    done = subprocess.run(  # noqa: S603
        ["docker", "inspect", "-f", "{{.RestartCount}}", container],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return int(done.stdout.strip())


def status_of(url: str) -> int:
    try:
        return httpx2.get(url, timeout=5).status_code
    except httpx2.TransportError:
        return 0


def assert_platform_whole(http: httpx2.Client) -> None:
    """Every API ready, every Compose service running and healthy, every DLQ empty."""
    for port in (8001, 8002, 8003, 8004):
        assert httpx2.get(f"http://localhost:{port}/health/ready", timeout=5).status_code == 200
    states = json.loads("[" + ",".join(compose("ps", "--format", "json").splitlines()) + "]")
    unhealthy = {
        s["Service"]: s["Health"]
        for s in states
        if s.get("Health") not in ("healthy", "") or s.get("State") != "running"
        if not s["Service"].endswith("-migrate")
    }
    assert unhealthy == {}
    assert {q: queue_counts(q) for q in DEAD_LETTER_QUEUES} == {
        q: {"visible": 0, "in_flight": 0} for q in DEAD_LETTER_QUEUES
    }
