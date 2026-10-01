"""The order state machine against real PostgreSQL (DESIGN.md section 7, ADR-07).

The guarantees under test are the ones a mock cannot give: the processed-event row, the guarded
UPDATE and the outbox row commit together or not at all, and concurrent deliveries of competing
outcomes produce exactly one transition.
"""

import json
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import CUSTOMER, count, order_body, post
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry
from sqlalchemy import Engine, text

from app.consumer.handler import InventoryOutcomeHandler
from app.domain.errors import OrderNotFound
from app.domain.transitions import (
    InventoryOutcome,
    StatusChange,
    TransitionKind,
    TransitionService,
    decide,
)
from app.events import order_status_updated_event
from app.metrics import OrderMetrics
from app.repo.transitions import PostgresTransitionStore
from retail_common.errors import PoisonMessage
from retail_common.events.consumer import HandlerOutcome
from retail_common.events.envelope import Envelope
from retail_common.events.schemas import (
    EventType,
    InventoryFailedData,
    InventoryReservedData,
    OrderStatusUpdatedData,
)


def event_id() -> str:
    """A valid ULID (Crockford has no 'I') that the suite's cleanup recognises by its prefix."""
    return "01TEST" + uuid.uuid4().hex[:20].upper()


def new_order(client: TestClient, key: str) -> str:
    response = post(client, key, order_body())
    assert response.status_code == 202, response.text
    return str(response.json()["order_id"])


def order_row(engine: Engine, order_id: str) -> Any:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT status, status_reason, version FROM orders WHERE order_id = :o"),
            {"o": order_id},
        ).one()


def status_events(engine: Engine, order_id: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT payload FROM outbox WHERE detail_type = 'OrderStatusUpdated' "
                "AND payload->'data'->>'order_id' = :o ORDER BY id"
            ),
            {"o": order_id},
        ).scalars()
        return [r if isinstance(r, dict) else json.loads(r) for r in rows]


def processed(engine: Engine, eid: str) -> int:
    return count(engine, "SELECT count(*) FROM processed_events WHERE event_id = :e", e=eid)


@pytest.fixture
def service(engine: Engine) -> TransitionService:
    return TransitionService(PostgresTransitionStore(engine), order_status_updated_event)


def reserved(service: TransitionService, eid: str, order_id: str) -> Any:
    return service.handle(eid, order_id, InventoryOutcome(reserved=True))


def failed(
    service: TransitionService, eid: str, order_id: str, reason: str = "OUT_OF_STOCK"
) -> Any:
    return service.handle(eid, order_id, InventoryOutcome(reserved=False, reason=reason))


def test_a_reservation_confirms_the_order_and_queues_exactly_one_status_event(
    engine: Engine, client: TestClient, key: str, service: TransitionService
) -> None:
    order_id = new_order(client, key)
    eid = event_id()

    result = reserved(service, eid, order_id)

    assert result.kind is TransitionKind.APPLIED
    row = order_row(engine, order_id)
    assert (row.status, row.status_reason, row.version) == ("CONFIRMED", None, 2)
    events = status_events(engine, order_id)
    assert len(events) == 1
    body = OrderStatusUpdatedData.model_validate(events[0]["data"])
    assert (body.old_status, body.new_status, body.customer_id) == (
        "PENDING",
        "CONFIRMED",
        CUSTOMER,
    )
    assert events[0]["causation_id"] == eid
    assert processed(engine, eid) == 1


def test_a_failure_rejects_the_order_with_the_reason(
    engine: Engine, client: TestClient, key: str, service: TransitionService
) -> None:
    order_id = new_order(client, key)

    failed(service, event_id(), order_id, "UNKNOWN_SKU")

    row = order_row(engine, order_id)
    assert (row.status, row.status_reason) == ("REJECTED", "UNKNOWN_SKU")
    assert status_events(engine, order_id)[0]["data"]["reason"] == "UNKNOWN_SKU"


def test_the_rejection_is_visible_through_the_api(
    client: TestClient, key: str, service: TransitionService
) -> None:
    order_id = new_order(client, key)
    failed(service, event_id(), order_id)

    body = client.get(f"/api/v1/orders/{order_id}").json()

    assert (body["status"], body["status_reason"]) == ("REJECTED", "OUT_OF_STOCK")


def test_redelivering_an_event_changes_nothing(
    engine: Engine, client: TestClient, key: str, service: TransitionService
) -> None:
    order_id = new_order(client, key)
    eid = event_id()

    first = reserved(service, eid, order_id)
    again = reserved(service, eid, order_id)

    assert (first.kind, again.kind) == (TransitionKind.APPLIED, TransitionKind.DUPLICATE)
    assert order_row(engine, order_id).version == 2
    assert len(status_events(engine, order_id)) == 1


def test_a_contradicting_outcome_cannot_change_a_final_status(
    engine: Engine, client: TestClient, key: str, service: TransitionService
) -> None:
    order_id = new_order(client, key)
    reserved(service, event_id(), order_id)
    late = event_id()

    result = failed(service, late, order_id)

    assert result.kind is TransitionKind.STALE
    assert order_row(engine, order_id).status == "CONFIRMED"
    assert len(status_events(engine, order_id)) == 1  # no second event
    assert processed(engine, late) == 1  # but the delivery is recorded, so it is not retried


