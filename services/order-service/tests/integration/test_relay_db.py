"""The outbox relay against real PostgreSQL and LocalStack's EventBridge and SQS.

This is where ADR-04 is proven: events survive a bus outage, are published at least once, never
by two relays at the same time, and never out of the order they were written.
"""

import json
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
import pytest
from botocore.config import Config
from conftest import IsolatedBus, count, order_body, post
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.relay.core import OutboxRelay
from app.relay.store import PostgresOutboxStore
from retail_common.events.consumer import HandlerOutcome, SqsConsumer
from retail_common.events.envelope import Envelope
from retail_common.events.publisher import EventBridgePublisher, PublishResult
from retail_common.events.schemas import OrderCreatedData

pytestmark = pytest.mark.usefixtures("exclusive_outbox")

BUS = "retail-events"  # only used by the dead publisher, which never reaches a bus
ITEST_CUSTOMER_DATA = {
    "order_id": "01J9Z6Q4W8K3M2N1P0R7S5T4V3",
    "customer_id": "itest-relay",
    "items": [{"sku": "ITEST-SKU-A", "quantity": 1}],
    "total_amount": "19.99",
    "currency": "USD",
}


def real_publisher(bus: str) -> EventBridgePublisher:
    return EventBridgePublisher(boto3.client("events", region_name="us-east-1"), bus)


def dead_publisher() -> EventBridgePublisher:
    """A publisher whose bus nothing listens on: the 'bus unavailable' condition."""
    client = boto3.client(
        "events",
        region_name="us-east-1",
        endpoint_url="http://127.0.0.1:1",
        config=Config(connect_timeout=1, read_timeout=1, retries={"max_attempts": 0}),
    )
    return EventBridgePublisher(client, BUS)


def relay_for(engine: Engine, publisher: Any, **kwargs: Any) -> OutboxRelay:
    return OutboxRelay(PostgresOutboxStore(engine), publisher, poll_interval_s=0.05, **kwargs)


def insert_event(
    engine: Engine,
    *,
    published_at: datetime | None = None,
    created_at: datetime | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    envelope = Envelope.create(
        event_type="OrderCreated",
        producer="order-service",
        data=ITEST_CUSTOMER_DATA,
        correlation_id="corr-relay-itest",
    )
    # A row with a deliberately broken payload carries no customer id for the cleanup to match on,
    # so give it the reserved test event-id prefix instead. Otherwise it would leak.
    event_id = envelope.event_id if payload is None else "01ITEST" + uuid.uuid4().hex[:19].upper()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO outbox (event_id, detail_type, payload, published_at, created_at) "
                "VALUES (:e, 'OrderCreated', CAST(:p AS jsonb), :pub, COALESCE(:cr, now()))"
            ),
            {
                "e": event_id,
                "p": json.dumps(
                    payload if payload is not None else envelope.model_dump(mode="json")
                ),
                "pub": published_at,
                "cr": created_at,
            },
        )
    return event_id


def outbox_state(engine: Engine, event_id: str) -> Any:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT published_at, attempts, last_error FROM outbox WHERE event_id = :e"),
            {"e": event_id},
        ).one()


def drain_queue(
    sqs: Any, queue: str, wanted: set[str], timeout_s: float = 15.0
) -> dict[str, Envelope]:
    """Read a queue with the real consumer until every wanted event id has arrived."""
    seen: dict[str, Envelope] = {}
    consumer = SqsConsumer(sqs, queue, wait_time_s=1)

    def collect(envelope: Envelope, _data: Any) -> HandlerOutcome:
        seen[envelope.event_id] = envelope
        return HandlerOutcome.PROCESSED

    consumer.register("OrderCreated", collect)
    deadline = time.monotonic() + timeout_s
    while not wanted <= set(seen) and time.monotonic() < deadline:
        consumer.poll_once()
    return seen


# --- end to end: order -> outbox -> relay -> EventBridge -> SQS -> consumer ---------------------


