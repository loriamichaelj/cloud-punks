"""Integration fixtures: the order service against the real Compose PostgreSQL and LocalStack.

Run with ``make itest`` (the stack must be up; the Makefile loads .env and pauses the real
``order-relay`` container, because relay tests need exclusive ownership of the outbox).

Everything created here belongs to customers named ``itest-*`` and is removed afterwards. The two
HTTP dependencies (product and inventory services) are replaced by in-process fakes: this suite is
about the order service and its own stores, not about the other services.

Safety: the AWS environment is forced to LocalStack with dummy credentials before any client is
built, so a shell with real AWS credentials or a profile cannot make these tests touch an account.
"""

import os
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import boto3
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from app.config import DatabaseSettings, Settings
from app.domain.errors import UpstreamUnavailable
from app.domain.models import OrderLine, ProductInfo, StockLine, StockReport
from app.main import create_app
from app.migrate import run_migrations
from retail_common.database import build_engine

LOCALSTACK = "http://localhost:4566"
os.environ.update(
    AWS_ENDPOINT_URL=LOCALSTACK,
    AWS_ACCESS_KEY_ID="test",
    AWS_SECRET_ACCESS_KEY="test",
    AWS_REGION="us-east-1",
    AWS_DEFAULT_REGION="us-east-1",
)
for _name in (
    "AWS_PROFILE",
    "AWS_SESSION_TOKEN",
    "AWS_ENDPOINT_URL_EVENTS",
    "AWS_ENDPOINT_URL_SQS",
):
    os.environ.pop(_name, None)

CUSTOMER = "itest-cust"
MARKER = "itest-%"  # LIKE pattern for every row this suite owns
RELAY_POLL_GRACE_S = 2.5  # longer than the relay's 0.5 s idle poll


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.exit(f"{name} is not set; run `make itest` (it loads .env)", returncode=2)
    return value


def settings_for(*, owner: bool = False, db_port: int = 5432) -> Settings:
    user, password = (
        ("order_owner", _env("ORDER_OWNER_PASSWORD"))
        if owner
        else ("order_app", _env("ORDER_APP_PASSWORD"))
    )
    return Settings(
        db_host="localhost",
        db_port=db_port,
        db_name="order_db",
        db_user=user,
        db_password=password,  # type: ignore[arg-type]
        product_service_url="http://product.invalid",
        inventory_service_url="http://inventory.invalid",
    )


class FakeCatalog:
    def __init__(self) -> None:
        self.products: dict[str, ProductInfo] = {}
        self.down = False

    def add(self, sku: str, price: str, *, currency: str = "USD", active: bool = True) -> None:
        self.products[sku] = ProductInfo(sku, Decimal(price), currency, active)

    def get_products(self, skus: Sequence[str]) -> Mapping[str, ProductInfo]:
        if self.down:
            raise UpstreamUnavailable("product-service")
        return {s: self.products[s] for s in skus if s in self.products}


class FakeStock:
    def __init__(self) -> None:
        self.levels: dict[str, int] = {}
        self.down = False

    def check(self, lines: Sequence[OrderLine]) -> StockReport:
        if self.down:
            raise UpstreamUnavailable("inventory-service")
        out = []
        for line in lines:
            have = self.levels.get(line.sku, 0)
            ok = have >= line.quantity
            out.append(StockLine(line.sku, line.quantity, have, ok, None if ok else "OUT_OF_STOCK"))
        return StockReport(all(o.sufficient for o in out), tuple(out))


@pytest.fixture(scope="session")
def owner_settings() -> DatabaseSettings:
    return settings_for(owner=True)


@pytest.fixture(scope="session", autouse=True)
def migrated(owner_settings: DatabaseSettings) -> None:
    """Apply migrations through the same code path as the `migrate` command."""
    try:
        run_migrations(owner_settings)
    except OperationalError as exc:
        pytest.exit(f"PostgreSQL is not reachable on localhost:5432: run `make up` ({exc.orig})")


@pytest.fixture(scope="session")
def engine(migrated: None) -> Iterator[Engine]:
    """The application role's engine, used for setup, cleanup and direct SQL."""
    engine = build_engine(settings_for())
    yield engine
    engine.dispose()


def wipe(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM outbox WHERE payload->'data'->>'customer_id' LIKE :m"), {"m": MARKER}
        )
        connection.execute(text("DELETE FROM outbox WHERE event_id LIKE '01ITEST%'"))
        connection.execute(text("DELETE FROM processed_events WHERE event_id LIKE '01TEST%'"))
        connection.execute(
            text(
                "DELETE FROM order_items WHERE order_id IN (SELECT order_id FROM orders WHERE customer_id LIKE :m)"
            ),
            {"m": MARKER},
        )
        connection.execute(text("DELETE FROM orders WHERE customer_id LIKE :m"), {"m": MARKER})


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    wipe(engine)
    yield
    wipe(engine)


