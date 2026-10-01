from decimal import Decimal

import pytest
from fakes import FakeCache, FakeRepository, make_product

from app.domain.errors import DuplicateSku, ProductNotFound, UnknownCategory
from app.domain.keys import MAX_CACHED_PAGE
from app.domain.models import NewProduct, ProductChanges
from app.domain.service import ProductService


def build() -> tuple[ProductService, FakeRepository, FakeCache, list[str]]:
    log: list[str] = []
    repository, cache = FakeRepository(log=log), FakeCache(log=log)
    repository.products["SKU-1"] = make_product("SKU-1")
    return ProductService(repository, cache), repository, cache, log


NEW = NewProduct("SKU-2", "Mug", None, "home", Decimal("8.99"), "USD")
CHANGES = ProductChanges("Black T-Shirt v2", None, "apparel", Decimal("24.99"), "USD", True)


# --- cache-aside reads ------------------------------------------------------------------------


def test_first_read_goes_to_the_database_then_is_cached() -> None:
    service, repository, cache, _ = build()

    first = service.get_product("SKU-1")

    assert first.sku == "SKU-1"
    assert repository.calls == ["get_product:SKU-1"]
    assert "SKU-1" in cache.products


def test_second_read_is_served_from_the_cache_without_touching_the_database() -> None:
    service, repository, _, _ = build()
    service.get_product("SKU-1")
    repository.calls.clear()

    service.get_product("SKU-1")

    assert repository.calls == []


def test_unknown_product_raises_and_is_never_cached() -> None:
    service, repository, cache, _ = build()

    with pytest.raises(ProductNotFound):
        service.get_product("NOPE")
    with pytest.raises(ProductNotFound):
        service.get_product("NOPE")

    assert repository.calls == ["get_product:NOPE", "get_product:NOPE"]  # asked the DB both times
    assert cache.products == {}


def test_pages_are_cached_per_category_page_and_size() -> None:
    service, repository, _, _ = build()
    service.list_products(None, 1, 20)
    service.list_products(None, 1, 20)
    service.list_products("apparel", 1, 20)
    service.list_products(None, 1, 10)

    assert repository.calls == [
        "list_products:None:1:20",
        "list_products:apparel:1:20",
        "list_products:None:1:10",
    ]


def test_pages_beyond_the_cache_bound_bypass_the_cache_entirely() -> None:
    service, repository, _, log = build()

    service.list_products(None, MAX_CACHED_PAGE + 1, 20)
    service.list_products(None, MAX_CACHED_PAGE + 1, 20)

    assert repository.calls == [f"list_products:None:{MAX_CACHED_PAGE + 1}:20"] * 2
    assert not any(entry.startswith("cache.") for entry in log)


def test_categories_are_cached() -> None:
    service, repository, _, _ = build()
    service.list_categories()
    service.list_categories()
    assert repository.calls == ["list_categories"]


# --- a cache outage is invisible to callers ---------------------------------------------------


def test_with_the_cache_down_every_read_still_works_from_the_database() -> None:
    service, repository, cache, _ = build()
    cache.down = True

    assert service.get_product("SKU-1").sku == "SKU-1"
    assert service.get_product("SKU-1").sku == "SKU-1"
    assert service.list_products(None, 1, 20).total == 1
    assert [c.slug for c in service.list_categories()] == ["apparel", "home"]

    assert repository.calls.count("get_product:SKU-1") == 2  # no cache, so the DB served both


def test_with_the_cache_down_writes_still_succeed() -> None:
    service, _, cache, _ = build()
    cache.down = True

    assert service.create_product(NEW).sku == "SKU-2"
    assert service.update_product("SKU-1", CHANGES).price == Decimal("24.99")


# --- writes: commit first, then invalidate -----------------------------------------------------


def test_create_invalidates_listings_only_after_the_database_write() -> None:
    service, _, _, log = build()

    service.create_product(NEW)

    assert log == ["repo.create", "cache.invalidate_listings"]


def test_update_invalidates_the_product_and_listings_after_the_database_write() -> None:
    service, _, _, log = build()

    service.update_product("SKU-1", CHANGES)

    assert log == [
        "repo.update",
        "cache.invalidate_product:SKU-1",
        "cache.invalidate_listings",
    ]


def test_an_update_is_visible_on_the_next_read_not_five_minutes_later() -> None:
    service, _, _, _ = build()
    assert service.get_product("SKU-1").price == Decimal("19.99")  # warms the cache
    service.list_products(None, 1, 20)  # warms a listing

    service.update_product("SKU-1", CHANGES)

    assert service.get_product("SKU-1").price == Decimal("24.99")
    assert service.list_products(None, 1, 20).items[0].price == Decimal("24.99")


@pytest.mark.parametrize(
    ("operation", "error"),
    [
        (
            lambda s: s.create_product(
                NewProduct("SKU-1", "x", None, "apparel", Decimal("1"), "USD")
            ),
            DuplicateSku,
        ),
        (
            lambda s: s.create_product(NewProduct("N", "x", None, "nope", Decimal("1"), "USD")),
            UnknownCategory,
        ),
        (lambda s: s.update_product("MISSING", CHANGES), ProductNotFound),
    ],
)
def test_a_failed_write_leaves_the_cache_untouched(operation, error) -> None:
    service, _, _, log = build()

    with pytest.raises(error):
        operation(service)

    assert not any(entry.startswith("cache.invalidate") for entry in log)
