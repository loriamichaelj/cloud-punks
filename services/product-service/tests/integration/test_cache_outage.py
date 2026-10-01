"""Valkey failing while the service runs: the 'cache down' drill, in-process."""

import time

from conftest import CATEGORY, TcpProxy, make_client, sample
from fastapi.testclient import TestClient


def create(client: TestClient, sku: str, price: str = "5.5") -> None:
    assert (
        client.post(
            "/api/v1/products",
            json={"sku": sku, "name": "Itest", "category": CATEGORY, "price": price},
        ).status_code
        == 201
    )


def test_valkey_dying_mid_flight_does_not_break_reads_writes_or_readiness(
    proxy: TcpProxy, sku: str
) -> None:
    client = next(make_client(proxy.url))
    create(client, sku)
    client.get(f"/api/v1/products/{sku}")
    client.get(f"/api/v1/products/{sku}")
    assert sample(client, "cache_hits_total", keyspace="product") == 1  # the cache was working

    proxy.stop()  # Valkey disappears; the service still holds pooled connections to it

    assert client.get(f"/api/v1/products/{sku}").status_code == 200  # served from PostgreSQL
    assert client.get("/api/v1/products").status_code == 200
    create(client, f"{sku}-b")
    assert (
        client.put(
            f"/api/v1/products/{sku}",
            json={"name": "x", "category": CATEGORY, "price": "7.25"},
        ).json()["price"]
        == "7.25"
    )
    assert client.get(f"/api/v1/products/{sku}").json()["price"] == "7.25"  # not a stale copy

    assert sample(client, "cache_errors_total", keyspace="product") > 0  # and it was noticed
    ready = client.get("/health/ready")
    assert ready.status_code == 200  # readiness is unaffected by the cache
    assert ready.json()["dependencies"]["valkey"]["status"] == "error"


def test_the_cache_recovers_by_itself_when_valkey_returns(proxy: TcpProxy, sku: str) -> None:
    client = next(make_client(proxy.url))
    create(client, sku)
    proxy.stop()
    client.get(f"/api/v1/products/{sku}")  # fails over to PostgreSQL

    proxy.start()  # Valkey is back; no restart of the service

    hits = 0.0
    for _ in range(5):  # the first call or two may still discover the dead pooled connections
        client.get(f"/api/v1/products/{sku}")
        hits = sample(client, "cache_hits_total", keyspace="product")
        if hits:
            break
    assert hits >= 1
    assert client.get("/health/ready").json()["dependencies"]["valkey"]["status"] == "ok"


def test_a_cache_that_accepts_connections_but_never_answers_is_bounded_by_the_timeout(
    proxy: TcpProxy, sku: str
) -> None:
    """The nastier outage: no refusal, just silence. The socket timeout (0.25 s) must cap it."""
    proxy.stop()
    proxy.start(hang=True)
    client = next(make_client(proxy.url))
    create(client, sku)

    started = time.perf_counter()
    response = client.get(f"/api/v1/products/{sku}")
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert elapsed < 2.0, f"a hung cache stalled the request for {elapsed:.2f}s"
    assert sample(client, "cache_errors_total", keyspace="product") > 0


def test_a_refused_cache_costs_almost_nothing(sku: str) -> None:
    client = next(make_client("redis://127.0.0.1:1/0"))
    create(client, sku)

    started = time.perf_counter()
    for _ in range(20):
        assert client.get(f"/api/v1/products/{sku}").status_code == 200
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0, f"20 reads took {elapsed:.2f}s with the cache refusing connections"