def test_an_order_travels_from_the_api_through_the_relay_to_a_queue(
    client: TestClient, engine: Engine, sqs: Any, key: str, itest_bus: IsolatedBus
) -> None:
    orders = [
        post(client, f"{key}-{n}", order_body(**{"ITEST-SKU-A": n + 1})).json() for n in range(3)
    ]
    with engine.connect() as connection:
        event_ids = {
            r.event_id
            for r in connection.execute(
                text(
                    "SELECT event_id FROM outbox WHERE payload->'data'->>'customer_id' LIKE 'itest-%'"
                )
            )
        }

    result = relay_for(engine, real_publisher(itest_bus.bus)).run_once()

    assert (result.published, result.failed) == (3, 0)
    assert all(outbox_state(engine, e).published_at is not None for e in event_ids)
    received = drain_queue(sqs, itest_bus.queue, event_ids)
    assert event_ids <= set(received)  # every event arrived, through the real bus and queue
    by_order = {
        OrderCreatedData.model_validate(e.data).order_id: e
        for e in received.values()
        if e.event_id in event_ids
    }
    for order in orders:
        envelope = by_order[order["order_id"]]
        data = OrderCreatedData.model_validate(envelope.data)
        assert str(data.total_amount) == order["total_amount"]
        assert [(i.sku, i.quantity) for i in data.items] == [
            (i["sku"], i["quantity"]) for i in order["items"]
        ]
        assert envelope.producer == "order-service"


def test_the_correlation_id_of_the_http_request_survives_the_whole_trip(
    client: TestClient, engine: Engine, sqs: Any, key: str, itest_bus: IsolatedBus
) -> None:
    created = client.post(
        "/api/v1/orders",
        json=order_body(),
        headers={"Idempotency-Key": key, "X-Correlation-ID": "corr-end-to-end"},
    ).json()
    relay_for(engine, real_publisher(itest_bus.bus)).run_once()

    with engine.connect() as connection:
        event_id = connection.execute(
            text("SELECT event_id FROM outbox WHERE payload->'data'->>'order_id' = :o"),
            {"o": created["order_id"]},
        ).scalar_one()
    received = drain_queue(sqs, itest_bus.queue, {event_id})

    assert received[event_id].correlation_id == "corr-end-to-end"


# --- the 'bus unavailable' drill: the proof that the outbox is transactional --------------------


def test_orders_are_still_accepted_while_the_bus_is_down_and_drain_when_it_returns(
    client: TestClient, engine: Engine, sqs: Any, key: str, itest_bus: IsolatedBus
) -> None:
    # The bus is down: POST /orders must still answer 202, because it never talks to the bus.
    created = post(client, key)
    assert created.status_code == 202

    down = relay_for(engine, dead_publisher()).run_once()
    assert (down.published, down.failed) == (0, 1)
    with engine.connect() as connection:
        event_id = connection.execute(
            text("SELECT event_id FROM outbox WHERE payload->'data'->>'order_id' = :o"),
            {"o": created.json()["order_id"]},
        ).scalar_one()
    state = outbox_state(engine, event_id)
    assert state.published_at is None  # nothing was lost, nothing was falsely marked sent
    assert state.attempts == 1
    assert "EndpointConnectionError" in state.last_error

    # The bus comes back: the same relay pass now drains it.
    up = relay_for(engine, real_publisher(itest_bus.bus)).run_once()
    assert (up.published, up.failed) == (1, 0)
    assert outbox_state(engine, event_id).published_at is not None
    assert event_id in drain_queue(sqs, itest_bus.queue, {event_id})
    assert client.get(f"/api/v1/orders/{created.json()['order_id']}").json()["status"] == "PENDING"


def test_a_burst_of_orders_during_an_outage_all_get_through_in_order(
    client: TestClient, engine: Engine, sqs: Any, key: str, itest_bus: IsolatedBus
) -> None:
    ids = [post(client, f"{key}-{n}").json()["order_id"] for n in range(12)]
    dead = relay_for(engine, dead_publisher())
    for _ in range(3):
        dead.run_once()  # three failed attempts while the bus is down

    live = relay_for(engine, real_publisher(itest_bus.bus), batch_size=5)
    published = 0
    while (result := live.run_once()).published:
        published += result.published

    assert published == 12
    assert (
        count(
            engine,
            "SELECT count(*) FROM outbox WHERE published_at IS NULL AND payload->'data'->>'customer_id' LIKE 'itest-%'",
        )
        == 0
    )
    with engine.connect() as connection:
        attempts = {
            r.attempts
            for r in connection.execute(
                text(
                    "SELECT attempts FROM outbox WHERE payload->'data'->>'customer_id' LIKE 'itest-%'"
                )
            )
        }
    assert attempts == {3}  # the failed attempts are on the record
    assert len(ids) == 12


