import json
from decimal import Decimal

import pytest
from fakeredis import FakeRedis, FakeServer
from fakes import make_product
from prometheus_client import CollectorRegistry

from app.cache import CacheMetrics, ValkeyProductCache
from app.domain.keys import (
    CATEGORIES_KEY,
    LIST_KEYS_SET,
    list_key,
    product_key,
)
from app.domain.models import Category, ProductPage


class Harness:
    def __init__(self) -> None:
        self.server = FakeServer()
        self.redis = FakeRedis(server=self.server, decode_responses=True)
        self.registry = CollectorRegistry()
        self.cache = ValkeyProductCache(self.redis, CacheMetrics(self.registry))

    def counter(self, name: str, keyspace: str) -> float:
        return self.registry.get_sample_value(name, {"keyspace": keyspace}) or 0.0


@pytest.fixture
def h() -> Harness:
    return Harness()


def page(*skus: str, number: int = 1, size: int = 20) -> ProductPage:
    return ProductPage(
        items=tuple(make_product(sku) for sku in skus), page=number, size=size, total=len(skus)
    )


# --- layout -----------------------------------------------------------------------------------


def test_keys_follow_the_documented_layout() -> None:
    assert product_key("SKU-1") == "product:v1:SKU-1"
    assert list_key(None, 1, 20) == "products:v1:list:_all:1:20"
    assert list_key("apparel", 2, 10) == "products:v1:list:apparel:2:10"
    assert CATEGORIES_KEY == "categories:v1"
    assert LIST_KEYS_SET == "products:v1:listkeys"


def test_ttls_match_the_design(h: Harness) -> None:
    h.cache.set_product(make_product("SKU-1"))
    h.cache.set_page(None, page("SKU-1"))
    h.cache.set_categories([Category("apparel", "Apparel")])

    assert 295 <= h.redis.ttl(product_key("SKU-1")) <= 300
    assert 295 <= h.redis.ttl(list_key(None, 1, 20)) <= 300
    assert 3595 <= h.redis.ttl(CATEGORIES_KEY) <= 3600
    assert h.redis.ttl(LIST_KEYS_SET) > 300  # the tracking set outlives the entries it tracks


# --- round trips ------------------------------------------------------------------------------


def test_a_product_survives_a_round_trip_exactly(h: Harness) -> None:
    original = make_product("SKU-1", price=Decimal("19.90"), description=None)
    h.cache.set_product(original)

    restored = h.cache.get_product("SKU-1")

    assert restored == original
    assert restored is not None
    assert str(restored.price) == "19.90"  # trailing zero preserved
    assert restored.created_at.tzinfo is not None


def test_money_is_stored_as_a_string_in_the_cache_too(h: Harness) -> None:
    h.cache.set_product(make_product("SKU-1", price=Decimal("19.99")))
    assert json.loads(h.redis.get(product_key("SKU-1")))["price"] == "19.99"


def test_a_page_and_categories_round_trip(h: Harness) -> None:
    h.cache.set_page("apparel", page("A", "B", number=2, size=2))
    h.cache.set_categories([Category("apparel", "Apparel"), Category("home", "Home")])

    restored = h.cache.get_page("apparel", 2, 2)

    assert restored is not None
    assert [p.sku for p in restored.items] == ["A", "B"]
    assert (restored.page, restored.size, restored.total) == (2, 2, 2)
    assert h.cache.get_categories() == [Category("apparel", "Apparel"), Category("home", "Home")]


def test_hits_and_misses_are_counted_per_keyspace(h: Harness) -> None:
    assert h.cache.get_product("SKU-1") is None
    h.cache.set_product(make_product("SKU-1"))
    assert h.cache.get_product("SKU-1") is not None
    assert h.cache.get_page(None, 1, 20) is None

    assert h.counter("cache_hits_total", "product") == 1
    assert h.counter("cache_misses_total", "product") == 1
    assert h.counter("cache_misses_total", "product_list") == 1
    assert h.counter("cache_errors_total", "product") == 0


# --- invalidation: never KEYS * ---------------------------------------------------------------


