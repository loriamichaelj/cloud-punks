"""Stock reservation against LocalStack's real DynamoDB (DESIGN.md sections 5 to 7, ADR-05).

What a Stubber cannot prove is here: the transaction really is all-or-none, two workers cannot
both take the last unit, and a redelivery or a crash between the commit and the follow-up write
never decrements twice. And the transfer of a CloudPunk (DESIGN.md section 16.5): one buyer wins a
race for it, and a resale happens only while the seller still owns it.
"""

import threading
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import new_order_id, put_raw

from app.domain.reservations import (
    ProcessedOrder,
    ReservationService,
    ReservedLine,
)
from app.repo.dynamodb import DynamoInventoryRepository
from app.repo.reservations import DynamoReservationStore
from retail_common.events.envelope import new_event_id

BUYER = "itest-buyer"


@pytest.fixture
def store(dynamodb: Any) -> DynamoReservationStore:
    return DynamoReservationStore(dynamodb)


@pytest.fixture
def service(dynamodb: Any, store: DynamoReservationStore) -> ReservationService:
    return ReservationService(
        store,
        DynamoInventoryRepository(dynamodb),
        new_event_id=new_event_id,
        now=lambda: datetime.now(UTC),
    )


def levels(dynamodb: Any, sku: str) -> tuple[int, int]:
    item = dynamodb.get_item(TableName="inventory", Key={"sku": {"S": sku}}, ConsistentRead=True)[
        "Item"
    ]
    return int(item["available"]["N"]), int(item["reserved"]["N"])


def test_reserving_moves_units_from_available_to_reserved(
    dynamodb: Any, service: ReservationService, sku: str
) -> None:
    put_raw(dynamodb, sku, available=10)

    outcome = service.process(new_order_id(), [ReservedLine(sku, 3)], buyer=BUYER)

    assert outcome.reservation.status == "RESERVED"
    assert outcome.duplicate is False
    assert levels(dynamodb, sku) == (7, 3)
    assert outcome.reservation.remaining == {sku: 7}


def test_reserving_exactly_the_remaining_stock_succeeds_and_leaves_zero(
    dynamodb: Any, service: ReservationService, sku: str
) -> None:
    put_raw(dynamodb, sku, available=4)

    assert (
        service.process(new_order_id(), [ReservedLine(sku, 4)], buyer=BUYER).reservation.status
        == "RESERVED"
    )
    assert levels(dynamodb, sku) == (0, 4)


def test_not_enough_stock_fails_the_order_and_changes_nothing(
    dynamodb: Any, service: ReservationService, sku: str
) -> None:
    put_raw(dynamodb, sku, available=2)

    outcome = service.process(new_order_id(), [ReservedLine(sku, 5)], buyer=BUYER)

    assert outcome.reservation.status == "FAILED"
    assert outcome.reservation.reason == "OUT_OF_STOCK"
    assert [(f.sku, f.requested, f.available) for f in outcome.reservation.failed_items] == [
        (sku, 5, 2)
    ]
    assert levels(dynamodb, sku) == (2, 0)


def test_an_unknown_sku_fails_the_order_with_that_reason(
    service: ReservationService, sku: str
) -> None:
    outcome = service.process(new_order_id(), [ReservedLine(sku, 1)], buyer=BUYER)

    assert outcome.reservation.status == "FAILED"
    assert outcome.reservation.reason == "UNKNOWN_SKU"
    assert [(f.sku, f.available) for f in outcome.reservation.failed_items] == [(sku, 0)]


def test_a_multi_sku_order_is_all_or_none(
    dynamodb: Any, service: ReservationService, sku: str
) -> None:
    """One line cannot be filled, so the line that could have been must not be taken either."""
    plenty, scarce = f"{sku}-A", f"{sku}-B"
    put_raw(dynamodb, plenty, available=10)
    put_raw(dynamodb, scarce, available=1)

    outcome = service.process(
        new_order_id(), [ReservedLine(plenty, 2), ReservedLine(scarce, 3)], buyer=BUYER
    )

    assert outcome.reservation.status == "FAILED"
    assert levels(dynamodb, plenty) == (10, 0)
    assert levels(dynamodb, scarce) == (1, 0)
    assert [f.sku for f in outcome.reservation.failed_items] == [scarce]


