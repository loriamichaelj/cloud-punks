"""Migration 0001 for order_db, inspected from the catalog up."""

from typing import Any

import psycopg
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.config import DatabaseSettings
from app.migrate import run_migrations


def rows(engine: Engine, sql: str, **params: object) -> list[tuple[Any, ...]]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(sql), params)]


def columns(engine: Engine, table: str) -> dict[str, tuple[Any, ...]]:
    result = rows(
        engine,
        "SELECT column_name, data_type, is_nullable, numeric_precision, numeric_scale, "
        "character_maximum_length, column_default, is_identity, identity_generation "
        "FROM information_schema.columns WHERE table_schema='public' AND table_name=:t",
        t=table,
    )
    return {row[0]: row[1:] for row in result}


def test_the_revision_is_recorded_and_rerunning_is_a_no_op(
    owner_settings: DatabaseSettings, engine: Engine
) -> None:
    run_migrations(owner_settings)
    assert rows(engine, "SELECT version_num FROM alembic_version") == [("0002",)]


def test_orders_columns_match_the_design(engine: Engine) -> None:
    c = columns(engine, "orders")

    assert set(c) == {
        "order_id", "customer_id", "status", "status_reason", "total_amount", "currency",
        "idempotency_key", "request_hash", "version", "created_at", "updated_at",
    }  # fmt: skip
    assert c["order_id"][0] == "character"
    assert c["order_id"][4] == 26  # a ULID
    assert c["total_amount"][0] == "numeric"
    assert (c["total_amount"][2], c["total_amount"][3]) == (12, 2)  # NUMERIC(12,2): totals
    assert c["request_hash"][4] == 64  # sha256 hex
    assert c["version"][5] == "1"  # optimistic lock starts at 1
    assert c["created_at"][0] == "timestamp with time zone"


def test_money_columns_are_numeric_never_float(engine: Engine) -> None:
    unit_price = columns(engine, "order_items")["unit_price"]
    assert unit_price[0] == "numeric"
    assert (unit_price[2], unit_price[3]) == (10, 2)


def test_outbox_has_a_bigint_identity_and_a_jsonb_payload(engine: Engine) -> None:
    c = columns(engine, "outbox")
    assert c["id"][0] == "bigint"
    assert c["id"][6:8] == ("YES", "ALWAYS")
    assert c["payload"][0] == "jsonb"
    assert c["payload"][1] == "NO"  # NOT NULL
    assert c["attempts"][5] == "0"
    assert c["published_at"][1] == "YES"  # NULL means "not yet published"


def test_the_partial_and_descending_indexes_exist_as_designed(engine: Engine) -> None:
    defs = dict(
        rows(
            engine,
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public' AND tablename IN ('orders', 'outbox')",
        )
    )

    assert "WHERE (published_at IS NULL)" in defs["ix_outbox_unpublished"]
    assert "WHERE ((status)::text = 'PENDING'::text)" in defs["ix_orders_pending_created"]
    assert "created_at DESC" in defs["ix_orders_customer_created"]
    assert "customer_id" in defs["ix_orders_customer_created"]


def insert_order(c: Any, **overrides: object) -> None:
    values = {
        "order_id": "01J9Z6Q4W8K3M2N1P0R7S5T4V3", "customer_id": "itest-mig", "status": "PENDING",
        "total_amount": 1, "currency": "USD", "idempotency_key": "itest-mig-key", "request_hash": "a" * 64,
        **overrides,
    }  # fmt: skip
    cols = ", ".join(values)
    params = ", ".join(f":{k}" for k in values)
    c.execute(text(f"INSERT INTO orders ({cols}) VALUES ({params})"), values)


def test_a_status_outside_the_state_machine_is_rejected_by_the_database(engine: Engine) -> None:
    with pytest.raises(IntegrityError, match="ck_orders_status"), engine.begin() as c:
        insert_order(c, status="SHIPPED")


def test_the_idempotency_constraint_is_per_customer(engine: Engine) -> None:
    with engine.begin() as c:
        insert_order(c)
        insert_order(
            c, order_id="01J9Z6Q4W8K3M2N1P0R7S5T4V4", customer_id="itest-mig-other"
        )  # fine
    with pytest.raises(IntegrityError, match="uq_orders_customer_idem"), engine.begin() as c:
        insert_order(c, order_id="01J9Z6Q4W8K3M2N1P0R7S5T4V5")  # same customer, same key


def test_item_quantity_is_limited_to_1_through_100_by_the_database(engine: Engine) -> None:
    with engine.begin() as c:
        insert_order(c)
    for bad in (0, 101):
        with pytest.raises(IntegrityError, match="ck_order_items_quantity"), engine.begin() as c:
            c.execute(
                text("INSERT INTO order_items VALUES ('01J9Z6Q4W8K3M2N1P0R7S5T4V3', 'S', :q, 1)"),
                {"q": bad},
            )


def test_order_items_cannot_reference_a_missing_order(engine: Engine) -> None:
    with pytest.raises(IntegrityError, match="foreign key"), engine.begin() as c:
        c.execute(text("INSERT INTO order_items VALUES ('01J9Z6Q4W8K3M2N1P0R7S5T4ZZ', 'S', 1, 1)"))


def test_the_schema_is_owned_by_the_owner_role(engine: Engine) -> None:
    owners = rows(
        engine,
        "SELECT tablename, tableowner FROM pg_tables WHERE schemaname='public' "
        "AND tablename IN ('orders', 'order_items', 'outbox', 'processed_events', 'listings', "
        "'bids', 'alembic_version')",
    )
    assert {owner for _, owner in owners} == {"order_owner"}
    assert len(owners) == 7


def test_the_app_role_has_exactly_dml_on_the_six_tables(engine: Engine) -> None:
    grants = rows(
        engine,
        "SELECT table_name, privilege_type FROM information_schema.role_table_grants WHERE grantee = 'order_app'",
    )
    for table in ("orders", "order_items", "outbox", "processed_events", "listings", "bids"):
        assert {p for t, p in grants if t == table} == {"SELECT", "INSERT", "UPDATE", "DELETE"}


@pytest.mark.parametrize(
    "ddl",
    ["CREATE TABLE itest_forbidden (x int)", "ALTER TABLE orders ADD COLUMN x int", "DROP TABLE outbox", "TRUNCATE orders"],
)  # fmt: skip
def test_the_running_service_cannot_change_its_own_schema(engine: Engine, ddl: str) -> None:
    with pytest.raises(DBAPIError, match=r"permission denied|must be owner"), engine.begin() as c:
        c.execute(text(ddl))


def test_the_app_role_carries_the_documented_timeouts(engine: Engine) -> None:
    """A stuck transaction holding the outbox lock is the failure to kill, not to wait on."""
    assert rows(engine, "SHOW statement_timeout") == [("5s",)]
    assert rows(engine, "SHOW idle_in_transaction_session_timeout") == [("30s",)]


def test_another_services_database_is_out_of_reach(engine: Engine) -> None:
    """ADR-03: separate databases, separate roles, no cross-service joins."""
    url = engine.url.set(database="product_db")
    conninfo = url.render_as_string(hide_password=False).replace("+psycopg", "")

    with pytest.raises(psycopg.OperationalError, match="permission denied"):
        psycopg.connect(conninfo, connect_timeout=3)
