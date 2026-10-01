"""Customer notifications (simulated), DESIGN.md sections 4 to 6.

Each inventory or order event becomes one notification record. The record is keyed by
``(order_id, event_id)``, so storing the same event twice is a no-op: that is the consumer's
idempotency (ADR-07). Nothing is actually sent; the record is the notification.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from pydantic import BaseModel

from retail_common.events.envelope import Envelope
from retail_common.events.schemas import (
    EventType,
    InventoryFailedData,
    InventoryReservedData,
    OrderStatusUpdatedData,
)

CHANNEL = "email"  # simulated
RETENTION = timedelta(days=30)

_FAILURE_TEXT = {
    "OUT_OF_STOCK": "some items are out of stock",
    "UNKNOWN_SKU": "an item is no longer sold",
}


@dataclass(frozen=True)
class Notification:
    order_id: str
    event_id: str
    type: str  # the event type that caused it
    channel: str
    message: str
    created_at: datetime  # when the event happened, so a redelivery builds an identical record

    @property
    def expires_at(self) -> datetime:
        return self.created_at + RETENTION


class NotificationStore(Protocol):
    def add(self, notification: Notification) -> bool:
        """Store it unless this ``event_id`` already has a record for the order.

        Returns True when stored, False when it was a duplicate. Raises ``StoreUnavailable``."""
        ...

    def for_order(self, order_id: str) -> Sequence[Notification]:
        """Oldest first (event ids are ULIDs, so they sort by time)."""
        ...


def compose(envelope: Envelope, data: BaseModel) -> Notification:
    """The notification for a validated event. Raises ``ValueError`` for an unsupported event."""
    if isinstance(data, InventoryReservedData):
        lines = ", ".join(f"{item.quantity} x {item.sku}" for item in data.items)
        order_id, message = data.order_id, f"Stock is reserved for order {data.order_id}: {lines}."
    elif isinstance(data, InventoryFailedData):
        why = _FAILURE_TEXT.get(data.reason, data.reason)
        order_id = data.order_id
        message = f"We could not reserve stock for order {data.order_id}: {why}."
    elif isinstance(data, OrderStatusUpdatedData):
        order_id = data.order_id
        if data.new_status == "CONFIRMED":
            message = f"Your order {data.order_id} is confirmed."
        elif data.new_status == "REJECTED":
            message = (
                f"Your order {data.order_id} was rejected ({data.reason or 'no reason given'})."
            )
        else:
            message = f"Your order {data.order_id} is now {data.new_status}."
    else:
        raise ValueError(f"no notification for {type(data).__name__}")
    return Notification(
        order_id=order_id,
        event_id=envelope.event_id,
        type=envelope.event_type,
        channel=CHANNEL,
        message=message,
        created_at=envelope.occurred_at,
    )


NOTIFIED_EVENTS = (
    EventType.INVENTORY_RESERVED,
    EventType.INVENTORY_FAILED,
    EventType.ORDER_STATUS_UPDATED,
)


class NotificationService:
    def __init__(self, store: NotificationStore) -> None:
        self._store = store

    def record(self, envelope: Envelope, data: BaseModel) -> bool:
        """True if a new notification was stored, False for a duplicate delivery."""
        return self._store.add(compose(envelope, data))

    def for_order(self, order_id: str) -> Sequence[Notification]:
        return self._store.for_order(order_id)
