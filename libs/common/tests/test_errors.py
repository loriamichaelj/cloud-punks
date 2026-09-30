from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from retail_common.config import BaseServiceSettings
from retail_common.errors import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    UpstreamUnavailableError,
)
from retail_common.logging import CORRELATION_HEADER
from retail_common.service import create_service_app


class Payload(BaseModel):
    quantity: int = Field(ge=1)
    card_number: str = Field(min_length=20)


def build_client(settings: BaseServiceSettings) -> TestClient:
    app = create_service_app(settings)

    @app.get("/missing")
    def missing() -> None:
        raise NotFoundError("order 01J... not found")

    @app.get("/conflict")
    def conflict() -> None:
        raise ConflictError("already exists", code="OUT_OF_STOCK")

    @app.get("/down")
    def down() -> None:
        raise ServiceUnavailableError("try later", retry_after_s=7)

    @app.get("/upstream")
    def upstream() -> None:
        raise UpstreamUnavailableError("product-service is unavailable")

    @app.post("/validate")
    def validate(payload: Payload) -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/crash")
    def crash() -> None:
        raise RuntimeError("password=hunter2 connection refused at 10.0.0.5")

    return TestClient(app, raise_server_exceptions=False)


def test_app_error_uses_the_documented_error_shape(settings: BaseServiceSettings) -> None:
    response = build_client(settings).get("/missing", headers={CORRELATION_HEADER: "corr-1"})

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "order 01J... not found",
            "correlation_id": "corr-1",
        }
    }


def test_error_code_can_be_overridden_per_raise(settings: BaseServiceSettings) -> None:
    response = build_client(settings).get("/conflict")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OUT_OF_STOCK"


def test_service_unavailable_sets_retry_after(settings: BaseServiceSettings) -> None:
    response = build_client(settings).get("/down")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "7"
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_upstream_failure_is_a_503_with_its_own_code(settings: BaseServiceSettings) -> None:
    response = build_client(settings).get("/upstream")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"


def test_validation_error_reports_fields_but_never_echoes_input(
    settings: BaseServiceSettings,
) -> None:
    response = build_client(settings).post(
        "/validate", json={"quantity": 0, "card_number": "4111-SECRET"}
    )

    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "quantity" in body["error"]["message"]
    assert "card_number" in body["error"]["message"]
    assert "4111-SECRET" not in response.text


def test_unknown_route_uses_the_error_shape(settings: BaseServiceSettings) -> None:
    response = build_client(settings).get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_wrong_method_uses_the_error_shape(settings: BaseServiceSettings) -> None:
    response = build_client(settings).post("/missing")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_unexpected_exception_is_a_generic_500_that_leaks_nothing(
    settings: BaseServiceSettings,
) -> None:
    response = build_client(settings).get("/crash")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in response.text
    assert "10.0.0.5" not in response.text


def test_500_response_still_carries_the_correlation_id(settings: BaseServiceSettings) -> None:
    """The last-resort handler runs outside the middleware; the id must survive that."""
    response = build_client(settings).get("/crash", headers={CORRELATION_HEADER: "corr-500"})

    assert response.status_code == 500
    assert response.json()["error"]["correlation_id"] == "corr-500"
    assert response.headers[CORRELATION_HEADER] == "corr-500"
