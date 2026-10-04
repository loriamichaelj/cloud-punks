"""local/seed/reset.py: what the "App: reset" workflow deletes and puts back, against fakes."""

from contextlib import contextmanager
from typing import Any

import pytest
import reset
from catalog import STOCK


class FakeConnection:
    """Records each statement and whether it ran inside the transaction."""

    def __init__(self, counts: dict[str, int] | None = None) -> None:
        self.statements: list[str] = []
        self.in_transaction: list[bool] = []
        self.counts = counts or {}
        self.open = False

    @contextmanager
    def transaction(self) -> Any:
        self.open = True
        try:
            yield
        finally:
            self.open = False

    def cursor(self) -> "FakeCursor":
        return FakeCursor(self)


class FakeCursor:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn
        self.rowcount = -1

    def execute(self, sql: str) -> None:
        self._conn.statements.append(sql)
        self._conn.in_transaction.append(self._conn.open)
        self.rowcount = self._conn.counts.get(sql.removeprefix("DELETE FROM "), 0)

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeDynamoDb:
    def __init__(self) -> None:
        self.puts: list[dict[str, Any]] = []

    def put_item(self, **request: Any) -> None:
        self.puts.append(request)


def test_deletes_the_market_children_first_in_one_transaction() -> None:
    conn = FakeConnection({"orders": 3, "bids": 2})
    deleted = reset.reset_orders(conn)
    assert conn.statements == [
        "DELETE FROM bids",
        "DELETE FROM listings",
        "DELETE FROM order_items",
        "DELETE FROM orders",
        "DELETE FROM outbox",
    ]
    assert all(conn.in_transaction)
    assert deleted["orders_deleted"] == 3
    assert deleted["bids_deleted"] == 2


def test_keeps_the_consumers_dedupe() -> None:
    conn = FakeConnection()
    reset.reset_orders(conn)
    assert not any("processed_events" in s for s in conn.statements)


def test_every_cloudpunk_goes_back_to_the_platform() -> None:
    dynamodb = FakeDynamoDb()
    assert reset.reset_stock(dynamodb, "loria-inventory") == {"stock_reset": 100}
    assert {p["Item"]["sku"]["S"] for p in dynamodb.puts} == set(STOCK)
    for put in dynamodb.puts:
        assert put["TableName"] == "loria-inventory"
        assert put["Item"]["available"] == {"N": "1"}
        assert put["Item"]["reserved"] == {"N": "0"}
        assert "owner" not in put["Item"]  # back with the platform: red again
        assert "ConditionExpression" not in put  # an existing (sold) item is overwritten


@pytest.mark.parametrize("environment", ["stage", "prod", "staging", ""])
def test_refuses_outside_local_and_dev(environment: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", environment)

    def no_store(*_: object, **__: object) -> None:
        raise AssertionError("a refused reset must not connect to anything")

    monkeypatch.setattr(reset.psycopg, "connect", no_store)
    monkeypatch.setattr(reset.boto3, "client", no_store)
    assert reset.main() == 2