def test_a_multi_sku_order_reserves_every_line_together(
    dynamodb: Any, service: ReservationService, sku: str
) -> None:
    first, second = f"{sku}-A", f"{sku}-B"
    put_raw(dynamodb, first, available=10)
    put_raw(dynamodb, second, available=5)

    outcome = service.process(
        new_order_id(), [ReservedLine(first, 2), ReservedLine(second, 5)], buyer=BUYER
    )

    assert outcome.reservation.status == "RESERVED"
    assert levels(dynamodb, first) == (8, 2)
    assert levels(dynamodb, second) == (0, 5)
    assert outcome.reservation.remaining == {first: 8, second: 0}


def test_a_redelivered_order_does_not_decrement_again_and_returns_the_same_event(
    dynamodb: Any, service: ReservationService, sku: str
) -> None:
    put_raw(dynamodb, sku, available=10)
    order_id = new_order_id()

    first = service.process(order_id, [ReservedLine(sku, 3)], buyer=BUYER)
    again = service.process(order_id, [ReservedLine(sku, 3)], buyer=BUYER)

    assert (first.duplicate, again.duplicate) == (False, True)
    assert levels(dynamodb, sku) == (7, 3)
    assert again.reservation.event_id == first.reservation.event_id
    assert again.reservation.remaining == {sku: 7}


def test_a_redelivered_failure_stays_a_failure_even_if_stock_arrives_later(
    dynamodb: Any, service: ReservationService, sku: str
) -> None:
    """The first decision is final: a restock must not turn an announced rejection into a sale."""
    put_raw(dynamodb, sku, available=1)
    order_id = new_order_id()
    first = service.process(order_id, [ReservedLine(sku, 5)], buyer=BUYER)
    put_raw(dynamodb, sku, available=100)

    again = service.process(order_id, [ReservedLine(sku, 5)], buyer=BUYER)

    assert first.reservation.status == again.reservation.status == "FAILED"
    assert again.duplicate is True
    assert levels(dynamodb, sku) == (100, 0)


def test_a_crash_after_the_commit_is_completed_by_the_redelivery(
    dynamodb: Any, store: DynamoReservationStore, service: ReservationService, sku: str
) -> None:
    """The window between the transaction and the write of `remaining`: nothing is decremented
    twice, and the retry still produces a complete outcome."""
    put_raw(dynamodb, sku, available=10)
    order_id, event_id = new_order_id(), new_event_id()
    store.reserve(
        order_id, [ReservedLine(sku, 4)], event_id, datetime.now(UTC), buyer=BUYER
    )  # then "crash"
    assert store.get(order_id).remaining is None  # type: ignore[union-attr]

    retried = service.process(order_id, [ReservedLine(sku, 4)], buyer=BUYER)

    assert retried.duplicate is True
    assert retried.reservation.event_id == event_id
    assert retried.reservation.remaining == {sku: 6}
    assert levels(dynamodb, sku) == (6, 4)


def test_remaining_is_written_once(
    dynamodb: Any, store: DynamoReservationStore, service: ReservationService, sku: str
) -> None:
    put_raw(dynamodb, sku, available=10)
    order_id = new_order_id()
    service.process(order_id, [ReservedLine(sku, 4)], buyer=BUYER)
    put_raw(dynamodb, sku, available=999)  # stock moves on afterwards

    stored = store.store_remaining(order_id, {sku: 999})

    assert stored.remaining == {sku: 6}  # the first value stands: the event must not change


