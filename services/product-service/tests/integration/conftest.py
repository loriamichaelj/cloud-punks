"""Integration fixtures: the service in-process against the real Compose PostgreSQL and Valkey.

Run with ``make itest`` (the stack must be up; the Makefile loads .env for the passwords).
Everything created here is prefixed ``ITEST-`` / ``itest-`` and removed afterwards, and Valkey
database 15 is used so a developer's cache in database 0 is never touched.
"""

import os
import socket
import threading
import uuid
from collections.abc import Iterator
from contextlib import suppress

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from app.config import DatabaseSettings, Settings
from app.main import create_app
from app.migrate import run_migrations
from retail_common.database import build_engine

PG_HOST = "localhost"
VALKEY_HOST = "localhost"
VALKEY_PORT = 6379
TEST_VALKEY_DB = 15
UP_URL = f"redis://{VALKEY_HOST}:{VALKEY_PORT}/{TEST_VALKEY_DB}"
DOWN_URL = "redis://127.0.0.1:1/0"  # nothing listens on port 1: connection refused
CATEGORY = "itest-cat"


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.exit(f"{name} is not set; run `make itest` (it loads .env)", returncode=2)
    return value


def _settings(cache_url: str, *, owner: bool = False) -> Settings:
    user, password = (
        ("product_owner", _env("PRODUCT_OWNER_PASSWORD"))
        if owner
        else ("product_app", _env("PRODUCT_APP_PASSWORD"))
    )
    return Settings(
        db_host=PG_HOST,
        db_name="product_db",
        db_user=user,
        db_password=password,  # type: ignore[arg-type]
        cache_url=cache_url,
    )


@pytest.fixture(scope="session")
def owner_settings() -> DatabaseSettings:
    return _settings(UP_URL, owner=True)


@pytest.fixture(scope="session", autouse=True)
def migrated(owner_settings: DatabaseSettings) -> None:
    """Apply migrations through the same code path as the `migrate` command."""
    try:
        run_migrations(owner_settings)
    except OperationalError as exc:
        pytest.exit(f"PostgreSQL is not reachable on {PG_HOST}:5432: run `make up` ({exc.orig})")


@pytest.fixture(scope="session")
def engine(migrated: None) -> Iterator[Engine]:
    """The application role's engine, used for setup, cleanup and direct SQL."""
    engine = build_engine(_settings(UP_URL))
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def valkey() -> Iterator[Redis]:
    client: Redis = Redis.from_url(UP_URL, decode_responses=True, socket_connect_timeout=1)
    assert client.connection_pool.connection_kwargs["db"] == TEST_VALKEY_DB  # never flush db 0
    try:
        client.ping()
    except RedisError as exc:
        pytest.exit(
            f"Valkey is not reachable on {VALKEY_HOST}:{VALKEY_PORT}: run `make up` ({exc})"
        )
    yield client
    client.close()


@pytest.fixture(scope="session")
def category(engine: Engine) -> Iterator[str]:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO categories (slug, name) VALUES (:s, 'Integration Test') "
                "ON CONFLICT (slug) DO NOTHING"
            ),
            {"s": CATEGORY},
        )
    yield CATEGORY
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM products WHERE sku LIKE 'ITEST-%'"))
        connection.execute(text("DELETE FROM categories WHERE slug LIKE 'itest-%'"))


@pytest.fixture(autouse=True)
def _clean(engine: Engine, valkey: Redis, category: str) -> Iterator[None]:
    def wipe() -> None:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM products WHERE sku LIKE 'ITEST-%'"))
        valkey.flushdb()

    wipe()
    yield
    wipe()


@pytest.fixture
def sku() -> str:
    return f"ITEST-{uuid.uuid4().hex[:10]}"


def make_client(cache_url: str) -> Iterator[TestClient]:
    with TestClient(create_app(_settings(cache_url))) as client:
        yield client


@pytest.fixture(params=["cache-up", "cache-down"])
def cache_mode(request: pytest.FixtureRequest) -> str:
    return str(request.param).removeprefix("cache-")


@pytest.fixture
def client(cache_mode: str) -> Iterator[TestClient]:
    """The service with Valkey up and then down: the same tests must pass in both."""
    yield from make_client(UP_URL if cache_mode == "up" else DOWN_URL)


@pytest.fixture
def up_client() -> Iterator[TestClient]:
    yield from make_client(UP_URL)


def sample(client: TestClient, name: str, **labels: str) -> float:
    return client.app.state.registry.get_sample_value(name, labels) or 0.0  # type: ignore[attr-defined,no-any-return]


class TcpProxy:
    """A TCP proxy in front of Valkey that can die, come back, or accept and never answer."""

    def __init__(self, target_host: str, target_port: int) -> None:
        self._target = (target_host, target_port)
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self.port = probe.getsockname()[1]
        probe.close()
        self._listener: socket.socket | None = None
        self._connections: list[socket.socket] = []

    @property
    def url(self) -> str:
        return f"redis://127.0.0.1:{self.port}/{TEST_VALKEY_DB}"

    def start(self, *, hang: bool = False) -> None:
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", self.port))
        listener.listen()
        self._listener = listener
        threading.Thread(target=self._accept, args=(listener, hang), daemon=True).start()

    def _accept(self, listener: socket.socket, hang: bool) -> None:
        while True:
            try:
                downstream, _ = listener.accept()
            except OSError:
                return
            self._connections.append(downstream)
            if hang:
                continue  # accepted, but never read or answered
            upstream = socket.create_connection(self._target)
            self._connections.append(upstream)
            for source, sink in ((downstream, upstream), (upstream, downstream)):
                threading.Thread(target=self._pump, args=(source, sink), daemon=True).start()

    @staticmethod
    def _pump(source: socket.socket, sink: socket.socket) -> None:
        with suppress(OSError):
            while data := source.recv(65536):
                sink.sendall(data)
        for sock in (source, sink):
            with suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        for connection in self._connections:
            with suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)
            connection.close()
        self._connections.clear()


@pytest.fixture
def proxy() -> Iterator[TcpProxy]:
    proxy = TcpProxy(VALKEY_HOST, VALKEY_PORT)
    proxy.start()
    yield proxy
    proxy.stop()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(pytest.mark.integration)
