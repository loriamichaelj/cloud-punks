"""The failure drills (DESIGN.md section 11): break one thing, see it detected, see it recover.

Each drill restores what it broke in a ``finally``, so a failing drill cannot leave the stack
half-down for the next one. They run after the acceptance steps in ``make e2e``; one at a time:
``make drill-consumer-down`` (or ``-poison``, ``-duplicate``, ``-bus-down``, ``-cache-down``,
``-db-down``). The drills own the whole platform, so unlike the integration tests they use the
real queues, the real bus and the real relay.
"""

import json
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx2
from conftest import (
    SKU_A,
    api_metrics,
    assert_platform_whole,
    aws,
    compose,
    container_restarts,
    metric,
    order_ids_sql,
    place_order,
    process_metrics,
    psql,
    queue_counts,
    set_stock,
    status_of,
    stock,
    wait_for,
    wait_for_status,
)

from retail_common.events.envelope import Envelope
from retail_common.events.publisher import EventBridgePublisher

INVENTORY_QUEUE = "inventory-order-events"
BUS = "retail-events"
CONSUMER_LONG_POLL_S = 20


@contextmanager
def stopped(*services: str) -> Iterator[None]:
    """Stop services for the length of the block and start them again, however it ends."""
    compose("stop", *services)
    try:
        yield
    finally:
        compose("start", *services)


