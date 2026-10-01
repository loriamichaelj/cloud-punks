import pytest
from fakes import FakeRepository, make_item

from app.domain.errors import StockNotFound
from app.domain.models import RequestedLine
from app.domain.service import InventoryService, evaluate_availability

STOCK = {item.sku: item for item in (make_item("A", 10), make_item("B", 1), make_item("C", 0))}


def line(sku: str, quantity: int) -> RequestedLine:
    return RequestedLine(sku, quantity)


def test_enough_stock_is_sufficient() -> None:
    report = evaluate_availability([line("A", 2)], STOCK)

    assert report.available is True
    assert report.lines[0].sufficient is True
    assert report.lines[0].reason is None
    assert (report.lines[0].requested, report.lines[0].available) == (2, 10)


def test_asking_for_exactly_the_stock_on_hand_is_sufficient() -> None:
    assert evaluate_availability([line("A", 10)], STOCK).available is True


def test_asking_for_one_more_than_the_stock_is_out_of_stock() -> None:
    report = evaluate_availability([line("A", 11)], STOCK)

    assert report.available is False
    assert report.lines[0].reason == "OUT_OF_STOCK"
    assert report.lines[0].available == 10  # tells the caller how much there really is


def test_zero_stock_is_out_of_stock_not_unknown() -> None:
    assert evaluate_availability([line("C", 1)], STOCK).lines[0].reason == "OUT_OF_STOCK"


def test_an_sku_with_no_record_is_unknown_with_zero_available() -> None:
    report = evaluate_availability([line("NOPE", 1)], STOCK)

    assert report.available is False
    assert report.lines[0].reason == "UNKNOWN_SKU"
    assert report.lines[0].available == 0


def test_one_bad_line_makes_the_whole_order_unavailable_but_lines_stay_individual() -> None:
    report = evaluate_availability([line("A", 2), line("B", 5), line("NOPE", 1)], STOCK)

    assert report.available is False
    assert [r.sufficient for r in report.lines] == [True, False, False]
    assert [r.reason for r in report.lines] == [None, "OUT_OF_STOCK", "UNKNOWN_SKU"]


def test_results_keep_the_request_order() -> None:
    report = evaluate_availability([line("C", 1), line("A", 1), line("B", 1)], STOCK)
    assert [r.sku for r in report.lines] == ["C", "A", "B"]


def test_an_empty_request_is_vacuously_available() -> None:
    assert evaluate_availability([], STOCK).available is True


def test_get_stock_returns_the_record_or_raises() -> None:
    service = InventoryService(FakeRepository(make_item("A", 7)))

    assert service.get_stock("A").available == 7
    with pytest.raises(StockNotFound):
        service.get_stock("NOPE")


def test_every_read_goes_to_the_repository_there_is_no_cache() -> None:
    repository = FakeRepository(make_item("A", 7))
    service = InventoryService(repository)

    service.get_stock("A")
    service.get_stock("A")
    service.check_availability([line("A", 1)])
    service.check_availability([line("A", 1)])

    assert repository.calls == ["get:A", "get:A", "get_many:A", "get_many:A"]


def test_set_stock_returns_the_updated_record() -> None:
    service = InventoryService(FakeRepository(make_item("A", 7, reserved=3)))

    updated = service.set_stock("A", 40)

    assert (updated.available, updated.reserved) == (40, 3)