def test_concurrent_orders_never_oversell_the_last_units(
    dynamodb: Any, service: ReservationService, sku: str
) -> None:
    """Stock for 5, 20 orders of one unit each, released together: exactly 5 win."""
    stock, contenders = 5, 20
    put_raw(dynamodb, sku, available=stock)
    outcomes: list[ProcessedOrder] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(contenders)
    lock = threading.Lock()

    def attempt() -> None:
        try:
            barrier.wait(timeout=10)
            outcome = service.process(new_order_id(), [ReservedLine(sku, 1)], buyer=BUYER)
            with lock:
                outcomes.append(outcome)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the main thread below
            errors.append(exc)

    threads = [threading.Thread(target=attempt) for _ in range(contenders)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    if errors:
        raise errors[0]

    winners = [o for o in outcomes if o.reservation.status == "RESERVED"]
    losers = [o for o in outcomes if o.reservation.status == "FAILED"]
    assert len(outcomes) == contenders
    assert len(winners) == stock
    assert len(losers) == contenders - stock
    assert all(o.reservation.reason == "OUT_OF_STOCK" for o in losers)
    assert levels(dynamodb, sku) == (0, stock)


def race(contenders: int, run: Any) -> list[ProcessedOrder]:
    """Release ``contenders`` calls of ``run(i)`` together; return every outcome."""
    outcomes: list[ProcessedOrder] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(contenders)
    lock = threading.Lock()

    def attempt(i: int) -> None:
        try:
            barrier.wait(timeout=10)
            outcome = run(i)
            with lock:
                outcomes.append(outcome)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the main thread below
            errors.append(exc)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(contenders)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    if errors:
        raise errors[0]
    assert len(outcomes) == contenders
    return outcomes


def owner(dynamodb: Any, sku: str) -> str | None:
    item = dynamodb.get_item(TableName="inventory", Key={"sku": {"S": sku}}, ConsistentRead=True)
    return item["Item"].get("owner", {}).get("S")


def test_ten_buyers_race_for_one_cloudpunk_and_exactly_one_becomes_its_owner(
    dynamodb: Any, service: ReservationService, sku: str
) -> None:
    put_raw(dynamodb, sku, available=1)

    outcomes = race(
        10,
        lambda i: service.process(new_order_id(), [ReservedLine(sku, 1)], buyer=f"itest-buyer-{i}"),
    )

    winners = [o for o in outcomes if o.reservation.status == "RESERVED"]
    assert len(winners) == 1
    assert owner(dynamodb, sku) == winners[0].reservation.buyer
    assert levels(dynamodb, sku) == (0, 1)
    losers = [o for o in outcomes if o.reservation.status == "FAILED"]
    assert {(o.reservation.reason, o.reservation.detail) for o in losers} == {
        ("OUT_OF_STOCK", "SOLD")
    }


def test_two_resales_by_one_seller_race_and_only_one_goes_through(
    dynamodb: Any, service: ReservationService, sku: str
) -> None:
    """Two accepted bids for the same CloudPunk: whichever commits first owns it."""
    put_raw(dynamodb, sku, available=0, reserved=1, owner="itest-seller")

    outcomes = race(
        2,
        lambda i: service.process(
            new_order_id(), [ReservedLine(sku, 1)], buyer=f"itest-bidder-{i}", seller="itest-seller"
        ),
    )

    winners = [o for o in outcomes if o.reservation.status == "RESERVED"]
    (loser,) = [o for o in outcomes if o.reservation.status == "FAILED"]
    assert len(winners) == 1
    assert owner(dynamodb, sku) == winners[0].reservation.buyer
    assert loser.reservation.detail == "OWNER_CHANGED"
    assert levels(dynamodb, sku) == (0, 2)  # stock untouched; one more sale counted


def test_a_resale_by_someone_who_no_longer_owns_it_changes_nothing(
    dynamodb: Any, service: ReservationService, sku: str
) -> None:
    put_raw(dynamodb, sku, available=0, reserved=1, owner="itest-new-owner")

    outcome = service.process(
        new_order_id(), [ReservedLine(sku, 1)], buyer=BUYER, seller="itest-old-owner"
    )

    assert (outcome.reservation.status, outcome.reservation.detail) == ("FAILED", "OWNER_CHANGED")
    assert owner(dynamodb, sku) == "itest-new-owner"
    assert levels(dynamodb, sku) == (0, 1)


def test_a_purchase_from_the_platform_records_the_buyer_as_owner(
    dynamodb: Any, service: ReservationService, sku: str
) -> None:
    put_raw(dynamodb, sku, available=1)

    service.process(new_order_id(), [ReservedLine(sku, 1)], buyer=BUYER)

    assert owner(dynamodb, sku) == BUYER
