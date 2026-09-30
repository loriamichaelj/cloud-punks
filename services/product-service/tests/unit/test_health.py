from fastapi.testclient import TestClient

from app.main import app
from retail_common.logging import CORRELATION_HEADER

client = TestClient(app)


def test_live_returns_200() -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_is_200_while_the_service_has_no_required_stores() -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_metrics_are_exposed_with_route_templates() -> None:
    client.get("/health/live")
    body = client.get("/metrics").text
    assert 'http_requests_total{method="GET",route="/health/live",status="200"}' in body


def test_a_correlation_id_is_echoed_and_the_service_name_is_its_own() -> None:
    response = client.get("/health/live", headers={CORRELATION_HEADER: "corr-1"})
    assert response.headers[CORRELATION_HEADER] == "corr-1"
    assert app.title == "product-service"
