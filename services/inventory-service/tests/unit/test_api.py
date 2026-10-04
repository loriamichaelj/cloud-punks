from typing import Any

import pytest
from fakes import FakeRepository, make_item, make_settings
from fastapi.testclient import TestClient

from app.main import create_app
from retail_common.health import ReadinessCheck
from retail_common.logging import CORRELATION_HEADER


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository(make_item("SKU-A", 10, reserved=2), make_item("SKU-B", 1))


@pytest.fixture
def client(repository: FakeRepository) -> TestClient:
    return TestClient(create_app(make_settings(), repository=repository))


def code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def check(client: TestClient, *lines: tuple[str, object]) -> Any:
    return client.post(
        "/api/v1/inventory/availability",
        json={"items": [{"sku": sku, "quantity": quantity} for sku, quantity in lines]},
    )


# --- GET ------------------------------------------------------------------------------------


def test_get_stock(client: TestClient) -> None:
    response = client.get("/api/v1/inventory/SKU-A")

    assert response.status_code == 200
    body = response.json()
    assert (body["sku"], body["available"], body["reserved"]) == ("SKU-A", 10, 2)
    assert body["updated_at"].startswith("2026-10-01T12:00:00")


def test_the_owner_is_null_while_the_platform_holds_it_and_named_once_sold(
    client: TestClient, repository: FakeRepository
) -> None:
    assert client.get("/api/v1/inventory/SKU-A").json()["owner"] is None
    repository.items["CP-0001"] = make_item("CP-0001", 0, reserved=1, owner="cust-7")

    assert client.get("/api/v1/inventory/CP-0001").json()["owner"] == "cust-7"
    (line,) = check(client, ("CP-0001", 1)).json()["items"]
    assert (line["owner"], line["sufficient"], line["reason"]) == ("cust-7", False, "OUT_OF_STOCK")


def test_unknown_sku_is_404_in_the_shared_error_shape(client: TestClient) -> None:
    response = client.get("/api/v1/inventory/NOPE", headers={CORRELATION_HEADER: "corr-1"})

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "INVENTORY_NOT_FOUND",
        "message": "no inventory record for 'NOPE'",
        "correlation_id": "corr-1",
    }


@pytest.mark.parametrize("path", ["/api/v1/inventory/SKU-A", "/api/v1/inventory/NOPE"])
def test_stock_responses_forbid_caching_by_anything_in_between(
    client: TestClient, path: str
) -> None:
    assert client.get(path).headers["Cache-Control"] == "no-store"


def test_every_read_reaches_the_repository(client: TestClient, repository: FakeRepository) -> None:
    client.get("/api/v1/inventory/SKU-A")
    client.get("/api/v1/inventory/SKU-A")
    assert repository.calls == ["get:SKU-A", "get:SKU-A"]


# --- availability -----------------------------------------------------------------------------


def test_availability_when_everything_is_in_stock(client: TestClient) -> None:
    response = check(client, ("SKU-A", 2), ("SKU-B", 1))

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "available": True,
        "items": [
            {
                "sku": "SKU-A",
                "requested": 2,
                "available": 10,
                "sufficient": True,
                "reason": None,
                "owner": None,
            },
            {
                "sku": "SKU-B",
                "requested": 1,
                "available": 1,
                "sufficient": True,
                "reason": None,
                "owner": None,
            },
        ],
    }


def test_availability_names_the_failing_lines(client: TestClient) -> None:
    body = check(client, ("SKU-A", 2), ("SKU-B", 5), ("SKU-NOPE", 1)).json()

    assert body["available"] is False
    assert [(i["sku"], i["reason"]) for i in body["items"]] == [
        ("SKU-A", None),
        ("SKU-B", "OUT_OF_STOCK"),
        ("SKU-NOPE", "UNKNOWN_SKU"),
    ]
    assert body["items"][1]["available"] == 1  # the caller can say "requested 5, available 1"


def test_the_batch_endpoint_name_is_reserved_and_never_treated_as_an_sku(
    client: TestClient, repository: FakeRepository
) -> None:
    for method, kwargs in (("GET", {}), ("PUT", {"json": {"available": 5}})):
        response = client.request(method, "/api/v1/inventory/availability", **kwargs)
        assert response.status_code == 422
        assert "reserved" in response.json()["error"]["message"]
    assert repository.items.keys() == {"SKU-A", "SKU-B"}  # nothing was created
    assert check(client, ("availability", 1)).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"items": []},
        {"items": [{"sku": "A", "quantity": 1}] * 2},  # duplicate SKUs
        {"items": [{"sku": f"S{i}", "quantity": 1} for i in range(21)]},  # over the 20-line cap
        {"items": [{"sku": "A", "quantity": 0}]},
        {"items": [{"sku": "A", "quantity": 101}]},
        {"items": [{"sku": "A", "quantity": "2"}]},  # strings are not quantities
        {"items": [{"sku": "A", "quantity": 2.0}]},  # nor are floats
        {"items": [{"sku": "A", "quantity": True}]},  # nor booleans
        {"items": [{"sku": "bad sku", "quantity": 1}]},
        {"items": [{"sku": "A", "quantity": 1, "extra": 1}]},
        {"items": [{"sku": "A", "quantity": 1}], "extra": 1},
        [{"sku": "A", "quantity": 1}],  # a bare array is not the contract
    ],
)
def test_invalid_availability_requests_are_422(client: TestClient, body: object) -> None:
    response = client.post("/api/v1/inventory/availability", json=body)
    assert response.status_code == 422
    assert code(response) == "VALIDATION_ERROR"


