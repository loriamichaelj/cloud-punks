"""The API against real PostgreSQL. Every test runs twice, with Valkey up and with Valkey down;
the results must be identical because the cache is an optimisation, not a dependency."""

from datetime import datetime

from conftest import CATEGORY
from fastapi.testclient import TestClient


def body(sku: str, **overrides: object) -> dict[str, object]:
    return {
        "sku": sku,
        "name": "Itest Mug",
        "description": "integration test product",
        "category": CATEGORY,
        "price": "5.5",
        **overrides,
    }


def update_body(**overrides: object) -> dict[str, object]:
    return {"name": "Itest Mug v2", "category": CATEGORY, "price": "7.25", **overrides}


def test_create_read_update_roundtrip(client: TestClient, sku: str) -> None:
    created = client.post("/api/v1/products", json=body(sku))
    assert created.status_code == 201
    assert created.json()["price"] == "5.50"  # PostgreSQL NUMERIC(10,2), serialized as a string

    fetched = client.get(f"/api/v1/products/{sku}")
    assert fetched.status_code == 200
    assert fetched.json() == created.json()

    updated = client.put(f"/api/v1/products/{sku}", json=update_body())
    assert updated.status_code == 200
    assert updated.json()["price"] == "7.25"
    assert updated.json()["name"] == "Itest Mug v2"

    # No five-minute staleness: the very next read sees the update, with the cache up or down.
    assert client.get(f"/api/v1/products/{sku}").json()["price"] == "7.25"


def test_updated_at_moves_and_created_at_does_not(client: TestClient, sku: str) -> None:
    created = client.post("/api/v1/products", json=body(sku)).json()
    updated = client.put(f"/api/v1/products/{sku}", json=update_body()).json()

    assert updated["created_at"] == created["created_at"]
    assert datetime.fromisoformat(updated["updated_at"]) > datetime.fromisoformat(
        created["updated_at"]
    )


def test_money_keeps_exact_precision_through_the_database(client: TestClient, sku: str) -> None:
    for price in ("99999999.99", "0.01", "0.00", "1234.50"):
        client.post("/api/v1/products", json=body(f"{sku}-{price}", price=price))
        assert client.get(f"/api/v1/products/{sku}-{price}").json()["price"] == price


def test_timestamps_are_timezone_aware_utc(client: TestClient, sku: str) -> None:
    client.post("/api/v1/products", json=body(sku))
    created_at = datetime.fromisoformat(client.get(f"/api/v1/products/{sku}").json()["created_at"])
    assert created_at.utcoffset() is not None
    assert created_at.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


def test_unknown_product_is_a_404_with_the_shared_error_shape(client: TestClient) -> None:
    response = client.get("/api/v1/products/ITEST-DOES-NOT-EXIST")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCT_NOT_FOUND"
    assert response.json()["error"]["correlation_id"]


def test_duplicate_sku_is_409_and_does_not_overwrite(client: TestClient, sku: str) -> None:
    client.post("/api/v1/products", json=body(sku, price="5.5"))

    again = client.post("/api/v1/products", json=body(sku, price="9.99"))

    assert again.status_code == 409
    assert again.json()["error"]["code"] == "SKU_EXISTS"
    assert client.get(f"/api/v1/products/{sku}").json()["price"] == "5.50"


def test_unknown_category_is_422_and_nothing_is_written(client: TestClient, sku: str) -> None:
    response = client.post("/api/v1/products", json=body(sku, category="no-such-category"))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNKNOWN_CATEGORY"
    assert client.get(f"/api/v1/products/{sku}").status_code == 404


def test_put_to_a_missing_product_is_404_and_creates_nothing(client: TestClient, sku: str) -> None:
    assert client.put(f"/api/v1/products/{sku}", json=update_body()).status_code == 404
    assert client.get(f"/api/v1/products/{sku}").status_code == 404


def test_listing_paginates_in_sku_order_with_a_total(client: TestClient, sku: str) -> None:
    for n in range(5):
        client.post("/api/v1/products", json=body(f"{sku}-{n}"))

    first = client.get(f"/api/v1/products?category={CATEGORY}&page=1&size=2").json()
    last = client.get(f"/api/v1/products?category={CATEGORY}&page=3&size=2").json()
    beyond = client.get(f"/api/v1/products?category={CATEGORY}&page=4&size=2").json()

    assert first["total"] == 5
    assert [i["sku"] for i in first["items"]] == [f"{sku}-0", f"{sku}-1"]
    assert [i["sku"] for i in last["items"]] == [f"{sku}-4"]
    assert beyond["items"] == []
    assert beyond["total"] == 5


def test_inactive_products_leave_the_listing_immediately(client: TestClient, sku: str) -> None:
    client.post("/api/v1/products", json=body(sku))
    listed = lambda: [  # noqa: E731
        i["sku"] for i in client.get(f"/api/v1/products?category={CATEGORY}").json()["items"]
    ]
    assert sku in listed()

    client.put(f"/api/v1/products/{sku}", json=update_body(active=False))

    assert sku not in listed()
    assert client.get(f"/api/v1/products/{sku}").json()["active"] is False  # still fetchable


def test_a_new_product_appears_in_an_already_fetched_listing(client: TestClient, sku: str) -> None:
    before = client.get(f"/api/v1/products?category={CATEGORY}").json()["total"]  # may warm a cache

    client.post("/api/v1/products", json=body(sku))

    assert client.get(f"/api/v1/products?category={CATEGORY}").json()["total"] == before + 1


def test_categories_include_the_test_category(client: TestClient) -> None:
    slugs = [c["slug"] for c in client.get("/api/v1/categories").json()["items"]]
    assert CATEGORY in slugs


def test_readiness_is_green_in_both_modes_and_reports_the_cache_honestly(
    client: TestClient, cache_mode: str
) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    dependencies = response.json()["dependencies"]
    assert dependencies["postgres"] == {
        **dependencies["postgres"],
        "status": "ok",
        "required": True,
    }
    assert dependencies["valkey"]["required"] is False
    assert dependencies["valkey"]["status"] == ("ok" if cache_mode == "up" else "error")


def test_liveness_never_depends_on_a_store(client: TestClient) -> None:
    assert client.get("/health/live").status_code == 200
