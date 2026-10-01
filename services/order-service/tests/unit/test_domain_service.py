from decimal import Decimal

import pytest
from fakes import FakeCatalog, FakeRepository, FakeStock, make_service, product

from app.domain.errors import (
    IdempotencyKeyReused,
    MixedCurrency,
    OrderNotFound,
    OutOfStock,
    ProductInactive,
    UnknownProduct,
    UpstreamUnavailable,
)
from app.domain.hashing import request_hash
from app.domain.models import OrderLine, StoredOrder
from retail_common.events.envelope import Envelope
from retail_common.events.schemas import OrderCreatedData

KEY = "6f1c2b1e-4a7d-4c55-9a51-0b8e3f0d2c11"
LINES = [OrderLine("SKU-1", 2), OrderLine("SKU-2", 3)]


# --- the happy path ---------------------------------------------------------------------------


def test_a_new_order_is_pending_with_snapshotted_prices_and_an_exact_total() -> None:
    service, repository, _, _ = make_service()

    result = service.create_order("cust-1", KEY, LINES)

    order = result.order
    assert result.created is True
    assert order.status == "PENDING"
    assert order.status_reason is None
    assert order.customer_id == "cust-1"
    assert order.currency == "USD"
    assert [(i.sku, i.quantity, i.unit_price) for i in order.items] == [
        ("SKU-1", 2, Decimal("19.99")),
        ("SKU-2", 3, Decimal("8.99")),
    ]
    assert order.total_amount == Decimal("66.95")  # 2 x 19.99 + 3 x 8.99, exactly
    assert repository.orders[order.order_id] == order


def test_the_total_is_exact_decimal_arithmetic_across_many_lines() -> None:
    skus = [f"SKU-{n:02d}" for n in range(20)]
    catalog = FakeCatalog(*(product(sku, "0.10") for sku in skus))
    service, _, _, _ = make_service(catalog=catalog, stock=FakeStock({sku: 100 for sku in skus}))

    order = service.create_order("cust-1", KEY, [OrderLine(sku, 3) for sku in skus]).order

    assert order.total_amount == Decimal(
        "6.00"
    )  # twenty 3 x 0.10 lines: floats give 6.000000000000001
    assert isinstance(order.total_amount, Decimal)


def test_the_price_is_a_snapshot_later_price_changes_never_alter_an_order() -> None:
    service, repository, catalog, _ = make_service()
    first = service.create_order("cust-1", KEY, LINES).order

    catalog.products["SKU-1"] = product("SKU-1", "99.99")  # the price goes up afterwards
    replay = service.create_order("cust-1", KEY, LINES)

    assert replay.order.items[0].unit_price == Decimal("19.99")
    assert replay.order == first
    assert repository.orders[first.order_id].items[0].unit_price == Decimal("19.99")


def test_the_outbox_event_is_written_with_the_order_and_describes_it() -> None:
    service, repository, _, _ = make_service()

    order = service.create_order("cust-1", KEY, LINES).order

    (event,) = repository.outbox
    assert event.detail_type == "OrderCreated"
    envelope = Envelope.model_validate(event.payload)  # a complete, valid envelope
    assert envelope.event_id == event.event_id
    assert envelope.producer == "order-service"
    data = OrderCreatedData.model_validate(envelope.data)
    assert data.order_id == order.order_id
    assert (data.customer_id, data.currency) == ("cust-1", "USD")
    assert data.total_amount == Decimal("66.95")
    assert [(i.sku, i.quantity) for i in data.items] == [("SKU-1", 2), ("SKU-2", 3)]
    assert envelope.data["total_amount"] == "66.95"  # a string in the stored JSON, never a float