@pytest.fixture
def catalog() -> FakeCatalog:
    fake = FakeCatalog()
    fake.add("ITEST-SKU-A", "19.99")
    fake.add("ITEST-SKU-B", "8.50")
    return fake


@pytest.fixture
def stock() -> FakeStock:
    fake = FakeStock()
    fake.levels = {"ITEST-SKU-A": 100, "ITEST-SKU-B": 100}
    return fake


@pytest.fixture
def client(catalog: FakeCatalog, stock: FakeStock) -> Iterator[TestClient]:
    with TestClient(create_app(settings_for(), catalog=catalog, stock=stock)) as client:
        yield client


@pytest.fixture
def key() -> str:
    return f"itest-{uuid.uuid4()}"


def order_body(customer: str = CUSTOMER, **lines: int) -> dict[str, Any]:
    lines = lines or {"ITEST-SKU-A": 2}
    return {"customer_id": customer, "items": [{"sku": s, "quantity": q} for s, q in lines.items()]}


def post(client: TestClient, key: str, body: dict[str, Any] | None = None) -> Any:
    return client.post(
        "/api/v1/orders", json=body or order_body(), headers={"Idempotency-Key": key}
    )


def count(engine: Engine, sql: str, **params: object) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(sql), params).scalar_one())


@pytest.fixture(scope="session")
def exclusive_outbox(engine: Engine) -> None:
    """Relay tests need the outbox to themselves; fail loudly (not flakily) if they do not have it."""
    foreign = count(
        engine,
        "SELECT count(*) FROM outbox WHERE published_at IS NULL "
        "AND coalesce(payload->'data'->>'customer_id', '') NOT LIKE :m AND event_id NOT LIKE '01ITEST%'",
        m=MARKER,
    )
    if foreign:
        pytest.exit(
            f"{foreign} unpublished outbox row(s) from outside this suite: let `order-relay` drain "
            "them (make up) before running `make itest`",
            returncode=2,
        )
    # A running relay would claim and publish the rows these tests create. Detect it with a probe.
    event_id = "01ITEST" + uuid.uuid4().hex[:19].upper()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO outbox (event_id, detail_type, payload) VALUES (:e, 'Probe', '{}'::jsonb)"
            ),
            {"e": event_id},
        )
    time.sleep(RELAY_POLL_GRACE_S)
    taken = count(
        engine,
        "SELECT count(*) FROM outbox WHERE event_id = :e AND published_at IS NOT NULL",
        e=event_id,
    )
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM outbox WHERE event_id = :e"), {"e": event_id})
    if taken:
        pytest.exit(
            "another relay is publishing the outbox: stop the order-relay container "
            "(`make itest` does this for you)",
            returncode=2,
        )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def eventbridge() -> Any:
    return boto3.client("events", region_name="us-east-1")


@pytest.fixture(scope="session")
def sqs() -> Any:
    return boto3.client("sqs", region_name="us-east-1")


@dataclass(frozen=True)
class IsolatedBus:
    """A temporary event bus whose only target is a temporary queue."""

    bus: str
    queue: str


@pytest.fixture(scope="session")
def itest_bus(eventbridge: Any, sqs: Any) -> Iterator[IsolatedBus]:
    """Relay tests publish to their own bus and read their own queue.

    The real ``retail-events`` bus fans out to the real queues, which the inventory consumer
    reads. Anything a test published there would be processed as a phantom order, and reading or
    purging those queues from a test counts as a receive (5 receives send a message to the DLQ).
    So the tests never touch them: they get a private bus, rule and queue, removed afterwards.
    """
    suffix = uuid.uuid4().hex[:8]
    bus, queue = f"itest-bus-{suffix}", f"itest-queue-{suffix}"
    queue_url = sqs.create_queue(QueueName=queue)["QueueUrl"]
    queue_arn = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])[
        "Attributes"
    ]["QueueArn"]
    eventbridge.create_event_bus(Name=bus)
    eventbridge.put_rule(
        Name="all-order-created", EventBusName=bus, EventPattern='{"detail-type":["OrderCreated"]}'
    )
    eventbridge.put_targets(
        Rule="all-order-created", EventBusName=bus, Targets=[{"Id": "1", "Arn": queue_arn}]
    )
    yield IsolatedBus(bus=bus, queue=queue)
    eventbridge.remove_targets(Rule="all-order-created", EventBusName=bus, Ids=["1"])
    eventbridge.delete_rule(Name="all-order-created", EventBusName=bus)
    eventbridge.delete_event_bus(Name=bus)
    sqs.delete_queue(QueueUrl=queue_url)
