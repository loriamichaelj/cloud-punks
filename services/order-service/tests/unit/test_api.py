import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeCatalog, FakeRepository, FakeStock, make_settings, product
from fastapi.testclient import TestClient

from app.domain.models import OrderLine
from app.main import create_app
from retail_common.health import ReadinessCheck
from retail_common.logging import CORRELATION_HEADER

KEY = "6f1c2b1e-4a7d-4c55-9a51-0b8e3f0d2c11"
HEADERS = {"Idempotency-Key": KEY}
BODY = {"customer_id": "cust-1001", "items": [{"sku": "SKU-TSHIRT-BLK-M", "quantity": 2}]}
ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


class Harness:
    def __init__(self) -> None:
        self.repository = FakeRepository()
        self.catalog = FakeCatalog(product("SKU-TSHIRT-BLK-M", "19.99"), product("SKU-MUG", "8.5"))
        self.stock = FakeStock({"SKU-TSHIRT-BLK-M": 10, "SKU-MUG": 10})
        self.client = TestClient(
            create_app(
                make_settings(),
                repository=self.repository,
                catalog=self.catalog,
                stock=self.stock,
            )
        )


@pytest.fixture
def h() -> Harness:
    return Harness()


def code(response: Any) -> str:
    return str(response.json()["error"]["code"])


# --- POST /orders -----------------------------------------------------------------------------


def test_create_returns_202_pending_with_the_documented_shape(h: Harness) -> None:
    response = h.client.post("/api/v1/orders", json=BODY, headers=HEADERS)

    assert response.status_code == 202
    body = response.json()
    assert ULID.match(body["order_id"])
    assert body["status"] == "PENDING"
    assert body["total_amount"] == "39.98"
    assert body["currency"] == "USD"
    assert body["items"] == [{"sku": "SKU-TSHIRT-BLK-M", "quantity": 2, "unit_price": "19.99"}]
    created_at = datetime.fromisoformat(body["created_at"])
    assert created_at.utcoffset() == timedelta(0)  # UTC
    assert abs(datetime.now(UTC) - created_at) < timedelta(minutes=1)
    assert response.headers["Location"] == f"/api/v1/orders/{body['order_id']}"


def test_money_is_always_a_two_decimal_string(h: Harness) -> None:
    body = h.client.post(
        "/api/v1/orders",
        json={"customer_id": "c", "items": [{"sku": "SKU-MUG", "quantity": 3}]},
        headers=HEADERS,
    ).json()

    assert body["items"][0]["unit_price"] == "8.50"  # 8.5 in the catalog, two decimals on the wire
    assert body["total_amount"] == "25.50"
    assert isinstance(body["total_amount"], str)


def test_replaying_the_same_key_and_body_returns_the_original_with_200(h: Harness) -> None:
    first = h.client.post("/api/v1/orders", json=BODY, headers=HEADERS)
    replay = h.client.post("/api/v1/orders", json=BODY, headers=HEADERS)

    assert (first.status_code, replay.status_code) == (202, 200)
    assert replay.json() == first.json()
    assert replay.headers["Location"] == first.headers["Location"]
    assert len(h.repository.outbox) == 1


def test_the_same_key_with_a_different_body_is_422(h: Harness) -> None:
    h.client.post("/api/v1/orders", json=BODY, headers=HEADERS)
    other = {**BODY, "items": [{"sku": "SKU-TSHIRT-BLK-M", "quantity": 3}]}

    response = h.client.post("/api/v1/orders", json=other, headers=HEADERS)

    assert response.status_code == 422
    assert code(response) == "IDEMPOTENCY_KEY_REUSED"


def test_out_of_stock_is_409_with_the_documented_message_and_no_order(h: Harness) -> None:
    h.stock.levels["SKU-TSHIRT-BLK-M"] = 1

    response = h.client.post(
        "/api/v1/orders", json=BODY, headers={**HEADERS, CORRELATION_HEADER: "c-1"}
    )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "OUT_OF_STOCK",
        "message": "SKU-TSHIRT-BLK-M: requested 2, available 1",
        "correlation_id": "c-1",
    }
    assert h.repository.orders == {}


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        (lambda h: h.catalog.products.pop("SKU-TSHIRT-BLK-M"), "UNKNOWN_PRODUCT"),
        (
            lambda h: h.catalog.products.update(
                {"SKU-TSHIRT-BLK-M": product("SKU-TSHIRT-BLK-M", active=False)}
            ),
            "PRODUCT_INACTIVE",
        ),
    ],
)
def test_products_that_cannot_be_ordered_are_422(h: Harness, setup: Any, expected: str) -> None:
    setup(h)
    response = h.client.post("/api/v1/orders", json=BODY, headers=HEADERS)
    assert response.status_code == 422
    assert code(response) == expected
    assert h.repository.orders == {}


