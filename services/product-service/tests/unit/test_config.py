import pytest
from pydantic import ValidationError

from app.config import DatabaseSettings, Settings
from app.repo.db import database_url

DB = {
    "DB_HOST": "postgres",
    "DB_NAME": "product_db",
    "DB_USER": "product_app",
    "DB_PASSWORD": "s3cret",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [*DB, "DB_PORT", "DB_SSLMODE", "CACHE_URL", "SERVICE_NAME", "ENVIRONMENT"]:
        monkeypatch.delenv(name, raising=False)


def set_env(monkeypatch: pytest.MonkeyPatch, **extra: str) -> None:
    for name, value in {**DB, **extra}.items():
        monkeypatch.setenv(name, value)


def test_settings_read_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, CACHE_URL="redis://valkey:6379/0")

    settings = Settings()  # type: ignore[call-arg]

    assert settings.service_name == "product-service"
    assert (settings.db_host, settings.db_port, settings.db_name) == (
        "postgres",
        5432,
        "product_db",
    )
    assert settings.db_sslmode == "disable"
    assert settings.cache_url == "redis://valkey:6379/0"


def test_the_service_needs_a_cache_url_but_the_migrate_job_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_env(monkeypatch)

    DatabaseSettings()  # type: ignore[call-arg]  # no CACHE_URL needed
    with pytest.raises(ValidationError, match="cache_url"):
        Settings()  # type: ignore[call-arg]


@pytest.mark.parametrize("missing", ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"])
def test_each_database_variable_is_required(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    set_env(monkeypatch)
    monkeypatch.delenv(missing)
    with pytest.raises(ValidationError, match=missing.lower()):
        DatabaseSettings()  # type: ignore[call-arg]


def test_the_password_never_appears_in_repr_or_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch)
    settings = DatabaseSettings()  # type: ignore[call-arg]
    assert "s3cret" not in repr(settings)
    assert "s3cret" not in str(settings)
    assert "s3cret" not in settings.model_dump_json()


def test_an_unknown_sslmode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, DB_SSLMODE="maybe")
    with pytest.raises(ValidationError, match="db_sslmode"):
        DatabaseSettings()  # type: ignore[call-arg]


def test_the_database_url_is_built_from_parts_so_special_characters_are_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_env(monkeypatch, DB_PASSWORD="p@ss:w/rd%#", DB_SSLMODE="verify-full", DB_PORT="6543")

    url = database_url(DatabaseSettings())  # type: ignore[call-arg]

    assert url.drivername == "postgresql+psycopg"
    assert url.password == "p@ss:w/rd%#"
    assert (url.host, url.port, url.database) == ("postgres", 6543, "product_db")
    assert url.query["sslmode"] == "verify-full"
    assert "p@ss" not in str(url)  # str() masks the password
