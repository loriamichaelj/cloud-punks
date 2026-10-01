"""The stuck-order query against real PostgreSQL (section 8, stuck-order sweeper).

Only the orders this suite creates (customer ``itest-*``) are identified; the table may hold other
orders, so every assertion is about membership of our own ids, never about the total.
"""

from datetime import timedelta
from typing import Any

import pytest
from conftest import post
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.relay.store import PostgresOutboxStore
from app.relay.sweeper import STUCK_AFTER

pytestmark = pytest.mark.integration


def make_order(client: TestClient, key: str) -> str:
    response = post(client, key)
    assert response.status_code == 202, response.text
    return str(response.json()["order_id"])


def set_order(engine: Engine, order_id: str, *, age: timedelta, status: str = "PENDING") -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE orders SET status = :s, created_at = now() - make_interval(secs => :age) "
                "WHERE order_id = :o"
            ),
            {"s": status, "age": age.total_seconds(), "o": order_id},
        )


def stuck_ids(engine: Engine) -> tuple[set[str], Any]:
    found = PostgresOutboxStore(engine).stuck_orders(STUCK_AFTER, 100_000)
    return set(found.sample_ids), found


def test_only_pending_orders_older_than_five_minutes_are_stuck(
    client: TestClient, engine: Engine
) -> None:
    old_pending = make_order(client, "itest-sweep-1")
    fresh_pending = make_order(client, "itest-sweep-2")
    old_confirmed = make_order(client, "itest-sweep-3")
    just_under = make_order(client, "itest-sweep-4")
    set_order(engine, old_pending, age=timedelta(minutes=10))
    set_order(engine, old_confirmed, age=timedelta(minutes=10), status="CONFIRMED")
    set_order(engine, just_under, age=timedelta(minutes=4, seconds=30))

    ids, found = stuck_ids(engine)

    assert old_pending in ids
    assert not ids & {fresh_pending, old_confirmed, just_under}
    assert found.count == len(ids)
    assert (found.oldest_age_s or 0) >= 600


def test_the_sample_is_bounded_and_oldest_first(client: TestClient, engine: Engine) -> None:
    oldest = make_order(client, "itest-sweep-5")
    newer = make_order(client, "itest-sweep-6")
    set_order(engine, oldest, age=timedelta(hours=3))
    set_order(engine, newer, age=timedelta(minutes=20))

    found = PostgresOutboxStore(engine).stuck_orders(STUCK_AFTER, 1)

    assert found.count >= 2
    assert len(found.sample_ids) == 1
    assert found.sample_ids[0] != newer  # the oldest stuck order comes first


def test_the_query_uses_the_partial_index_not_a_table_scan(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            row[0]
            for row in connection.execute(
                text(
                    "EXPLAIN SELECT count(*) FROM orders "
                    "WHERE status = 'PENDING' AND created_at < now() - interval '5 minutes'"
                )
            )
        )
    assert "ix_orders_pending_created" in plan