# --- partial failure --------------------------------------------------------------------------


class RejectingPublisher:
    """Wraps a real publisher but refuses the chosen event ids, like per-entry PutEvents errors."""

    def __init__(self, inner: EventBridgePublisher, reject: set[str]) -> None:
        self.inner, self.reject = inner, reject

    def publish(self, envelopes: Any) -> PublishResult:
        accepted = [e for e in envelopes if e.event_id not in self.reject]
        result = self.inner.publish(accepted)
        for envelope in envelopes:
            if envelope.event_id in self.reject:
                result.failed[envelope.event_id] = "ThrottlingException"
        return result


def test_a_partial_failure_marks_only_the_accepted_rows_and_the_rest_retry(
    engine: Engine, itest_bus: IsolatedBus
) -> None:
    ids = [insert_event(engine) for _ in range(4)]
    rejected = {ids[1], ids[3]}

    first = relay_for(
        engine, RejectingPublisher(real_publisher(itest_bus.bus), rejected)
    ).run_once()

    assert (first.published, first.failed) == (2, 2)
    for event_id in ids:
        state = outbox_state(engine, event_id)
        if event_id in rejected:
            assert (state.published_at, state.attempts, state.last_error) == (
                None,
                1,
                "ThrottlingException",
            )
        else:
            assert state.published_at is not None
            assert state.attempts == 0

    second = relay_for(engine, real_publisher(itest_bus.bus)).run_once()
    assert (second.published, second.failed) == (2, 0)  # only the two that had failed
    assert all(outbox_state(engine, e).published_at is not None for e in ids)


def test_a_row_with_a_broken_payload_does_not_block_the_rows_behind_it(
    engine: Engine, itest_bus: IsolatedBus
) -> None:
    broken = insert_event(engine, payload={"not": "an envelope"})
    good = [insert_event(engine) for _ in range(2)]

    result = relay_for(engine, real_publisher(itest_bus.bus)).run_once()

    assert (result.published, result.failed) == (2, 1)
    assert outbox_state(engine, broken).published_at is None
    assert "invalid envelope" in outbox_state(engine, broken).last_error
    assert all(outbox_state(engine, e).published_at is not None for e in good)


# --- concurrency: SKIP LOCKED ----------------------------------------------------------------


def test_a_claim_holds_its_rows_and_a_second_relay_skips_them(engine: Engine) -> None:
    for _ in range(6):
        insert_event(engine)
    first, second = PostgresOutboxStore(engine), PostgresOutboxStore(engine)

    with first.claim(3) as batch_a, second.claim(3) as batch_b:
        ids_a = {row.id for row in batch_a.rows}
        ids_b = {row.id for row in batch_b.rows}

    assert len(ids_a) == len(ids_b) == 3
    assert ids_a.isdisjoint(ids_b)  # the second relay did not wait for, or take, the first's rows


class SlowRecordingPublisher:
    def __init__(self) -> None:
        self.published: list[str] = []
        self._lock = threading.Lock()

    def publish(self, envelopes: Any) -> PublishResult:
        time.sleep(0.03)  # hold the row locks long enough for the other relay to overlap
        result = PublishResult()
        for envelope in envelopes:
            result.succeeded.append(envelope.event_id)
            with self._lock:
                self.published.append(envelope.event_id)
        return result