def test_exactly_twenty_distinct_lines_are_accepted(client: TestClient) -> None:
    lines = tuple((f"SKU-{i}", 1) for i in range(20))
    assert check(client, *lines).status_code == 200


# --- PUT --------------------------------------------------------------------------------------


def test_put_sets_available_and_keeps_reserved(client: TestClient) -> None:
    response = client.put("/api/v1/inventory/SKU-A", json={"available": 40})

    assert response.status_code == 200
    body = response.json()
    assert (body["available"], body["reserved"]) == (40, 2)
    assert client.get("/api/v1/inventory/SKU-A").json()["available"] == 40


def test_put_keeps_the_owner_unless_told_to_hand_it_back_to_the_platform(
    client: TestClient, repository: FakeRepository
) -> None:
    repository.items["CP-0001"] = make_item("CP-0001", 0, reserved=1, owner="cust-7")

    assert (
        client.put("/api/v1/inventory/CP-0001", json={"available": 0}).json()["owner"] == "cust-7"
    )
    reset = client.put("/api/v1/inventory/CP-0001", json={"available": 1, "reset_owner": True})

    assert reset.status_code == 200
    assert (reset.json()["available"], reset.json()["owner"]) == (1, None)


def test_put_creates_a_record_for_a_new_sku(client: TestClient) -> None:
    response = client.put("/api/v1/inventory/SKU-NEW", json={"available": 5})
    assert response.status_code == 200
    assert (response.json()["available"], response.json()["reserved"]) == (5, 0)


def test_put_accepts_zero_to_take_a_product_out_of_stock(client: TestClient) -> None:
    assert client.put("/api/v1/inventory/SKU-A", json={"available": 0}).json()["available"] == 0


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"available": -1},
        {"available": 1_000_001},
        {"available": "5"},
        {"available": 5.5},
        {"available": 5.0},
        {"available": True},
        {"available": None},
        {"available": 5, "reserved": 0},  # reserved is owned by reservations, never set by hand
        {"available": 5, "sku": "OTHER"},
        {"available": 5, "owner": "cust-1"},  # ownership moves only by a sale
        {"available": 5, "reset_owner": "yes"},
        {"available": 5, "reset_owner": 1},
    ],
)
def test_invalid_put_bodies_are_422(client: TestClient, body: dict[str, object]) -> None:
    response = client.put("/api/v1/inventory/SKU-A", json=body)
    assert response.status_code == 422
    assert client.get("/api/v1/inventory/SKU-A").json()["available"] == 10  # nothing changed


def test_a_bad_sku_in_the_path_is_422(client: TestClient) -> None:
    assert client.put("/api/v1/inventory/bad%20sku", json={"available": 1}).status_code == 422


# --- outage, readiness, observability ---------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/inventory/SKU-A", None),
        ("POST", "/api/v1/inventory/availability", {"items": [{"sku": "SKU-A", "quantity": 1}]}),
        ("PUT", "/api/v1/inventory/SKU-A", {"available": 3}),
    ],
)
def test_a_store_outage_is_a_503_with_retry_after_never_a_500(
    repository: FakeRepository, method: str, path: str, body: object
) -> None:
    repository.down = True
    client = TestClient(create_app(make_settings(), repository=repository))

    response = client.request(method, path, json=body, headers={CORRELATION_HEADER: "corr-down"})

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.json()["error"] == {
        "code": "STORE_UNAVAILABLE",
        "message": "the inventory store is temporarily unavailable",
        "correlation_id": "corr-down",
    }


def test_readiness_follows_dynamodb_and_liveness_never_does(repository: FakeRepository) -> None:
    def down() -> None:
        raise ConnectionError("dynamodb down")

    def build(probe: object) -> TestClient:
        probes = (ReadinessCheck("dynamodb", probe),)  # type: ignore[arg-type]
        return TestClient(
            create_app(make_settings(), repository=repository, readiness_probes=probes)
        )

    assert build(lambda: None).get("/health/ready").status_code == 200
    unready = build(down)
    assert unready.get("/health/ready").status_code == 503
    assert unready.get("/health/live").status_code == 200


def test_metrics_use_route_templates(client: TestClient) -> None:
    client.get("/api/v1/inventory/SKU-A")
    client.get("/api/v1/inventory/SKU-B")

    text = client.get("/metrics").text
    assert 'route="/api/v1/inventory/{sku}"' in text
    assert "SKU-A" not in text


def test_openapi_documents_every_endpoint(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert set(paths["/api/v1/inventory/{sku}"]) == {"get", "put"}
    assert set(paths["/api/v1/inventory/availability"]) == {"post"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/inventory/NOPE", None),  # a 404 must not be cached either
        ("POST", "/api/v1/inventory/availability", {"items": []}),  # nor a 422
        ("PUT", "/api/v1/inventory/SKU-A", {"available": -1}),
    ],
)
def test_error_responses_are_no_store_too(
    client: TestClient, method: str, path: str, body: object
) -> None:
    response = client.request(method, path, json=body)
    assert response.status_code >= 400
    assert response.headers["Cache-Control"] == "no-store"


def test_endpoints_outside_the_inventory_prefix_are_not_marked(client: TestClient) -> None:
    assert "Cache-Control" not in client.get("/health/live").headers