def test_the_service_does_the_cheap_idempotency_check_first_then_prices_then_stock() -> None:
    log: list[str] = []
    repository = FakeRepository()
    repository.find_by_idempotency_key = lambda c, k: (log.append("find"), None)[1]  # type: ignore[method-assign]
    catalog = FakeCatalog(product("SKU-1"), log=log)
    stock = FakeStock({"SKU-1": 5}, log=log)
    service, *_ = make_service(repository, catalog, stock)

    service.create_order("cust-1", KEY, [OrderLine("SKU-1", 1)])

    assert log == ["find", "catalog", "stock"]


# --- idempotency ------------------------------------------------------------------------------


def test_the_same_key_and_body_returns_the_original_without_calling_anything() -> None:
    service, repository, catalog, stock = make_service()
    first = service.create_order("cust-1", KEY, LINES)
    catalog.calls.clear()
    stock.calls = 0

    replay = service.create_order("cust-1", KEY, LINES)

    assert replay.created is False
    assert replay.order == first.order
    assert (catalog.calls, stock.calls) == ([], 0)  # no downstream traffic for a replay
    assert repository.create_calls == 1
    assert len(repository.outbox) == 1  # and no second event


def test_a_replay_survives_stock_running_out_in_the_meantime() -> None:
    service, _, _, stock = make_service()
    first = service.create_order("cust-1", KEY, LINES).order

    stock.levels["SKU-1"] = 0  # the stock is gone

    assert service.create_order("cust-1", KEY, LINES).order == first


def test_reordering_the_items_is_still_the_same_request() -> None:
    service, _, _, _ = make_service()
    first = service.create_order("cust-1", KEY, LINES).order

    replay = service.create_order("cust-1", KEY, list(reversed(LINES)))

    assert replay.created is False
    assert replay.order == first


def test_the_same_key_with_a_different_body_is_rejected() -> None:
    service, repository, _, _ = make_service()
    service.create_order("cust-1", KEY, LINES)

    with pytest.raises(IdempotencyKeyReused):
        service.create_order("cust-1", KEY, [OrderLine("SKU-1", 5)])

    assert len(repository.orders) == 1


def test_a_key_is_scoped_to_the_customer() -> None:
    service, repository, _, _ = make_service()
    a = service.create_order("cust-A", KEY, LINES)
    b = service.create_order("cust-B", KEY, LINES)

    assert a.created is True
    assert b.created is True
    assert a.order.order_id != b.order.order_id
    assert len(repository.orders) == 2


def concurrent_winner(repository: FakeRepository, lines: list[OrderLine]) -> StoredOrder:
    """Another request that carries the same key and commits between our lookup and our insert."""
    won = make_service()[0].create_order("cust-1", KEY, lines).order
    stored = StoredOrder(won, request_hash("cust-1", lines))
    repository.before_create = lambda: repository.by_key.__setitem__(("cust-1", KEY), stored)
    return stored


def test_losing_a_race_for_the_key_behaves_as_a_replay_of_the_winner() -> None:
    """Two requests with one key both pass the lookup; the second to insert finds the first."""
    service, repository, _, _ = make_service()
    winner = concurrent_winner(repository, LINES)

    result = service.create_order("cust-1", KEY, LINES)

    assert result.created is False
    assert result.order == winner.order
    assert repository.outbox == []  # the loser wrote no event


def test_losing_a_race_with_a_different_body_is_still_an_error() -> None:
    service, repository, _, _ = make_service()
    concurrent_winner(repository, [OrderLine("SKU-1", 9)])

    with pytest.raises(IdempotencyKeyReused):
        service.create_order("cust-1", KEY, LINES)


# --- failures leave no trace ------------------------------------------------------------------


def test_out_of_stock_names_the_lines_and_writes_nothing() -> None:
    service, repository, _, _ = make_service(stock=FakeStock({"SKU-1": 1, "SKU-2": 10}))

    with pytest.raises(OutOfStock) as raised:
        service.create_order("cust-1", KEY, [OrderLine("SKU-1", 2), OrderLine("SKU-2", 3)])

    assert str(raised.value) == "SKU-1: requested 2, available 1"
    assert [line.sku for line in raised.value.lines] == ["SKU-1"]
    assert (repository.create_calls, repository.orders, repository.outbox) == (0, {}, [])