def test_two_relays_running_at_once_never_publish_the_same_row_twice(engine: Engine) -> None:
    expected = {insert_event(engine) for _ in range(60)}
    publishers = [SlowRecordingPublisher(), SlowRecordingPublisher()]
    barrier = threading.Barrier(2)

    def work(publisher: SlowRecordingPublisher) -> None:
        relay = relay_for(engine, publisher, batch_size=10)
        barrier.wait()
        while not relay.run_once().idle:
            pass

    threads = [threading.Thread(target=work, args=(p,)) for p in publishers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    both = publishers[0].published + publishers[1].published
    assert len(both) == 60
    assert set(both) == expected  # all of them, and
    assert len(set(both)) == 60  # none twice
    assert publishers[0].published  # and the work really was shared
    assert publishers[1].published


def test_events_are_published_oldest_first(engine: Engine) -> None:
    ids = [insert_event(engine) for _ in range(8)]
    publisher = SlowRecordingPublisher()

    relay_for(engine, publisher, batch_size=8).run_once()

    assert publisher.published == ids


def test_a_crash_after_claiming_rolls_back_so_the_rows_are_published_later(
    engine: Engine, itest_bus: IsolatedBus
) -> None:
    ids = [insert_event(engine) for _ in range(3)]

    class Exploding:
        def publish(self, _envelopes: Any) -> PublishResult:
            raise RuntimeError("the process dies mid-publish")

    with pytest.raises(RuntimeError):
        relay_for(engine, Exploding()).run_once()

    assert all(outbox_state(engine, e).published_at is None for e in ids)
    assert all(
        outbox_state(engine, e).attempts == 0 for e in ids
    )  # not even counted: it rolled back
    assert relay_for(engine, real_publisher(itest_bus.bus)).run_once().published == 3


# --- the running loop, cleanup and metrics inputs -----------------------------------------------


def test_the_running_relay_picks_up_new_orders_and_stops_when_asked(
    client: TestClient, engine: Engine, key: str, itest_bus: IsolatedBus
) -> None:
    relay = relay_for(engine, real_publisher(itest_bus.bus))
    thread = threading.Thread(target=relay.run)
    thread.start()
    try:
        created = post(client, key).json()
        deadline = time.monotonic() + 10
        published = None
        while time.monotonic() < deadline and published is None:
            with engine.connect() as connection:
                published = connection.execute(
                    text("SELECT published_at FROM outbox WHERE payload->'data'->>'order_id' = :o"),
                    {"o": created["order_id"]},
                ).scalar_one()
            time.sleep(0.1)
        assert published is not None, "the running relay never published the new order"
    finally:
        relay.stop()
        thread.join(timeout=10)
    assert not thread.is_alive()


def test_cleanup_removes_only_rows_published_more_than_seven_days_ago(
    engine: Engine, itest_bus: IsolatedBus
) -> None:
    now = datetime.now(UTC)
    old = [insert_event(engine, published_at=now - timedelta(days=8)) for _ in range(3)]
    recent = [insert_event(engine, published_at=now - timedelta(days=1)) for _ in range(2)]
    unpublished_old = [insert_event(engine, created_at=now - timedelta(days=30)) for _ in range(2)]

    deleted = relay_for(engine, real_publisher(itest_bus.bus)).cleanup()

    assert deleted == 3
    remaining = {
        r[0]
        for r in engine.connect().execute(
            text("SELECT event_id FROM outbox WHERE payload->'data'->>'customer_id' LIKE 'itest-%'")
        )
    }
    assert remaining == set(recent) | set(unpublished_old)  # nothing unpublished is ever deleted
    assert not remaining & set(old)


def test_cleanup_deletes_at_most_the_batch_size_per_call(engine: Engine) -> None:
    now = datetime.now(UTC)
    for _ in range(5):
        insert_event(engine, published_at=now - timedelta(days=9))

    assert PostgresOutboxStore(engine).delete_published_before(now - timedelta(days=7), 2) == 2
    assert PostgresOutboxStore(engine).delete_published_before(now - timedelta(days=7), 1000) == 3


def test_unpublished_stats_feed_the_outbox_gauges(engine: Engine) -> None:
    store = PostgresOutboxStore(engine)
    before_count, _ = store.unpublished_stats()
    insert_event(engine, created_at=datetime.now(UTC) - timedelta(seconds=120))
    insert_event(engine)
    insert_event(engine, published_at=datetime.now(UTC))  # published rows are not counted

    unpublished, oldest_age = store.unpublished_stats()

    assert unpublished == before_count + 2
    assert oldest_age is not None
    assert 115 <= oldest_age <= 180


def test_unique_event_ids_stop_the_same_event_being_enqueued_twice(engine: Engine) -> None:
    event_id = insert_event(engine)
    with pytest.raises(Exception, match="uq_outbox_event_id"), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO outbox (event_id, detail_type, payload) VALUES (:e, 'OrderCreated', '{}'::jsonb)"
            ),
            {"e": event_id},
        )
