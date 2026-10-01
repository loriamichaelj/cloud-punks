from datetime import UTC, datetime

import pytest
from fakes import ORDER_ID, FakeStore

from app.consumer.handler import NotificationHandler
from app.domain.notifications import RETENTION, NotificationService, compose
from retail_common.errors import PoisonMessage
from retail_common.events.consumer import HandlerOutcome
from retail_common.events.envelope import Envelope
from retail_common.events.schemas import (
    EventType,
    InventoryFailedData,
    InventoryReservedData,
    OrderStatusUpdatedData,
)

WHEN = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


def reserved() -> tuple[Envelope, InventoryReservedData]:
    data = InventoryReservedData.model_validate(
        {
            "order_id": ORDER_ID,
            "items": [
                {"sku": "A", "quantity": 2, "remaining": 8},
                {"sku": "B", "quantity": 1, "remaining": 0},
            ],
        }
    )
    return Envelope.create(
        event_type=EventType.INVENTORY_RESERVED,
        producer="inventory-service",
        data=data,
        occurred_at=WHEN,
    ), data


def failed(reason: str = "OUT_OF_STOCK") -> tuple[Envelope, InventoryFailedData]:
    data = InventoryFailedData.model_validate(
        {
            "order_id": ORDER_ID,
            "reason": reason,
            "failed_items": [{"sku": "A", "requested": 5, "available": 1}],
        }
    )
    return Envelope.create(
        event_type=EventType.INVENTORY_FAILED, producer="inventory-service", data=data
    ), data


def status(new: str, reason: str | None = None) -> tuple[Envelope, OrderStatusUpdatedData]:
    data = OrderStatusUpdatedData.model_validate(
        {
            "order_id": ORDER_ID,
            "customer_id": "cust-1",
            "old_status": "PENDING",
            "new_status": new,
            "reason": reason,
        }
    )
    return Envelope.create(
        event_type=EventType.ORDER_STATUS_UPDATED, producer="order-service", data=data
    ), data


def test_a_reservation_lists_what_was_reserved() -> None:
    notification = compose(*reserved())

    assert notification.order_id == ORDER_ID
    assert notification.type == "InventoryReserved"
    assert notification.channel == "email"
    assert "2 x A, 1 x B" in notification.message


@pytest.mark.parametrize(
    ("reason", "text"),
    [("OUT_OF_STOCK", "out of stock"), ("UNKNOWN_SKU", "no longer sold")],
)
def test_a_failure_says_why(reason: str, text: str) -> None:
    assert text in compose(*failed(reason)).message


def test_status_messages() -> None:
    assert "is confirmed" in compose(*status("CONFIRMED")).message
    rejected = compose(*status("REJECTED", "OUT_OF_STOCK")).message
    assert "was rejected (OUT_OF_STOCK)" in rejected


def test_the_record_carries_the_event_identity_and_time_not_the_clock() -> None:
    envelope, data = reserved()

    notification = compose(envelope, data)

    assert notification.event_id == envelope.event_id
    assert notification.created_at == WHEN
    assert notification.expires_at == WHEN + RETENTION


def test_an_unsupported_payload_is_refused() -> None:
    envelope, _ = reserved()
    with pytest.raises(ValueError, match="no notification"):
        compose(envelope, object())  # type: ignore[arg-type]


def test_the_same_event_twice_stores_one_notification() -> None:
    store = FakeStore()
    handler = NotificationHandler(NotificationService(store))
    envelope, data = reserved()

    first = handler(envelope, data)
    second = handler(envelope, data)

    assert (first, second) == (HandlerOutcome.PROCESSED, HandlerOutcome.DUPLICATE)
    assert len(store.rows) == 1


def test_one_order_collects_one_notification_per_event() -> None:
    store = FakeStore()
    handler = NotificationHandler(NotificationService(store))

    handler(*reserved())
    handler(*status("CONFIRMED"))

    types = {n.type for n in NotificationService(store).for_order(ORDER_ID)}
    assert types == {"InventoryReserved", "OrderStatusUpdated"}


def test_a_payload_the_handler_cannot_describe_is_poison() -> None:
    handler = NotificationHandler(NotificationService(FakeStore()))
    envelope, _ = reserved()
    with pytest.raises(PoisonMessage):
        handler(envelope, object())  # type: ignore[arg-type]
