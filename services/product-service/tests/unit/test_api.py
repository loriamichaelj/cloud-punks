from decimal import Decimal
from typing import Any

import pytest
from fakes import FakeCache, FakeRepository, make_product, make_settings
from fastapi.testclient import TestClient

from app.domain.errors import StoreUnavailable
from app.main import create_app
from retail_common.health import ReadinessCheck
from retail_common.logging import CORRELATION_HEADER

CREATE = {
    "sku": "SKU-NEW",
    "name": "Ceramic Mug",
    "description": "350 ml stoneware mug.",
    "category": "home",
    "price": "8.99",
}


@pytest.fixture
def repository() -> FakeRepository:
    repository = FakeRepository()
    repository.products["SKU-1"] = make_product("SKU-1")
    return repository


@pytest.fixture
def client(repository: FakeRepository) -> TestClient:
    return TestClient(create_app(make_settings(), repository=repository, cache=FakeCache()))


def code(response: Any) -> str:
    return str(response.json()["error"]["code"])


# --- reads ------------------------------------------------------------------------------------


def test_get_product_returns_money_as_a_string(client: TestClient) -> None:
    response = client.get("/api/v1/products/SKU-1")

    assert response.status_code == 200
    body = response.json()
    assert body["price"] == "19.99"
    assert isinstance(body["price"], str)
    assert body["sku"] == "SKU-1"
    assert body["category"] == "apparel"
    assert body["created_at"].startswith("2026-10-01T12:00:00")


def test_a_trailing_zero_price_keeps_its_two_decimals(
    client: TestClient, repository: FakeRepository
) -> None:
    repository.products["SKU-1"] = make_product("SKU-1", price=Decimal("19.90"))
    assert client.get("/api/v1/products/SKU-1").json()["price"] == "19.90"


def test_unknown_product_is_404_in_the_shared_error_shape(client: TestClient) -> None:
    response = client.get("/api/v1/products/NOPE", headers={CORRELATION_HEADER: "corr-9"})

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "PRODUCT_NOT_FOUND",
        "message": "product 'NOPE' not found",
        "correlation_id": "corr-9",
    }


def test_list_products_has_the_documented_page_envelope(client: TestClient) -> None:
    body = client.get("/api/v1/products").json()

    assert body["page"] == 1
    assert body["size"] == 20
    assert body["total"] == 1
    assert [item["sku"] for item in body["items"]] == ["SKU-1"]


def test_list_filters_by_category(client: TestClient, repository: FakeRepository) -> None:
    repository.products["SKU-M"] = make_product("SKU-M", category="home")

    assert [i["sku"] for i in client.get("/api/v1/products?category=home").json()["items"]] == [
        "SKU-M"
    ]


def test_inactive_products_are_not_listed_but_can_still_be_fetched(
    client: TestClient, repository: FakeRepository
) -> None:
    repository.products["SKU-OFF"] = make_product("SKU-OFF", active=False)

    listed = [i["sku"] for i in client.get("/api/v1/products").json()["items"]]

    assert "SKU-OFF" not in listed
    assert client.get("/api/v1/products/SKU-OFF").json()["active"] is False


@pytest.mark.parametrize(
    "query", ["page=0", "page=-1", "size=0", "size=101", "page=abc", "category=Not%20A%20Slug"]
)
def test_invalid_list_parameters_are_422(client: TestClient, query: str) -> None:
    response = client.get(f"/api/v1/products?{query}")
    assert response.status_code == 422
    assert code(response) == "VALIDATION_ERROR"


def test_categories(client: TestClient) -> None:
    body = client.get("/api/v1/categories").json()
    assert body == {
        "items": [{"slug": "apparel", "name": "Apparel"}, {"slug": "home", "name": "Home"}]
    }


# --- create -----------------------------------------------------------------------------------


def test_create_returns_201_and_the_product(client: TestClient) -> None:
    response = client.post("/api/v1/products", json=CREATE)

    assert response.status_code == 201
    body = response.json()
    assert body["sku"] == "SKU-NEW"
    assert body["price"] == "8.99"
    assert body["currency"] == "USD"  # default
    assert body["active"] is True


def test_a_created_product_can_be_read_back(client: TestClient) -> None:
    client.post("/api/v1/products", json=CREATE)
    assert client.get("/api/v1/products/SKU-NEW").json()["name"] == "Ceramic Mug"


def test_duplicate_sku_is_409(client: TestClient) -> None:
    client.post("/api/v1/products", json=CREATE)
    response = client.post("/api/v1/products", json=CREATE)
    assert response.status_code == 409
    assert code(response) == "SKU_EXISTS"


def test_unknown_category_is_422(client: TestClient) -> None:
    response = client.post("/api/v1/products", json={**CREATE, "category": "nonexistent"})
    assert response.status_code == 422
    assert code(response) == "UNKNOWN_CATEGORY"


@pytest.mark.parametrize("price", [8.99, 9, True, None, [], {"v": 1}])
def test_a_price_that_is_not_a_string_is_rejected(client: TestClient, price: object) -> None:
    """Money is never a JSON number: it would pass through a float on the way in."""
    response = client.post("/api/v1/products", json={**CREATE, "price": price})

    assert response.status_code == 422
    assert "price" in response.json()["error"]["message"]


