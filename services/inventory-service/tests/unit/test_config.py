import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AWS_REGION", "SERVICE_NAME", "ENVIRONMENT", "AWS_ENDPOINT_URL"):
        monkeypatch.delenv(name, raising=False)


def test_settings_read_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    settings = Settings()  # type: ignore[call-arg]
    assert (settings.service_name, settings.aws_region) == ("inventory-service", "eu-west-1")


def test_the_region_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="aws_region"):
        Settings()  # type: ignore[call-arg]


def test_the_aws_endpoint_is_deliberately_not_a_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    """boto3 reads AWS_ENDPOINT_URL itself, so no code path differs between LocalStack and AWS."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://localstack:4566")
    assert not hasattr(Settings(), "aws_endpoint_url")  # type: ignore[call-arg]


def test_table_names_default_to_the_local_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    settings = Settings()  # type: ignore[call-arg]
    assert (settings.inventory_table, settings.reservations_table) == (
        "inventory",
        "inventory_reservations",
    )


def test_table_names_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("INVENTORY_TABLE", "loria-inventory")
    monkeypatch.setenv("RESERVATIONS_TABLE", "loria-inventory-reservations")
    settings = Settings()  # type: ignore[call-arg]
    assert (settings.inventory_table, settings.reservations_table) == (
        "loria-inventory",
        "loria-inventory-reservations",
    )