def test_invalidating_listings_deletes_every_tracked_page_and_the_tracking_set(h: Harness) -> None:
    h.cache.set_product(make_product("SKU-1"))
    h.cache.set_categories([Category("apparel", "Apparel")])
    h.cache.set_page(None, page("SKU-1"))
    h.cache.set_page("apparel", page("SKU-1"))
    h.cache.set_page(None, page("SKU-1", number=2, size=5))

    h.cache.invalidate_listings()

    assert h.redis.exists(list_key(None, 1, 20)) == 0
    assert h.redis.exists(list_key("apparel", 1, 20)) == 0
    assert h.redis.exists(list_key(None, 2, 5)) == 0
    assert h.redis.exists(LIST_KEYS_SET) == 0
    assert h.redis.exists(product_key("SKU-1")) == 1  # unrelated keys survive
    assert h.redis.exists(CATEGORIES_KEY) == 1


def test_invalidation_never_scans_the_keyspace(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """KEYS blocks Valkey on a large keyspace; SCAN walks all of it. Neither is allowed."""

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("keyspace scan is forbidden")

    for name in ("keys", "scan", "scan_iter"):
        monkeypatch.setattr(h.redis, name, forbidden)
    h.cache.set_page(None, page("SKU-1"))

    h.cache.invalidate_listings()  # would raise AssertionError if it scanned

    assert h.redis.exists(list_key(None, 1, 20)) == 0


def test_a_large_number_of_tracked_pages_is_deleted_in_chunks(h: Harness) -> None:
    for number in range(1, 1201):
        h.cache.set_page(None, page("SKU-1", number=number, size=1))
    assert h.redis.scard(LIST_KEYS_SET) == 1200

    h.cache.invalidate_listings()

    assert h.redis.dbsize() == 0


def test_invalidating_one_product_leaves_the_others(h: Harness) -> None:
    h.cache.set_product(make_product("SKU-1"))
    h.cache.set_product(make_product("SKU-2"))

    h.cache.invalidate_product("SKU-1")

    assert h.cache.get_product("SKU-1") is None
    assert h.cache.get_product("SKU-2") is not None


# --- the cache is optional: failures are misses -----------------------------------------------


def test_with_valkey_down_nothing_raises_and_errors_are_counted(h: Harness) -> None:
    h.server.connected = False

    assert h.cache.get_product("SKU-1") is None
    h.cache.set_product(make_product("SKU-1"))
    assert h.cache.get_page(None, 1, 20) is None
    h.cache.set_page(None, page("SKU-1"))
    assert h.cache.get_categories() is None
    h.cache.set_categories([Category("apparel", "Apparel")])
    h.cache.invalidate_product("SKU-1")
    h.cache.invalidate_listings()

    assert h.counter("cache_errors_total", "product") == 3  # get, set, delete
    assert h.counter("cache_errors_total", "product_list") == 3  # get, set, invalidate
    assert h.counter("cache_errors_total", "categories") == 2  # get, set
    assert h.counter("cache_misses_total", "product") == 0  # an error is not a miss


def test_a_down_cache_comes_back_without_a_restart(h: Harness) -> None:
    h.server.connected = False
    assert h.cache.get_product("SKU-1") is None

    h.server.connected = True
    h.cache.set_product(make_product("SKU-1"))

    assert h.cache.get_product("SKU-1") is not None


def test_ping_raises_when_valkey_is_down_and_is_quiet_when_up(h: Harness) -> None:
    h.cache.ping()
    h.server.connected = False
    with pytest.raises(Exception, match=r"."):
        h.cache.ping()


@pytest.mark.parametrize(
    "garbage",
    ["not json", "[]", '{"sku": "SKU-1"}', '{"price": "NaN-ish"}', "null", "12"],
)
def test_a_corrupt_entry_is_dropped_and_treated_as_a_miss(h: Harness, garbage: str) -> None:
    h.redis.set(product_key("SKU-1"), garbage)

    assert h.cache.get_product("SKU-1") is None

    assert h.redis.exists(product_key("SKU-1")) == 0  # poison removed, not retried forever
    assert h.counter("cache_errors_total", "product") == 1
    assert h.counter("cache_hits_total", "product") == 0