@pytest.mark.parametrize(
    "price", ["-0.01", "8.999", "abc", "", "12345678901.00", "NaN", "Infinity"]
)
def test_an_invalid_decimal_string_is_rejected(client: TestClient, price: str) -> None:
    response = client.post("/api/v1/products", json={**CREATE, "price": price})
    assert response.status_code == 422


def test_zero_and_one_decimal_prices_are_accepted(client: TestClient) -> None:
    assert client.post("/api/v1/products", json={**CREATE, "price": "0"}).status_code == 201
    assert (
        client.post("/api/v1/products", json={**CREATE, "sku": "SKU-B", "price": "5.5"}).json()[
            "price"
        ]
        == "5.50"
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"sku": "has space"},
        {"sku": ""},
        {"sku": "x" * 65},
        {"name": ""},
        {"category": "UPPER"},
        {"currency": "usd"},
        {"unexpected_field": 1},
    ],
)
def test_invalid_create_bodies_are_422(client: TestClient, overrides: dict[str, object]) -> None:
    response = client.post("/api/v1/products", json={**CREATE, **overrides})
    assert response.status_code == 422
    assert code(response) == "VALIDATION_ERROR"


def test_validation_errors_never_echo_the_submitted_values(client: TestClient) -> None:
    response = client.post("/api/v1/products", json={**CREATE, "name": "", "price": "SECRET-9999"})
    assert "SECRET-9999" not in response.text


# --- update -----------------------------------------------------------------------------------

UPDATE = {"name": "Black T-Shirt v2", "category": "apparel", "price": "24.99"}


def test_put_replaces_the_mutable_fields(client: TestClient) -> None:
    response = client.put("/api/v1/products/SKU-1", json={**UPDATE, "active": False})

    assert response.status_code == 200
    body = response.json()
    assert body["price"] == "24.99"
    assert body["name"] == "Black T-Shirt v2"
    assert body["active"] is False


def test_put_to_an_unknown_sku_is_404(client: TestClient) -> None:
    response = client.put("/api/v1/products/NOPE", json=UPDATE)
    assert response.status_code == 404
    assert code(response) == "PRODUCT_NOT_FOUND"


def test_put_cannot_change_the_sku(client: TestClient) -> None:
    response = client.put("/api/v1/products/SKU-1", json={**UPDATE, "sku": "OTHER"})
    assert response.status_code == 422


def test_put_rejects_a_numeric_price(client: TestClient) -> None:
    assert client.put("/api/v1/products/SKU-1", json={**UPDATE, "price": 24.99}).status_code == 422


def test_put_to_an_unknown_category_is_422(client: TestClient) -> None:
    response = client.put("/api/v1/products/SKU-1", json={**UPDATE, "category": "nonexistent"})
    assert response.status_code == 422
    assert code(response) == "UNKNOWN_CATEGORY"


# --- readiness, metrics, contract -------------------------------------------------------------


def test_readiness_follows_the_required_store_only() -> None:
    def down() -> None:
        raise ConnectionError("db down")

    def up() -> None:
        return None

    def build(postgres: object, valkey: object) -> TestClient:
        probes = (
            ReadinessCheck("postgres", postgres),  # type: ignore[arg-type]
            ReadinessCheck("valkey", valkey, required=False),  # type: ignore[arg-type]
        )
        return TestClient(
            create_app(
                make_settings(),
                repository=FakeRepository(),
                cache=FakeCache(),
                readiness_probes=probes,
            )
        )

    assert build(up, up).get("/health/ready").status_code == 200
    assert build(up, down).get("/health/ready").status_code == 200  # cache down: still ready
    assert build(down, up).get("/health/ready").status_code == 503  # database down: not ready
    assert build(down, up).get("/health/live").status_code == 200  # ... but still alive


def test_metrics_use_route_templates(client: TestClient) -> None:
    client.get("/api/v1/products/SKU-1")
    client.get("/api/v1/products/SKU-2")

    text = client.get("/metrics").text
    assert 'route="/api/v1/products/{sku}"' in text
    assert "SKU-1" not in text


def test_openapi_documents_every_endpoint(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert set(paths["/api/v1/products"]) == {"get", "post"}
    assert set(paths["/api/v1/products/{sku}"]) == {"get", "put"}
    assert set(paths["/api/v1/categories"]) == {"get"}


# --- the store being unavailable is a 503, never a 500 ----------------------------------------


def test_a_store_outage_is_a_503_with_retry_after_and_a_generic_message() -> None:
    class DownRepository(FakeRepository):
        def get_product(self, sku: str):  # type: ignore[no-untyped-def]
            raise StoreUnavailable

    client = TestClient(create_app(make_settings(), repository=DownRepository(), cache=FakeCache()))

    response = client.get("/api/v1/products/SKU-1", headers={CORRELATION_HEADER: "corr-down"})

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.json()["error"] == {
        "code": "STORE_UNAVAILABLE",
        "message": "the product store is temporarily unavailable",
        "correlation_id": "corr-down",
    }