def test_an_unknown_order_rolls_back_including_the_processed_event_row(
    engine: Engine, service: TransitionService
) -> None:
    eid = event_id()

    with pytest.raises(OrderNotFound):
        reserved(service, eid, "01J9Z6R0C4ZZZZZZZZZZZZZZZZ")

    assert processed(engine, eid) == 0


def test_a_failure_while_writing_the_outbox_rolls_back_the_status_change(
    engine: Engine, client: TestClient, key: str
) -> None:
    """Atomicity: the order must not become CONFIRMED without its event (ADR-04)."""
    order_id = new_order(client, key)
    eid = event_id()

    def exploding_event(_context: Any, _cause: str) -> Any:
        raise RuntimeError("could not build the event")

    store_service = TransitionService(PostgresTransitionStore(engine), exploding_event)
    with pytest.raises(RuntimeError, match="could not build"):
        reserved(store_service, eid, order_id)

    assert order_row(engine, order_id).status == "PENDING"
    assert processed(engine, eid) == 0
    assert status_events(engine, order_id) == []


def test_the_same_event_delivered_concurrently_transitions_once(
    engine: Engine, client: TestClient, key: str, service: TransitionService
) -> None:
    order_id = new_order(client, key)
    eid = event_id()

    results = run_concurrently(8, lambda: reserved(service, eid, order_id))

    kinds = sorted(r.kind for r in results)
    assert kinds == [TransitionKind.APPLIED] + [TransitionKind.DUPLICATE] * 7
    assert order_row(engine, order_id).version == 2
    assert len(status_events(engine, order_id)) == 1


def test_competing_outcomes_delivered_concurrently_yield_one_final_status(
    engine: Engine, client: TestClient, key: str, service: TransitionService
) -> None:
    """Reserved and Failed arriving together: exactly one wins, the other is stale."""
    order_id = new_order(client, key)
    barrier_calls = [
        lambda: reserved(service, event_id(), order_id),
        lambda: failed(service, event_id(), order_id),
    ] * 4
    results = run_concurrently_each(barrier_calls)

    assert sorted(r.kind for r in results).count(TransitionKind.APPLIED) == 1
    assert sorted(r.kind for r in results).count(TransitionKind.STALE) == 7
    final = order_row(engine, order_id)
    assert final.status in {"CONFIRMED", "REJECTED"}
    assert final.version == 2
    events = status_events(engine, order_id)
    assert len(events) == 1
    assert events[0]["data"]["new_status"] == final.status


def test_the_handler_end_to_end_on_real_envelopes(
    engine: Engine, client: TestClient, key: str, service: TransitionService
) -> None:
    order_id = new_order(client, key)
    data = InventoryFailedData.model_validate(
        {
            "order_id": order_id,
            "reason": "OUT_OF_STOCK",
            "failed_items": [{"sku": "ITEST-SKU-A", "requested": 2, "available": 0}],
        }
    )
    envelope = Envelope.create(
        event_type=EventType.INVENTORY_FAILED,
        producer="inventory-service",
        data=data,
        event_id=event_id(),
    )
    metrics = OrderMetrics(CollectorRegistry())
    handler = InventoryOutcomeHandler(service, metrics, now=lambda: datetime.now(UTC))

    assert handler.on_failed(envelope, data) is HandlerOutcome.PROCESSED
    assert handler.on_failed(envelope, data) is HandlerOutcome.DUPLICATE
    assert order_row(engine, order_id).status == "REJECTED"
    assert metrics.orders_total.labels("REJECTED")._value.get() == 1.0  # type: ignore[attr-defined]
    assert metrics.time_to_terminal._sum.get() >= 0.0  # type: ignore[attr-defined]


def test_the_handler_turns_an_unknown_order_into_a_poison_message(
    service: TransitionService,
) -> None:
    data = InventoryReservedData.model_validate(
        {
            "order_id": "01J9Z6R0C4ZZZZZZZZZZZZZZZZ",
            "items": [{"sku": "ITEST-SKU-A", "quantity": 1, "remaining": 1}],
        }
    )
    envelope = Envelope.create(
        event_type=EventType.INVENTORY_RESERVED,
        producer="inventory-service",
        data=data,
        event_id=event_id(),
    )
    handler = InventoryOutcomeHandler(service, OrderMetrics(CollectorRegistry()))

    with pytest.raises(PoisonMessage):
        handler.on_reserved(envelope, data)


def test_decide_matches_what_the_database_stores() -> None:
    assert decide(InventoryOutcome(reserved=False, reason="UNKNOWN_SKU")) == StatusChange(
        "REJECTED", "UNKNOWN_SKU"
    )


# -- helpers -----------------------------------------------------------------------------------


def run_concurrently(n: int, call: Any) -> list[Any]:
    return run_concurrently_each([call] * n)


def run_concurrently_each(calls: list[Any]) -> list[Any]:
    """Run the calls on threads released together by a barrier, to maximise contention."""
    barrier = threading.Barrier(len(calls))
    results: list[Any] = [None] * len(calls)
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            barrier.wait(timeout=10)
            results[index] = calls[index]()
        except BaseException as exc:  # noqa: BLE001 - re-raised on the main thread below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(calls))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    if errors:
        raise errors[0]
    return results