def test_mixed_currencies_are_422(h: Harness) -> None:
    h.catalog.products["SKU-MUG"] = product("SKU-MUG", currency="EUR")
    body = {
        "customer_id": "c",
        "items": [{"sku": "SKU-TSHIRT-BLK-M", "quantity": 1}, {"sku": "SKU-MUG", "quantity": 1}],
    }

    response = h.client.post("/api/v1/orders", json=body, headers=HEADERS)

    assert response.status_code == 422
    assert code(response) == "MIXED_CURRENCY"


@pytest.mark.parametrize("dependency", ["catalog", "stock"])
def test_an_unreachable_service_is_a_503_with_retry_after_and_writes_nothing(
    h: Harness, dependency: str
) -> None:
    getattr(h, dependency).down = True

    response = h.client.post("/api/v1/orders", json=BODY, headers=HEADERS)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert code(response) == "UPSTREAM_UNAVAILABLE"
    assert (h.repository.orders, h.repository.outbox) == ({}, [])


def test_a_database_outage_is_a_503_not_a_500(h: Harness) -> None:
    h.repository.down = True
    response = h.client.post("/api/v1/orders", json=BODY, headers=HEADERS)
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert code(response) == "STORE_UNAVAILABLE"


# --- request validation -----------------------------------------------------------------------


def test_the_idempotency_key_header_is_required(h: Harness) -> None:
    response = h.client.post("/api/v1/orders", json=BODY)
    assert response.status_code == 422
    assert "Idempotency-Key" in response.json()["error"]["message"]
    assert h.repository.orders == {}


@pytest.mark.parametrize("key", ["", " ", "has space", "x" * 65, "semi;colon", 'quote"'])
def test_a_malformed_idempotency_key_is_rejected(h: Harness, key: str) -> None:
    response = h.client.post("/api/v1/orders", json=BODY, headers={"Idempotency-Key": key})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"customer_id": "c"},
        {"items": [{"sku": "SKU-MUG", "quantity": 1}]},
        {"customer_id": "c", "items": []},
        {"customer_id": "", "items": [{"sku": "SKU-MUG", "quantity": 1}]},
        {"customer_id": "bad id", "items": [{"sku": "SKU-MUG", "quantity": 1}]},
        {"customer_id": "c", "items": [{"sku": "SKU-MUG", "quantity": 1}] * 2},  # duplicate SKUs
        {"customer_id": "c", "items": [{"sku": f"S{i}", "quantity": 1} for i in range(21)]},
        {"customer_id": "c", "items": [{"sku": "SKU-MUG", "quantity": 0}]},
        {"customer_id": "c", "items": [{"sku": "SKU-MUG", "quantity": 101}]},
        {"customer_id": "c", "items": [{"sku": "SKU-MUG", "quantity": "2"}]},
        {"customer_id": "c", "items": [{"sku": "SKU-MUG", "quantity": 2.0}]},
        {"customer_id": "c", "items": [{"sku": "SKU-MUG", "quantity": True}]},
        {"customer_id": "c", "items": [{"sku": "bad sku", "quantity": 1}]},
        {"customer_id": "c", "items": [{"sku": "SKU-MUG", "quantity": 1, "unit_price": "0.01"}]},
        {"customer_id": "c", "items": [{"sku": "SKU-MUG", "quantity": 1}], "total_amount": "0.01"},
        [{"sku": "SKU-MUG", "quantity": 1}],
    ],
)
def test_invalid_bodies_are_422_and_never_reach_a_dependency(h: Harness, body: object) -> None:
    response = h.client.post("/api/v1/orders", json=body, headers=HEADERS)

    assert response.status_code == 422
    assert code(response) == "VALIDATION_ERROR"
    assert h.catalog.calls == []
    assert h.stock.calls == 0


def test_a_client_cannot_set_its_own_prices(h: Harness) -> None:
    """Prices come only from the product service; a body that tries to supply one is refused."""
    body = {"customer_id": "c", "items": [{"sku": "SKU-MUG", "quantity": 1, "unit_price": "0.01"}]}
    assert h.client.post("/api/v1/orders", json=body, headers=HEADERS).status_code == 422


