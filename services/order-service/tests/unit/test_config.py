import pytest
from pydantic import ValidationError

from app.config import DatabaseSettings, RelaySettings, Settings

DB = {"DB_HOST": "postgres", "DB_NAME": "order_db", "DB_USER": "order_app", "DB_PASSWORD": "s3cret"}
URLS = {
    "PRODUCT_SERVICE_URL": "http://product-service:8001",
    "INVENTORY_SERVICE_URL": "http://inventory-service:8002",
}
AWS = {"AWS_REGION": "us-east-1", "EVENT_BUS_NAME": "retail-events"}
ALL = [*DB, *URLS, *AWS, "DB_PORT", "DB_SSLMODE", "SERVICE_NAME", "ENVIRONMENT"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ALL:
        monkeypatch.delenv(name, raising=False)


def env(monkeypatch: pytest.MonkeyPatch, *groups: dict[str, str]) -> None:
    for group in groups:
        for name, value in group.items():
            monkeypatch.setenv(name, value)


def test_the_migrate_job_needs_only_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    env(monkeypatch, DB)
    assert DatabaseSettings().service_name == "order-service"  # type: ignore[call-arg]


def test_the_api_needs_the_database_and_both_upstream_urls_but_no_aws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env(monkeypatch, DB, URLS)  # no AWS_REGION, no EVENT_BUS_NAME: the API never touches the bus
    settings = Settings()  # type: ignore[call-arg]
    assert settings.product_service_url == "http://product-service:8001"
    assert not hasattr(settings, "event_bus_name")
    assert not hasattr(settings, "aws_region")


@pytest.mark.parametrize("missing", list(URLS))
def test_the_api_fails_fast_without_an_upstream_url(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    env(monkeypatch, DB, URLS)
    monkeypatch.delenv(missing)
    with pytest.raises(ValidationError, match=missing.lower()):
        Settings()  # type: ignore[call-arg]


def test_the_relay_needs_the_database_and_aws_but_not_the_upstream_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env(monkeypatch, DB, AWS)
    settings = RelaySettings()  # type: ignore[call-arg]
    assert (settings.aws_region, settings.event_bus_name) == ("us-east-1", "retail-events")
    assert not hasattr(settings, "product_service_url")


@pytest.mark.parametrize("missing", list(AWS))
def test_the_relay_fails_fast_without_aws_settings(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    env(monkeypatch, DB, AWS)
    monkeypatch.delenv(missing)
    with pytest.raises(ValidationError, match=missing.lower()):
        RelaySettings()  # type: ignore[call-arg]


def test_the_password_never_appears_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    env(monkeypatch, DB, URLS)
    assert "s3cret" not in repr(Settings())  # type: ignore[call-arg]
