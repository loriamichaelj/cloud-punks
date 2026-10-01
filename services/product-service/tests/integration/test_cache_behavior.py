"""Cache-aside, TTLs and invalidation against real Valkey (cache up only)."""

import json

from conftest import CATEGORY, sample
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import Engine, text


def create(client: TestClient, sku: str, price: str = "5.5") -> None:
    response = client.post(
        "/api/v1/products",
        json={"sku": sku, "name": "Itest", "category": CATEGORY, "price": price},
    )
    assert response.status_code == 201


def test_first_read_misses_the_second_hits(up_client: TestClient, sku: str, valkey: Redis) -> None:
    create(up_client, sku)

    up_client.get(f"/api/v1/products/{sku}")
    up_client.get(f"/api/v1/products/{sku}")

    assert sample(up_client, "cache_misses_total", keyspace="product") == 1
    assert sample(up_client, "cache_hits_total", keyspace="product") == 1
    assert sample(up_client, "cache_errors_total", keyspace="product") == 0


def test_the_cached_entry_has_the_documented_key_ttl_and_string_money(
    up_client: TestClient, sku: str, valkey: Redis
) -> None:
    create(up_client, sku, "19.9")
    up_client.get(f"/api/v1/products/{sku}")

    key = f"product:v1:{sku}"
    assert 295 <= valkey.ttl(key) <= 300
    assert json.loads(valkey.get(key))["price"] == "19.90"  # type: ignore[arg-type]


def test_a_hit_really_comes_from_the_cache_not_the_database(
    up_client: TestClient, sku: str, engine: Engine
) -> None:
    """Change the row behind the cache's back: only a cache hit could still return the old price."""
    create(up_client, sku, "5.5")
    up_client.get(f"/api/v1/products/{sku}")  # fill

    with engine.begin() as connection:
        connection.execute(text("UPDATE products SET price = 99 WHERE sku = :s"), {"s": sku})

    assert up_client.get(f"/api/v1/products/{sku}").json()["price"] == "5.50"  # stale, as designed


def test_put_drops_the_cached_product_so_the_next_read_is_fresh(
    up_client: TestClient, sku: str, valkey: Redis
) -> None:
    create(up_client, sku, "5.5")
    up_client.get(f"/api/v1/products/{sku}")
    assert valkey.exists(f"product:v1:{sku}") == 1

    up_client.put(
        f"/api/v1/products/{sku}", json={"name": "x", "category": CATEGORY, "price": "7.25"}
    )

    assert valkey.exists(f"product:v1:{sku}") == 0
    assert up_client.get(f"/api/v1/products/{sku}").json()["price"] == "7.25"


def test_a_listing_is_cached_tracked_and_cleared_by_a_write(
    up_client: TestClient, sku: str, valkey: Redis
) -> None:
    create(up_client, sku)
    list_url = f"/api/v1/products?category={CATEGORY}&page=1&size=20"
    key = f"products:v1:list:{CATEGORY}:1:20"

    up_client.get(list_url)
    up_client.get(list_url)

    assert sample(up_client, "cache_hits_total", keyspace="product_list") == 1
    assert 295 <= valkey.ttl(key) <= 300
    assert key in valkey.smembers("products:v1:listkeys")

    create(up_client, f"{sku}-b")  # a write: tracked listings must go

    assert valkey.exists(key) == 0
    assert valkey.exists("products:v1:listkeys") == 0
    assert up_client.get(list_url).json()["total"] == 2


def test_unrelated_cached_data_survives_a_write(
    up_client: TestClient, sku: str, valkey: Redis
) -> None:
    create(up_client, sku)
    up_client.get("/api/v1/categories")
    up_client.get(f"/api/v1/products/{sku}")

    create(up_client, f"{sku}-b")

    assert valkey.exists("categories:v1") == 1
    assert valkey.exists(f"product:v1:{sku}") == 1  # a create only drops listings


def test_categories_are_cached_for_an_hour(up_client: TestClient, valkey: Redis) -> None:
    up_client.get("/api/v1/categories")
    up_client.get("/api/v1/categories")

    assert 3595 <= valkey.ttl("categories:v1") <= 3600
    assert sample(up_client, "cache_hits_total", keyspace="categories") == 1


def test_a_missing_product_is_not_cached(up_client: TestClient, valkey: Redis) -> None:
    up_client.get("/api/v1/products/ITEST-NOPE")
    assert valkey.exists("product:v1:ITEST-NOPE") == 0


def test_the_inventory_data_is_never_cached(up_client: TestClient, valkey: Redis) -> None:
    """DESIGN.md: stock is never cached. Product caching must not leak any such key."""
    up_client.get("/api/v1/products")
    assert [k for k in valkey.scan_iter("*") if "inventory" in k or "stock" in k] == []