def test_exactly_twenty_lines_are_accepted() -> None:
    skus = [f"SKU-{n:02d}" for n in range(20)]
    h = Harness()
    h.catalog = FakeCatalog(*(product(sku) for sku in skus))
    h.stock = FakeStock({sku: 5 for sku in skus})
    client = TestClient(
        create_app(make_settings(), repository=h.repository, catalog=h.catalog, stock=h.stock)
    )
    body = {"customer_id": "c", "items": [{"sku": sku, "quantity": 1} for sku in skus]}

    assert client.post("/api/v1/orders", json=body, headers=HEADERS).status_code == 202


# --- reads ------------------------------------------------------------------------------------


def test_get_order(h: Harness) -> None:
    created = h.client.post("/api/v1/orders", json=BODY, headers=HEADERS).json()

    response = h.client.get(f"/api/v1/orders/{created['order_id']}")

    assert response.status_code == 200
    assert response.json() == created
    assert response.json()["customer_id"] == "cust-1001"


def test_unknown_order_is_404(h: Harness) -> None:
    response = h.client.get("/api/v1/orders/01J9Z6Q4W8K3M2N1P0R7S5T4V3")
    assert response.status_code == 404
    assert code(response) == "ORDER_NOT_FOUND"


def test_a_malformed_order_id_is_422_not_a_database_lookup(h: Harness) -> None:
    assert h.client.get("/api/v1/orders/not-a-ulid").status_code == 422


def test_list_orders_for_a_customer(h: Harness) -> None:
    for n in range(3):
        h.client.post("/api/v1/orders", json=BODY, headers={"Idempotency-Key": f"key-{n}"})
    h.client.post(
        "/api/v1/orders",
        json={**BODY, "customer_id": "someone-else"},
        headers={"Idempotency-Key": "k"},
    )

    body = h.client.get("/api/v1/orders?customer_id=cust-1001&size=2").json()

    assert (body["total"], body["page"], body["size"]) == (3, 1, 2)
    assert len(body["items"]) == 2
    assert {o["customer_id"] for o in body["items"]} == {"cust-1001"}


@pytest.mark.parametrize(
    "query",
    [
        "",
        "customer_id=",
        "customer_id=a&page=0",
        "customer_id=a&size=0",
        "customer_id=a&size=101",
        "customer_id=bad%20id",
    ],
)
def test_list_requires_a_valid_customer_and_sane_paging(h: Harness, query: str) -> None:
    assert h.client.get(f"/api/v1/orders?{query}").status_code == 422


# --- structure and observability --------------------------------------------------------------


def test_metrics_use_route_templates_so_order_ids_never_become_labels(h: Harness) -> None:
    created = h.client.post("/api/v1/orders", json=BODY, headers=HEADERS).json()
    h.client.get(f"/api/v1/orders/{created['order_id']}")

    text = h.client.get("/metrics").text
    assert 'route="/api/v1/orders/{order_id}"' in text
    assert created["order_id"] not in text


def test_openapi_documents_every_endpoint(h: Harness) -> None:
    paths = h.client.get("/openapi.json").json()["paths"]
    assert set(paths["/api/v1/orders"]) == {"get", "post"}
    assert set(paths["/api/v1/orders/{order_id}"]) == {"get"}


def test_readiness_follows_postgres_and_liveness_never_does() -> None:
    def down() -> None:
        raise ConnectionError("db down")

    unready = TestClient(
        create_app(
            make_settings(),
            repository=FakeRepository(),
            catalog=FakeCatalog(),
            stock=FakeStock(),
            readiness_probes=(ReadinessCheck("postgres", down),),
        )
    )
    assert unready.get("/health/ready").status_code == 503
    assert unready.get("/health/live").status_code == 200


def test_the_request_handlers_can_never_publish_an_event() -> None:
    """CLAUDE.md: never call PutEvents from a request handler. Outside the relay package there is
    no event-bus code at all; events leave only through the outbox. The consumer package may
    import boto3 (it reads an SQS queue) but still may not publish."""
    app_dir = Path(__file__).resolve().parents[2] / "app"
    publishing = re.compile(r"put_events|EventBridgePublisher")
    aws_import = re.compile(r"^\s*(import|from)\s+(boto3|botocore)", re.MULTILINE)
    offenders = []
    for path in app_dir.rglob("*.py"):
        parts = path.relative_to(app_dir).parts
        if "relay" in parts:
            continue
        text = path.read_text()
        if publishing.search(text) or ("consumer" not in parts and aws_import.search(text)):
            offenders.append(str(path.relative_to(app_dir)))
    assert offenders == []


def test_order_lines_are_value_objects() -> None:
    assert OrderLine("A", 1) == OrderLine("A", 1)
