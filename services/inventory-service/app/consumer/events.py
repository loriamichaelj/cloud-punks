"""Build the outcome event for a stored reservation (DESIGN.md section 6).

The event is derived *only* from the stored record: the same ``event_id``, the same timestamp,
the same payload. So publishing it again after a failed first attempt, or after a redelivery, is a
true re-emission that consumers deduplicate on ``event_id`` (ADR-07).
"""

from app.domain.reservations import Reservation
from retail_common.events.envelope import Envelope
from retail_common.events.schemas import (
    EventType,
    FailedItem,
    InventoryFailedData,
    InventoryReservedData,
    ReservedItem,
)

PRODUCER = "inventory-service"


def outcome_envelope(reservation: Reservation, *, causation_id: str) -> Envelope:
    if reservation.status == "RESERVED":
        remaining = reservation.remaining or {}
        data: InventoryReservedData | InventoryFailedData = InventoryReservedData(
            order_id=reservation.order_id,
            items=[
                ReservedItem(sku=i.sku, quantity=i.quantity, remaining=remaining.get(i.sku, 0))
                for i in reservation.items
            ],
        )
        event_type = EventType.INVENTORY_RESERVED
    else:
        if reservation.reason is None:  # pragma: no cover - a FAILED record always has a reason
            raise ValueError("FAILED reservation without a reason")
        data = InventoryFailedData(
            order_id=reservation.order_id,
            reason=reservation.reason,
            failed_items=[
                FailedItem(sku=f.sku, requested=f.requested, available=f.available)
                for f in reservation.failed_items
            ],
            detail=reservation.detail,
        )
        event_type = EventType.INVENTORY_FAILED
    return Envelope.create(
        event_type=event_type,
        producer=PRODUCER,
        data=data,
        causation_id=causation_id,
        event_id=reservation.event_id,
        occurred_at=reservation.created_at,
    )
