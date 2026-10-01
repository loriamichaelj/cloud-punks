from datetime import UTC, datetime, timedelta

import pytest
from fakes_transitions import CREATED_AT, FakeTransitionStore
from prometheus_client import CollectorRegistry

from app.consumer.handler import InventoryOutcomeHandler
from app.domain.transitions import (
    InventoryOutcome,
    StatusChange,
    TransitionService,
    decide,
)
from app.events import order_status_updated_event
from app.metrics import OrderMetrics
from retail_common.errors import PoisonMessage
from retail_common.events.consumer import HandlerOutcome
from retail_common.events.envelope import Envelope, new_event_id
from retail_common.events.schemas import (
    EventType,
    InventoryFailedData,
    InventoryReservedData,
    OrderStatusUpdatedData,
)

ORDER_ID = "01J9Z6R0C4AAAAAAAAAAAAAAAA"
LATER = CREATED_AT + timedelta(seconds=2.5)


def reserved_envelope() -> tuple[Envelope, InventoryReservedData]:
    data = InventoryReservedData.model_validate(
        {"order_id": ORDER_ID, "items": [{"sku": "TSHIRT-RED-M", "quantity": 2, "remaining": 8}]}
    )
    return Envelope.create(
        event_type=EventType.INVENTORY_RESERVED, producer="inventory-service", data=data
    ), data


def failed_envelope(reason: str = "OUT_OF_STOCK") -> tuple[Envelope, InventoryFailedData]:
    data = InventoryFailedData.model_validate(
        {
            "order_id": ORDER_ID,
            "reason": reason,
            "failed_items": [{"sku": "TSHIRT-RED-M", "requested": 5, "available": 1}],
        }
    )
    return Envelope.create(
        event_type=EventType.INVENTORY_FAILED, producer="inventory-service", data=data
    ), data


def make_handler(
    store: FakeTransitionStore, now: datetime = LATER
) -> tuple[InventoryOutcomeHandler, OrderMetrics]:
    metrics = OrderMetrics(CollectorRegistry())
    service = TransitionService(store, order_status_updated_event)
    return InventoryOutcomeHandler(service, metrics, now=lambda: now), metrics


# -- the pure decision -------------------------------------------------------------------------


def test_reserved_confirms_the_order() -> None:
    assert decide(InventoryOutcome(reserved=True)) == StatusChange("CONFIRMED", None)


@pytest.mark.parametrize("reason", ["OUT_OF_STOCK", "UNKNOWN_SKU"])
def test_failed_rejects_the_order_and_keeps_the_reason(reason: str) -> None:
    assert decide(InventoryOutcome(reserved=False, reason=reason)) == StatusChange(
        "REJECTED", reason
    )


# -- the handler -------------------------------------------------------------------------------


def test_a_reservation_confirms_a_pending_order_and_emits_one_status_event() -> None:
    store = FakeTransitionStore({ORDER_ID: "PENDING"})
    handler, metrics = make_handler(store)
    envelope, data = reserved_envelope()

    assert handler.on_reserved(envelope, data) is HandlerOutcome.PROCESSED

    assert store.orders[ORDER_ID] == "CONFIRMED"
    assert len(store.outbox) == 1
    event = store.outbox[0]
    assert event.detail_type == EventType.ORDER_STATUS_UPDATED
    assert event.payload["causation_id"] == envelope.event_id
    body = OrderStatusUpdatedData.model_validate(event.payload["data"])
    assert (body.old_status, body.new_status, body.reason) == ("PENDING", "CONFIRMED", None)
    assert metrics.orders_total.labels("CONFIRMED")._value.get() == 1.0  # type: ignore[attr-defined]


def test_a_failure_rejects_the_order_with_the_inventory_reason() -> None:
    store = FakeTransitionStore({ORDER_ID: "PENDING"})
    handler, _ = make_handler(store)
    envelope, data = failed_envelope("UNKNOWN_SKU")

    assert handler.on_failed(envelope, data) is HandlerOutcome.PROCESSED

    assert store.orders[ORDER_ID] == "REJECTED"
    assert store.reasons[ORDER_ID] == "UNKNOWN_SKU"
    body = OrderStatusUpdatedData.model_validate(store.outbox[0].payload["data"])
    assert (body.new_status, body.reason) == ("REJECTED", "UNKNOWN_SKU")


def test_the_same_event_delivered_twice_changes_the_order_once() -> None:
    store = FakeTransitionStore({ORDER_ID: "PENDING"})
    handler, metrics = make_handler(store)
    envelope, data = reserved_envelope()

    first = handler.on_reserved(envelope, data)
    second = handler.on_reserved(envelope, data)

    assert (first, second) == (HandlerOutcome.PROCESSED, HandlerOutcome.DUPLICATE)
    assert len(store.outbox) == 1
    assert metrics.orders_total.labels("CONFIRMED")._value.get() == 1.0  # type: ignore[attr-defined]


def test_an_outcome_for_a_terminal_order_is_ignored() -> None:
    """A late or contradictory outcome (a different event_id) must not flip a final status."""
    store = FakeTransitionStore({ORDER_ID: "CONFIRMED"})
    handler, metrics = make_handler(store)
    envelope, data = failed_envelope()

    assert handler.on_failed(envelope, data) is HandlerOutcome.DUPLICATE

    assert store.orders[ORDER_ID] == "CONFIRMED"
    assert store.outbox == []
    assert envelope.event_id in store.processed  # still recorded, so redelivery is a no-op
    assert metrics.orders_total.labels("REJECTED")._value.get() == 0.0  # type: ignore[attr-defined]


def test_an_unknown_order_is_a_poison_message_and_records_nothing() -> None:
    store = FakeTransitionStore({})
    handler, _ = make_handler(store)
    envelope, data = reserved_envelope()

    with pytest.raises(PoisonMessage, match=ORDER_ID):
        handler.on_reserved(envelope, data)

    assert store.processed == set()  # rolled back: the event is not marked done


def test_time_to_terminal_is_measured_from_order_creation() -> None:
    store = FakeTransitionStore({ORDER_ID: "PENDING"})
    handler, metrics = make_handler(store, now=CREATED_AT + timedelta(seconds=2.5))
    envelope, data = reserved_envelope()

    handler.on_reserved(envelope, data)

    histogram = metrics.time_to_terminal
    assert histogram._sum.get() == pytest.approx(2.5)  # type: ignore[attr-defined]


def test_a_clock_behind_the_database_never_records_a_negative_duration() -> None:
    store = FakeTransitionStore({ORDER_ID: "PENDING"})
    handler, metrics = make_handler(store, now=datetime(2020, 1, 1, tzinfo=UTC))
    envelope, data = reserved_envelope()

    handler.on_reserved(envelope, data)

    assert metrics.time_to_terminal._sum.get() == 0.0  # type: ignore[attr-defined]


# -- the event ---------------------------------------------------------------------------------


def test_the_status_event_inherits_the_correlation_id_of_the_message_being_handled() -> None:
    import contextvars

    from retail_common.logging import set_correlation_id

    store = FakeTransitionStore({ORDER_ID: "PENDING"})
    handler, _ = make_handler(store)
    envelope, data = reserved_envelope()

    def deliver() -> None:
        set_correlation_id("from-the-original-request")
        handler.on_reserved(envelope, data)

    contextvars.copy_context().run(deliver)

    assert store.outbox[0].payload["correlation_id"] == "from-the-original-request"
    assert store.outbox[0].event_id == store.outbox[0].payload["event_id"]
    assert store.outbox[0].event_id != new_event_id()
