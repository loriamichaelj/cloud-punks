from fakes import FakeRepository, make_settings
from fastapi.testclient import TestClient

from app.main import create_app
from retail_common.logging import CORRELATION_HEADER

app = create_app(make_settings(), repository=FakeRepository())
client = TestClient(app)


def test_live_returns_200() -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_a_correlation_id_is_echoed_and_the_service_name_is_its_own() -> None:
    response = client.get("/health/live", headers={CORRELATION_HEADER: "corr-1"})
    assert response.headers[CORRELATION_HEADER] == "corr-1"
    assert app.title == "inventory-service"