def settle(http: httpx2.Client, timeout_s: float = 60.0) -> None:
    """``assert_platform_whole``, retried while a restarted container finishes its health check."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            assert_platform_whole(http)
            return
        except AssertionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


def terminal_orders(http: httpx2.Client, ids: list[str]) -> list[str] | None:
    states = [http.get(f"/api/v1/orders/{i}").json()["status"] for i in ids]
    return states if all(s != "PENDING" for s in states) else None


def test_drill_consumer_down(http: httpx2.Client, customer: str) -> None:
    """Orders wait while the consumer is away, the alarm fires, and nothing is lost on return."""
    set_stock(http, SKU_A, 50)
    start = stock(http, SKU_A)
    waiting_before = queue_counts(INVENTORY_QUEUE)["visible"]
    stuck_before = metric(process_metrics("order-relay"), "orders_stuck")

    with stopped("inventory-consumer"):
        created = [place_order(http, f"{customer}-{i}", SKU_A, 1) for i in range(5)]
        assert [c.status_code for c in created] == [202] * 5
        ids = [c.json()["order_id"] for c in created]

        # detection 1: the work is queued, and nothing has been decided
        wait_for(
            "five orders waiting in the queue",
            lambda: queue_counts(INVENTORY_QUEUE)["visible"] - waiting_before == 5,
        )
        assert {http.get(f"/api/v1/orders/{i}").json()["status"] for i in ids} == {"PENDING"}

        # detection 2: after 5 minutes the sweeper counts them. Waiting that long is not an
        # option here, so age the five orders instead (our own e2e rows, nothing else).
        psql(
            "order_db",
            f"UPDATE orders SET created_at = now() - interval '10 minutes' "
            f"WHERE order_id IN ({order_ids_sql(ids)})",
        )
        wait_for(
            "orders_stuck to rise by five",
            lambda: metric(process_metrics("order-relay"), "orders_stuck") - stuck_before == 5,
            timeout_s=45,
        )

    # recovery: the queue drains, every order is confirmed once, the alarm clears
    wait_for("every order to be decided", lambda: terminal_orders(http, ids), timeout_s=45)
    assert {http.get(f"/api/v1/orders/{i}").json()["status"] for i in ids} == {"CONFIRMED"}
    after = stock(http, SKU_A)
    assert (after["available"], after["reserved"]) == (
        start["available"] - 5,
        start["reserved"] + 5,
    )
    wait_for(
        "orders_stuck to return to its starting value",
        lambda: metric(process_metrics("order-relay"), "orders_stuck") == stuck_before,
        timeout_s=45,
    )
    wait_for(
        "the queue to drain", lambda: queue_counts(INVENTORY_QUEUE)["visible"] == waiting_before
    )


def test_drill_poison_message_reaches_the_dlq_and_is_counted(http: httpx2.Client) -> None:
    marker = f"e2e-poison-{uuid.uuid4().hex[:12]}"
    sqs = aws("sqs")
    queue_url = sqs.get_queue_url(QueueName=INVENTORY_QUEUE)["QueueUrl"]
    dlq_url = sqs.get_queue_url(QueueName=f"{INVENTORY_QUEUE}-dlq")["QueueUrl"]
    poison_before = metric(
        process_metrics("inventory-consumer"), "events_consumed_total", outcome="poison"
    )
    original = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["VisibilityTimeout"])[
        "Attributes"
    ]["VisibilityTimeout"]

    # Five receives at the real 60 s visibility timeout would take five minutes. Shorten it for
    # the drill and put it back afterwards: the setting applies to each receive as it happens.
    sqs.set_queue_attributes(QueueUrl=queue_url, Attributes={"VisibilityTimeout": "1"})
    try:
        # A long poll that is already open took the old 60 s with it (found by running this
        # drill). The consumer polls for 20 s at most, so after that every poll is a new one.
        time.sleep(CONSUMER_LONG_POLL_S + 1)
        aws("events").put_events(
            Entries=[
                {
                    "Source": "retail.order",
                    "DetailType": "OrderCreated",
                    "Detail": json.dumps({"event_id": "not-a-ulid", "note": marker}),
                    "EventBusName": BUS,
                }
            ]
        )

        # detection: counted as poison, and parked in the DLQ after its receives
        wait_for(
            "the poison message in the DLQ",
            lambda: (
                marker
                in subprocess.run(  # noqa: S603
                    ["make", "-s", "dlq-peek", f"q={INVENTORY_QUEUE}-dlq"],  # noqa: S607
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=60,
                ).stdout
            ),
            timeout_s=60,
            interval_s=2,
        )
        poisoned = (
            metric(process_metrics("inventory-consumer"), "events_consumed_total", outcome="poison")
            - poison_before
        )
        assert poisoned >= 1
        wait_for(  # it left the queue, not just hid in it
            "the source queue to be empty",
            lambda: queue_counts(INVENTORY_QUEUE) == {"visible": 0, "in_flight": 0},
            timeout_s=15,
        )
    finally:
        sqs.set_queue_attributes(QueueUrl=queue_url, Attributes={"VisibilityTimeout": original})
        _delete_from_queue(sqs, dlq_url, marker)  # a poison message cannot be fixed: discard it

    assert_platform_whole(http)


def _delete_from_queue(sqs: Any, url: str, marker: str) -> None:
    for message in sqs.receive_message(
        QueueUrl=url, MaxNumberOfMessages=10, VisibilityTimeout=5, WaitTimeSeconds=1
    ).get("Messages", []):
        if marker in message["Body"]:
            sqs.delete_message(QueueUrl=url, ReceiptHandle=message["ReceiptHandle"])


def test_drill_poison_redrive_moves_a_parked_message_back_to_its_source() -> None:
    """The `make dlq-redrive` tool, on private queues so the platform's own are never touched."""
    sqs = aws("sqs")
    name = f"e2e-redrive-{uuid.uuid4().hex[:10]}"
    source = sqs.create_queue(QueueName=name)["QueueUrl"]
    dlq = sqs.create_queue(QueueName=f"{name}-dlq")["QueueUrl"]
    try:
        sqs.send_message(QueueUrl=dlq, MessageBody="fixed-and-ready")

        peeked = subprocess.run(  # noqa: S603
            ["make", "-s", "dlq-peek", f"q={name}-dlq"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout
        assert "1 message(s)" in peeked
        assert "fixed-and-ready" in peeked
        # peeking takes nothing: it is still there for the redrive
        assert wait_for("the message still in the DLQ", lambda: _count(sqs, dlq) == 1)

        moved = subprocess.run(  # noqa: S603
            ["make", "-s", "dlq-redrive", f"q={name}-dlq"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout
        assert "redrove 1 message(s)" in moved

        got = sqs.receive_message(QueueUrl=source, WaitTimeSeconds=2).get("Messages", [])
        assert [m["Body"] for m in got] == ["fixed-and-ready"]
        assert _count(sqs, dlq) == 0
    finally:
        sqs.delete_queue(QueueUrl=source)
        sqs.delete_queue(QueueUrl=dlq)


def _count(sqs: Any, url: str) -> int:
    attributes = sqs.get_queue_attributes(
        QueueUrl=url,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]
    return int(attributes["ApproximateNumberOfMessages"]) + int(
        attributes["ApproximateNumberOfMessagesNotVisible"]
    )


def test_drill_duplicate_delivery_decrements_stock_once(http: httpx2.Client, customer: str) -> None:
    set_stock(http, SKU_A, 20)
    created = place_order(http, customer, SKU_A, 2)
    order_id = created.json()["order_id"]
    wait_for_status(http, order_id, "CONFIRMED")
    after_first = stock(http, SKU_A)
    assert after_first["available"] == 18

    # The very envelope the relay published, sent twice more.
    payload = psql(
        "order_db",
        "SELECT payload FROM outbox WHERE detail_type = 'OrderCreated' "
        f"AND payload->'data'->>'order_id' = '{order_id}'",
    )
    envelope = Envelope.model_validate(json.loads(payload))
    inventory = "inventory-consumer"
    order = "order-consumer"
    dup = {"outcome": "duplicate"}
    inventory_before = metric(process_metrics(inventory), "events_consumed_total", **dup)
    order_before = metric(process_metrics(order), "events_consumed_total", **dup)

    result = EventBridgePublisher(aws("events"), BUS).publish([envelope, envelope])
    assert result.failed == {}

    # detection: both consumers count the repeats as duplicates
    wait_for(
        "the inventory consumer to count two duplicates",
        lambda: (
            metric(process_metrics(inventory), "events_consumed_total", **dup) - inventory_before
            == 2
        ),
    )
    # recovery needs nothing: the books are unchanged. The inventory service re-emits the same
    # outcome event each time, and the order consumer recognises it too.
    wait_for(
        "the order consumer to count the re-emitted outcome as duplicates",
        lambda: metric(process_metrics(order), "events_consumed_total", **dup) - order_before >= 1,
    )
    assert stock(http, SKU_A) == after_first
    assert http.get(f"/api/v1/orders/{order_id}").json()["status"] == "CONFIRMED"
    notifications = http.get("/api/v1/notifications", params={"order_id": order_id}).json()["items"]
    assert [n["type"] for n in notifications] == ["InventoryReserved", "OrderStatusUpdated"]
    assert_platform_whole(http)


def test_drill_bus_down_orders_are_accepted_and_nothing_is_lost(
    http: httpx2.Client, customer: str
) -> None:
    """ADR-04: with the bus unreachable for the relay only, POST /orders still answers 202."""
    set_stock(http, SKU_A, 20)
    start = stock(http, SKU_A)
    dead = f"e2e-dead-relay-{uuid.uuid4().hex[:8]}"

    compose("stop", "order-relay")
    try:
        # A second relay, identical but for an EventBridge address nothing listens on. The
        # per-service variable is named after the service id (..._EVENTBRIDGE, not ..._EVENTS).
        compose(
            "run",
            "-d",
            "--no-deps",
            "--name",
            dead,
            "-e",
            "AWS_ENDPOINT_URL_EVENTBRIDGE=http://127.0.0.1:1",
            "order-relay",
        )
        created = [place_order(http, f"{customer}-{i}", SKU_A, 1) for i in range(3)]
        assert [c.status_code for c in created] == [202, 202, 202]  # the outbox absorbed them
        ids = [c.json()["order_id"] for c in created]

        # detection: rows pile up unpublished with the reason recorded, the failures are counted,
        # and the relay stays ready (a bus outage must not take it out of rotation)
        rows_sql = (
            "SELECT count(*), min(attempts), max(last_error) FROM outbox WHERE published_at IS NULL "
            f"AND detail_type = 'OrderCreated' AND payload->'data'->>'order_id' IN ({order_ids_sql(ids)})"
        )

        def failing() -> str | None:
            count, attempts, error = psql("order_db", rows_sql).split("|")
            return error if count == "3" and int(attempts or 0) >= 1 and error else None

        error = wait_for("three unpublished rows with a recorded error", failing, timeout_s=30)
        assert "EndpointConnectionError" in error  # proves the dead address was really used
        dead_metrics = _exec_in(dead, "http://127.0.0.1:9000/metrics")
        assert metric(dead_metrics, "events_publish_failures_total") >= 3
        assert metric(dead_metrics, "outbox_unpublished") >= 3
        assert "200" in _exec_in(dead, "http://127.0.0.1:9000/health/ready", status_only=True)
        assert {http.get(f"/api/v1/orders/{i}").json()["status"] for i in ids} == {"PENDING"}
    finally:
        subprocess.run(["docker", "rm", "-f", dead], check=False, capture_output=True, timeout=60)  # noqa: S603, S607
        compose("start", "order-relay")

    # recovery: the working relay drains the outbox; every order decided exactly once
    wait_for("every order to be decided", lambda: terminal_orders(http, ids), timeout_s=45)
    assert {http.get(f"/api/v1/orders/{i}").json()["status"] for i in ids} == {"CONFIRMED"}
    assert stock(http, SKU_A)["available"] == start["available"] - 3
    for order_id in ids:
        published = psql(
            "order_db",
            f"SELECT count(*) FROM outbox WHERE payload->'data'->>'order_id' = '{order_id}' "
            "AND detail_type = 'OrderCreated' AND published_at IS NOT NULL",
        )
        assert published == "1"
        wait_for(
            "one notification per event",
            lambda order_id=order_id: (
                [
                    n["type"]
                    for n in http.get(
                        "/api/v1/notifications", params={"order_id": order_id}
                    ).json()["items"]
                ]
                == ["InventoryReserved", "OrderStatusUpdated"]
            ),
        )
    assert_platform_whole(http)


def _exec_in(container: str, url: str, *, status_only: bool = False) -> str:
    code = f"import urllib.request as u;r=u.urlopen('{url}');print(r.status if {status_only} else r.read().decode())"
    done = subprocess.run(  # noqa: S603
        ["docker", "exec", container, "python", "-c", code],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return done.stdout


def test_drill_cache_down_reads_still_work(http: httpx2.Client, customer: str) -> None:
    errors_before = metric(api_metrics(8001), "cache_errors_total")
    hits_before = metric(api_metrics(8001), "cache_hits_total")

    with stopped("valkey"):
        # reads fall back to PostgreSQL: a cache failure is a miss, never an error
        listing = http.get("/api/v1/products", params={"size": 3})
        detail = http.get(f"/api/v1/products/{SKU_A}")
        assert (listing.status_code, detail.status_code) == (200, 200)
        assert detail.json()["sku"] == SKU_A
        assert metric(api_metrics(8001), "cache_errors_total") > errors_before  # detection
        assert status_of("http://localhost:8001/health/ready") == 200  # cache is not required

        # and the platform keeps selling
        set_stock(http, SKU_A, 20)
        order_id = place_order(http, customer, SKU_A, 1).json()["order_id"]
        wait_for_status(http, order_id, "CONFIRMED")

    # recovery: the same process caches again, no restart needed
    def hits_again() -> bool:
        http.get(f"/api/v1/products/{SKU_A}")
        http.get(f"/api/v1/products/{SKU_A}")
        return metric(api_metrics(8001), "cache_hits_total") > hits_before

    wait_for("cache hits to resume", hits_again, timeout_s=20)
    settle(http)


def test_drill_db_down_is_a_503_not_a_500_and_recovers_without_restarts(
    http: httpx2.Client, customer: str
) -> None:
    services = ("product-service", "order-service", "order-relay", "order-consumer")
    restarts_before = {s: container_restarts(s) for s in services}

    with stopped("postgres"):
        # detection: not ready, still alive (a database outage must not restart anything)
        wait_for(
            "product and order to report not ready",
            lambda: all(
                status_of(f"http://localhost:{p}/health/ready") == 503 for p in (8001, 8003)
            ),
            timeout_s=20,
        )
        assert [status_of(f"http://localhost:{p}/health/live") for p in (8001, 8003)] == [200, 200]
        refused = place_order(http, customer, SKU_A, 1)
        assert refused.status_code == 503, refused.text  # never a 500
        assert refused.json()["error"]["code"] == "STORE_UNAVAILABLE"
        assert refused.headers["Retry-After"]
        assert refused.json()["error"]["message"]  # generic: no driver or host details
        assert "postgres" not in refused.text.lower()

    # recovery: ready again by itself, and orders flow end to end
    wait_for(
        "product and order to be ready again",
        lambda: all(status_of(f"http://localhost:{p}/health/ready") == 200 for p in (8001, 8003)),
        timeout_s=60,
    )
    set_stock(http, SKU_A, 20)
    order_id = place_order(http, customer, SKU_A, 1).json()["order_id"]
    wait_for_status(http, order_id, "CONFIRMED")
    assert {s: container_restarts(s) for s in services} == restarts_before
    assert_platform_whole(http)


def test_after_the_drills_the_platform_is_whole(http: httpx2.Client) -> None:
    assert_platform_whole(http)
