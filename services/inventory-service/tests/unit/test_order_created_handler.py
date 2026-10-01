import contextvars

import pytest
from fakes import FakeReservationStore, FakeStock
from test_reservation_service import NOW, ORDER

from app.consumer.handler import OrderCreatedHandler, OutcomePublishError
from app.domain.reservations import ReservationService
from retail_common.errors import PoisonMessage
from retail_common.events.consumer import HandlerOutcome
from retail_common.events.envelope import Envelope, new_event_id
from retail_common.events.publisher import PublishResult
from retail_common.events.schemas import OrderCreatedData
from retail_common.logging import set_correlation_id


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[Envelope] = []
        self.fail_next = 0

    def publish(self, envelopes: list[Envelope]) -> PublishResult:
        result = PublishResult()
        for envelope in envelopes:
            if self.fail_next:
                self.fail_next -= 1
                result.failed[envelope.event_id] = "ThrottlingException"
            else:
                self.published.append(envelope)
                result.succeeded.append(envelope.event_id)
        return result


def build(
    levels: dict[str, int],
) -> tuple[OrderCreatedHandler, RecordingPublisher, FakeStock, FakeReservationStore]:
    stock = FakeStock(levels)
    store = FakeReservationStore(stock)
    service = ReservationService(store, stock, new_event_id=new_event_id, now=lambda: NOW)  # type: ignore[arg-type]
    publisher = RecordingPublisher()
    return OrderCreatedHandler(service, publisher), publisher, stock, store


def deliver(
    handler: OrderCreatedHandler, envelope: Envelope, data: OrderCreatedData
) -> HandlerOutcome:
    """Call the handler the way ``SqsConsumer`` does: inside the message's correlation context."""

    def run() -> HandlerOutcome:
        set_correlation_id(envelope.correlation_id)
        return handler(envelope, data)

    return contextvars.copy_context().run(run)


def order_created(
    *items: tuple[str, int], order_id: str = ORDER
) -> tuple[Envelope, OrderCreatedData]:
    data = OrderCreatedData.model_validate(
        {
            "order_id": order_id,
            "customer_id": "cust-1",
            "items": [{"sku": sku, "quantity": qty} for sku, qty in items],
            "total_amount": "10.00",
            "currency": "USD",
        }
    )
    envelope = Envelope.create(
        event_type="OrderCreated", producer="order-service", data=data, correlation_id="corr-9"
    )
    return envelope, data


def test_a_successful_reservation_publishes_inventory_reserved_and_reports_processed() -> None:
    handler, publisher, stock, _ = build({"A": 10})
    envelope, data = order_created(("A", 2))

    outcome = deliver(handler, envelope, data)

    assert outcome is HandlerOutcome.PROCESSED
    (event,) = publisher.published
    assert event.event_type == "InventoryReserved"
    assert event.causation_id == envelope.event_id
    assert stock.levels["A"] == 8


def test_a_shortfall_publishes_inventory_failed_and_is_still_a_normal_outcome() -> None:
    handler, publisher, _, _ = build({"A": 1})
    envelope, data = order_created(("A", 2))

    assert (
        handler(envelope, data) is HandlerOutcome.PROCESSED
    )  # a rejection is a result, not an error

    (event,) = publisher.published
    assert event.event_type == "InventoryFailed"
    assert event.data["reason"] == "OUT_OF_STOCK"


def test_a_duplicate_delivery_re_emits_the_same_event_and_reports_duplicate() -> None:
    handler, publisher, stock, _ = build({"A": 10})
    envelope, data = order_created(("A", 2))
    deliver(handler, envelope, data)

    outcome = deliver(handler, envelope, data)

    assert outcome is HandlerOutcome.DUPLICATE
    first, second = publisher.published
    assert first.event_id == second.event_id
    assert first.model_dump_json() == second.model_dump_json()
    assert stock.levels["A"] == 8  # decremented exactly once


def test_if_publishing_fails_the_message_fails_and_the_retry_re_emits_without_reserving_again() -> (
    None
):
    """ADR-05 in one test: no outbox is needed because the stored reservation is replayed."""
    handler, publisher, stock, _ = build({"A": 10})
    envelope, data = order_created(("A", 2))
    publisher.fail_next = 1

    with pytest.raises(OutcomePublishError):
        deliver(
            handler, envelope, data
        )  # reserved, but the bus refused: the message is NOT deleted
    assert stock.levels["A"] == 8
    assert publisher.published == []

    outcome = deliver(handler, envelope, data)  # SQS redelivers

    assert outcome is HandlerOutcome.DUPLICATE
    assert stock.levels["A"] == 8  # still 8, not 6
    (event,) = publisher.published
    assert event.event_type == "InventoryReserved"


def test_an_order_that_lists_a_sku_twice_is_poison_not_retried() -> None:
    handler, publisher, _, _ = build({"A": 10})
    envelope, data = order_created(("A", 1), ("A", 2))

    with pytest.raises(PoisonMessage):
        handler(envelope, data)
    assert publisher.published == []


def test_the_correlation_id_of_the_incoming_event_reaches_the_outcome() -> None:
    import contextvars

    from retail_common.logging import set_correlation_id

    handler, publisher, _, _ = build({"A": 10})
    envelope, data = order_created(("A", 1))

    def run() -> None:
        set_correlation_id(envelope.correlation_id)  # what SqsConsumer does per message
        handler(envelope, data)

    contextvars.copy_context().run(run)

    assert publisher.published[0].correlation_id == "corr-9"
