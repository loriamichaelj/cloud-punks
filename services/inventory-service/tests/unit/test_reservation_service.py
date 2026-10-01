from datetime import UTC, datetime

import pytest
from fakes import FakeReservationStore, FakeStock

from app.domain.errors import InvalidOrder
from app.domain.reservations import ReservationService, ReservedLine
from retail_common.events.envelope import new_event_id

ORDER = "01J9Z6Q4W8K3M2N1P0R7S5T4V3"
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def build(levels: dict[str, int]) -> tuple[ReservationService, FakeReservationStore, FakeStock]:
    stock = FakeStock(levels)
    store = FakeReservationStore(stock)
    return (
        ReservationService(store, stock, new_event_id=new_event_id, now=lambda: NOW),
        store,
        stock,
    )  # type: ignore[arg-type]


def lines(**quantities: int) -> list[ReservedLine]:
    return [ReservedLine(sku, qty) for sku, qty in quantities.items()]


# --- reserving --------------------------------------------------------------------------------


def test_sufficient_stock_is_reserved_and_the_remaining_stock_is_recorded() -> None:
    service, _, stock = build({"A": 10, "B": 4})

    processed = service.process(ORDER, lines(A=2, B=1))

    assert processed.duplicate is False
    assert processed.reservation.status == "RESERVED"
    assert stock.levels == {"A": 8, "B": 3}
    assert processed.reservation.remaining == {"A": 8, "B": 3}


def test_insufficient_stock_on_one_line_reserves_nothing_at_all() -> None:
    service, _, stock = build({"A": 10, "B": 1})

    processed = service.process(ORDER, lines(A=2, B=5))

    assert processed.reservation.status == "FAILED"
    assert processed.reservation.reason == "OUT_OF_STOCK"
    assert [(f.sku, f.requested, f.available) for f in processed.reservation.failed_items] == [
        ("B", 5, 1)
    ]
    assert stock.levels == {"A": 10, "B": 1}  # all or none: A was not touched either


def test_an_unknown_sku_is_reported_as_such_with_zero_available() -> None:
    service, _, _ = build({"A": 10})

    processed = service.process(ORDER, lines(A=1, GHOST=2))

    assert processed.reservation.reason == "UNKNOWN_SKU"
    assert [(f.sku, f.available) for f in processed.reservation.failed_items] == [("GHOST", 0)]


def test_asking_for_exactly_what_is_left_succeeds_and_leaves_zero() -> None:
    service, _, stock = build({"A": 3})
    processed = service.process(ORDER, lines(A=3))
    assert processed.reservation.status == "RESERVED"
    assert stock.levels["A"] == 0
    assert processed.reservation.remaining == {"A": 0}


def test_the_same_sku_on_two_lines_is_an_invalid_order() -> None:
    service, store, _ = build({"A": 10})
    with pytest.raises(InvalidOrder, match="more than once"):
        service.process(ORDER, [ReservedLine("A", 1), ReservedLine("A", 2)])
    assert store.reserve_calls == 0  # it never reached the store


# --- duplicates: idempotent redelivery (ADR-05, ADR-07) ----------------------------------------


def test_a_duplicate_order_created_reserves_nothing_a_second_time() -> None:
    service, store, stock = build({"A": 10})
    first = service.process(ORDER, lines(A=2))

    again = service.process(ORDER, lines(A=2))

    assert again.duplicate is True
    assert stock.levels["A"] == 8  # decremented once
    assert again.reservation == first.reservation
    assert again.reservation.event_id == first.reservation.event_id  # the same outcome event
    assert store.reserve_calls == 2


def test_a_duplicate_of_a_failed_order_returns_the_stored_failure_even_if_stock_has_arrived() -> (
    None
):
    """The decision was made once. Restocking afterwards must not turn a rejected order around."""
    service, _, stock = build({"A": 1})
    first = service.process(ORDER, lines(A=5))
    stock.levels["A"] = 100

    again = service.process(ORDER, lines(A=5))

    assert again.duplicate is True
    assert again.reservation.status == "FAILED"
    assert again.reservation.event_id == first.reservation.event_id
    assert stock.levels["A"] == 100


def test_different_orders_for_the_same_sku_each_get_their_own_reservation() -> None:
    service, _, stock = build({"A": 10})
    one = service.process("01J9Z6Q4W8K3M2N1P0R7S5T4V1", lines(A=2))
    two = service.process("01J9Z6Q4W8K3M2N1P0R7S5T4V2", lines(A=3))

    assert one.reservation.event_id != two.reservation.event_id
    assert stock.levels["A"] == 5


# --- crash windows ----------------------------------------------------------------------------


def test_a_crash_after_reserving_but_before_remaining_is_stored_is_completed_on_redelivery() -> (
    None
):
    service, store, stock = build({"A": 10})
    store.crash_before_remaining = True
    with pytest.raises(RuntimeError, match="process died"):
        service.process(ORDER, lines(A=2))
    assert stock.levels["A"] == 8  # the reservation did commit
    assert store.records[ORDER].remaining is None

    store.crash_before_remaining = False
    redelivered = service.process(ORDER, lines(A=2))

    assert redelivered.duplicate is True  # recognised as already reserved
    assert stock.levels["A"] == 8  # and not reserved again
    assert redelivered.reservation.remaining == {"A": 8}  # but the missing piece is now filled in


def test_remaining_is_written_once_and_never_overwritten() -> None:
    service, store, stock = build({"A": 10})
    first = service.process(ORDER, lines(A=2))
    stock.levels["A"] = 1  # other orders have since consumed stock

    again = service.process(ORDER, lines(A=2))

    assert first.reservation.remaining == {"A": 8}
    assert again.reservation.remaining == {"A": 8}  # the re-emitted event matches the first
    assert store.records[ORDER].remaining == {"A": 8}
