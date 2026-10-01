import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import InterfaceError, OperationalError, ProgrammingError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from retail_common.database import (
    STORE_ERRORS,
    DatabaseSettings,
    build_engine,
    database_url,
    ping,
)

DB = {"DB_HOST": "postgres", "DB_NAME": "order_db", "DB_USER": "order_app", "DB_PASSWORD": "s3cret"}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*DB, "DB_PORT", "DB_SSLMODE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SERVICE_NAME", "order-service")


def with_db(monkeypatch: pytest.MonkeyPatch, **extra: str) -> DatabaseSettings:
    for name, value in {**DB, **extra}.items():
        monkeypatch.setenv(name, value)
    return DatabaseSettings()


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = with_db(monkeypatch)
    assert (settings.db_port, settings.db_sslmode) == (5432, "disable")


@pytest.mark.parametrize("missing", ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"])
def test_each_variable_is_required(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    for name, value in DB.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(missing)
    with pytest.raises(ValidationError, match=missing.lower()):
        DatabaseSettings()


@pytest.mark.parametrize(
    ("name", "value"), [("DB_SSLMODE", "maybe"), ("DB_PORT", "0"), ("DB_PORT", "70000")]
)
def test_invalid_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    with pytest.raises(ValidationError):
        with_db(monkeypatch, **{name: value})


def test_the_password_never_appears_in_repr_or_dumps(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = with_db(monkeypatch)
    assert "s3cret" not in repr(settings)
    assert "s3cret" not in settings.model_dump_json()


def test_the_url_is_built_from_parts_so_special_characters_are_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = database_url(with_db(monkeypatch, DB_PASSWORD="p@ss:w/rd%#", DB_SSLMODE="verify-full"))

    assert url.drivername == "postgresql+psycopg"
    assert url.password == "p@ss:w/rd%#"
    assert url.query["sslmode"] == "verify-full"
    assert "p@ss" not in str(url)  # str() masks the password


def test_the_engine_uses_the_documented_pool_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = build_engine(with_db(monkeypatch))
    try:
        assert engine.pool.size() == 5  # type: ignore[attr-defined]
        assert engine.pool._max_overflow == 5  # type: ignore[attr-defined]
        assert engine.pool._pre_ping is True  # type: ignore[attr-defined]
        assert engine.pool._recycle == 1800  # type: ignore[attr-defined]
    finally:
        engine.dispose()  # building an engine opens no connection


def test_ping_runs_select_1() -> None:
    engine = create_engine("sqlite://")
    ping(engine)  # raises if the database cannot answer
    engine.dispose()


def test_ping_raises_when_the_database_cannot_be_reached() -> None:
    engine = create_engine(
        "postgresql+psycopg://u:p@127.0.0.1:1/x", connect_args={"connect_timeout": 1}
    )
    with pytest.raises(OperationalError):
        ping(engine)
    engine.dispose()


def test_store_errors_cover_outages_but_not_bugs() -> None:
    assert issubclass(OperationalError, STORE_ERRORS)
    assert issubclass(InterfaceError, STORE_ERRORS)
    assert issubclass(PoolTimeoutError, STORE_ERRORS)
    assert not issubclass(ProgrammingError, STORE_ERRORS)  # bad SQL is a bug, not an outage