def test_every_failing_line_is_reported() -> None:
    service, _, _, _ = make_service(stock=FakeStock({"SKU-1": 1, "SKU-2": 0}))

    with pytest.raises(OutOfStock) as raised:
        service.create_order("cust-1", KEY, LINES)

    assert str(raised.value) == "SKU-1: requested 2, available 1; SKU-2: requested 3, available 0"


def test_a_product_with_no_inventory_record_is_out_of_stock_with_zero_available() -> None:
    service, _, _, _ = make_service(stock=FakeStock({"SKU-1": 10}))  # SKU-2 has no record

    with pytest.raises(OutOfStock) as raised:
        service.create_order("cust-1", KEY, LINES)

    assert str(raised.value) == "SKU-2: requested 3, available 0"


def test_an_unknown_product_is_reported_and_stock_is_never_asked() -> None:
    service, repository, _, stock = make_service()

    with pytest.raises(UnknownProduct) as raised:
        service.create_order(
            "cust-1", KEY, [OrderLine("SKU-1", 1), OrderLine("NOPE", 1), OrderLine("ALSO-NOPE", 1)]
        )

    assert raised.value.skus == ["NOPE", "ALSO-NOPE"]
    assert stock.calls == 0
    assert repository.orders == {}


def test_an_inactive_product_cannot_be_ordered() -> None:
    catalog = FakeCatalog(product("SKU-1"), product("SKU-2", active=False))
    service, repository, _, stock = make_service(catalog=catalog)

    with pytest.raises(ProductInactive) as raised:
        service.create_order("cust-1", KEY, LINES)

    assert raised.value.skus == ["SKU-2"]
    assert stock.calls == 0
    assert repository.orders == {}


def test_mixed_currencies_are_rejected_because_an_order_has_one() -> None:
    catalog = FakeCatalog(product("SKU-1", currency="USD"), product("SKU-2", currency="EUR"))
    service, repository, _, _ = make_service(catalog=catalog)

    with pytest.raises(MixedCurrency) as raised:
        service.create_order("cust-1", KEY, LINES)

    assert raised.value.currencies == ["EUR", "USD"]
    assert repository.orders == {}


@pytest.mark.parametrize("dependency", ["catalog", "stock"])
def test_an_unreachable_dependency_fails_the_request_and_writes_no_partial_order(
    dependency: str,
) -> None:
    service, repository, catalog, stock = make_service()
    (catalog if dependency == "catalog" else stock).down = True

    with pytest.raises(UpstreamUnavailable):
        service.create_order("cust-1", KEY, LINES)

    assert (repository.create_calls, repository.orders, repository.outbox) == (0, {}, [])


def test_a_failed_attempt_can_be_retried_with_the_same_key() -> None:
    service, _, catalog, _ = make_service()
    catalog.down = True
    with pytest.raises(UpstreamUnavailable):
        service.create_order("cust-1", KEY, LINES)

    catalog.down = False
    result = service.create_order("cust-1", KEY, LINES)

    assert result.created is True  # the key was never consumed by the failure


# --- reads ------------------------------------------------------------------------------------


def test_get_order_returns_it_or_raises() -> None:
    service, _, _, _ = make_service()
    order = service.create_order("cust-1", KEY, LINES).order

    assert service.get_order(order.order_id) == order
    with pytest.raises(OrderNotFound):
        service.get_order("01J9Z6Q4W8K3M2N1P0R7S5T4V3")


def test_list_orders_is_newest_first_and_per_customer() -> None:
    service, _, _, _ = make_service()
    first = service.create_order("cust-1", "key-1", LINES).order
    second = service.create_order("cust-1", "key-2", LINES).order
    service.create_order("cust-2", "key-3", LINES)

    page = service.list_orders("cust-1", 1, 10)

    assert page.total == 2
    assert [o.order_id for o in page.items] == [second.order_id, first.order_id]
