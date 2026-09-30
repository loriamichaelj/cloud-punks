import pytest
from pydantic import ValidationError

from retail_common.config import AwsSettings, BaseServiceSettings


def test_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "order-service")
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("HTTP_TIMEOUT_READ_S", "3.5")

    settings = BaseServiceSettings()

    assert settings.service_name == "order-service"
    assert settings.environment == "dev"
    assert settings.log_level == "WARNING"
    assert settings.http_timeout_read_s == 3.5
    assert settings.http_timeout_connect_s == 1.0  # documented default


def test_service_name_is_required() -> None:
    with pytest.raises(ValidationError, match="service_name"):
        BaseServiceSettings()


def test_log_level_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "x")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert BaseServiceSettings().log_level == "DEBUG"


def test_unknown_log_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "x")
    monkeypatch.setenv("LOG_LEVEL", "CHATTY")
    with pytest.raises(ValidationError, match="log_level"):
        BaseServiceSettings()


def test_timeouts_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "x")
    monkeypatch.setenv("HTTP_TIMEOUT_CONNECT_S", "0")
    with pytest.raises(ValidationError, match="http_timeout_connect_s"):
        BaseServiceSettings()


def test_unrelated_environment_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "x")
    monkeypatch.setenv("DB_HOST", "postgres")  # belongs to a service-specific subclass
    assert BaseServiceSettings().service_name == "x"


def test_settings_are_immutable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "x")
    settings = BaseServiceSettings()
    with pytest.raises(ValidationError, match="frozen"):
        settings.service_name = "y"  # type: ignore[misc]


def test_aws_settings_require_a_region(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "x")
    with pytest.raises(ValidationError, match="aws_region"):
        AwsSettings()
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    assert AwsSettings().aws_region == "us-east-1"
