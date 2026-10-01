import contextvars
from datetime import UTC, datetime

from app.consumer.events import outcome_envelope
from app.domain.reservations import FailedLine, Reservation, ReservedLine
from retail_common.events.envelope import Envelope
from retail_common.events.schemas import InventoryFailedData, InventoryReservedData, validate_data
from retail_common.logging import set_correlation_id

ORDER = "01J9Z6Q4W8K3M2N1P0R7S5T4V3"
EVENT_ID = "01J9Z6R0C4D5E6F7G8H9J0K1M2"
CAUSE = "01J9Z6Q4W8K3M2N1P0R7S5T4V4"
WHEN = datetime(2026, 10, 1, 12, 0, 0, 123000, tzinfo=UTC)

RESERVED = Reservation(
    ORDER, "RESERVED", (ReservedLine("A", 2), ReservedLine("B", 1)), EVENT_ID, WHEN,
    remaining={"A": 8, "B": 0},
)  # fmt: skip
FAILED = Reservation(
    ORDER, "FAILED", (ReservedLine("A", 5),), EVENT_ID, WHEN,
    reason="OUT_OF_STOCK", failed_items=(FailedLine("A", 5, 1),),
)  # fmt: skip


def build(reservation: Reservation) -> Envelope:
    return contextvars.copy_context().run(
        lambda: (set_correlation_id("corr-1"), outcome_envelope(reservation, causation_id=CAUSE))[1]
    )


def test_a_reserved_outcome_is_a_valid_inventory_reserved_event() -> None:
    envelope = build(RESERVED)

    data = validate_data(envelope)
    assert isinstance(data, InventoryReservedData)
    assert envelope.event_type == "InventoryReserved"
    assert [(i.sku, i.quantity, i.remaining) for i in data.items] == [("A", 2, 8), ("B", 1, 0)]


def test_a_failed_outcome_is_a_valid_inventory_failed_event() -> None:
    envelope = build(FAILED)

    data = validate_data(envelope)
    assert isinstance(data, InventoryFailedData)
    assert envelope.event_type == "InventoryFailed"
    assert data.reason == "OUT_OF_STOCK"
    assert [(f.sku, f.requested, f.available) for f in data.failed_items] == [("A", 5, 1)]


def test_the_event_carries_the_stored_id_and_time_so_a_re_emission_is_the_same_event() -> None:
    first, second = build(RESERVED), build(RESERVED)

    assert first.event_id == second.event_id == EVENT_ID
    assert first.occurred_at == second.occurred_at == WHEN
    assert first.model_dump_json() == second.model_dump_json()  # byte-identical on the wire


def test_the_event_links_back_to_the_order_created_event_and_keeps_the_correlation_id() -> None:
    envelope = build(RESERVED)
    assert envelope.causation_id == CAUSE
    assert envelope.correlation_id == "corr-1"
    assert envelope.producer == "inventory-service"


def test_money_free_payloads_use_only_integers() -> None:
    data = build(RESERVED).data
    assert all(
        isinstance(i["quantity"], int) and isinstance(i["remaining"], int) for i in data["items"]
    )
