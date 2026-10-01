"""Migration 0001 as applied to the real database, checked from the catalog up."""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.config import DatabaseSettings
from app.migrate import run_migrations


def rows(engine: Engine, sql: str, **params: object) -> list[tuple[object, ...]]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(sql), params)]


def columns(engine: Engine, table: str) -> dict[str, tuple[object, ...]]:
    result = rows(
        engine,
        "SELECT column_name, data_type, is_nullable, numeric_precision, numeric_scale, "
        "character_maximum_length, column_default, is_identity, identity_generation "
        "FROM information_schema.columns WHERE table_schema='public' AND table_name=:t",
        t=table,
    )
    return {row[0]: row[1:] for row in result}  # type: ignore[misc]


def test_the_revision_is_recorded(engine: Engine) -> None:
    assert rows(engine, "SELECT version_num FROM alembic_version") == [("0001",)]


def test_running_migrations_again_is_a_no_op(
    owner_settings: DatabaseSettings, engine: Engine
) -> None:
    run_migrations(owner_settings)
    run_migrations(owner_settings)
    assert rows(engine, "SELECT version_num FROM alembic_version") == [("0001",)]


def test_product_columns_match_the_design(engine: Engine) -> None:
    c = columns(engine, "products")

    assert set(c) == {
        "sku", "name", "description", "category_id", "price", "currency",
        "active", "created_at", "updated_at",
    }  # fmt: skip
    assert c["price"][0] == "numeric"
    assert (c["price"][2], c["price"][3]) == (10, 2)  # NUMERIC(10,2): money is never a float
    assert c["price"][1] == "NO"
    assert c["currency"][0] == "character"
    assert c["currency"][4] == 3
    assert "USD" in str(c["currency"][5])
    assert c["created_at"][0] == "timestamp with time zone"
    assert c["updated_at"][0] == "timestamp with time zone"
    assert c["sku"][4] == 64
    assert c["active"][0] == "boolean"
    assert "true" in str(c["active"][5])


def test_category_ids_are_always_generated_identities(engine: Engine) -> None:
    c = columns(engine, "categories")
    assert c["id"][6:8] == ("YES", "ALWAYS")  # is_identity, identity_generation


def test_the_partial_index_covers_only_active_products(engine: Engine) -> None:
    (definition,) = rows(
        engine, "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_products_category_active'"
    )[0]
    assert "category_id" in str(definition)
    assert "WHERE active" in str(definition)


def test_a_negative_price_is_rejected_by_the_database_itself(engine: Engine) -> None:
    with pytest.raises(IntegrityError, match="ck_products_price_non_negative"), engine.begin() as c:
        c.execute(text(
            "INSERT INTO products (sku, name, category_id, price) "
            "SELECT 'ITEST-NEG', 'x', id, -1 FROM categories LIMIT 1"
        ))  # fmt: skip


def test_the_foreign_key_to_categories_is_enforced(engine: Engine) -> None:
    with pytest.raises(IntegrityError, match="foreign key"), engine.begin() as c:
        c.execute(text(
            "INSERT INTO products (sku, name, category_id, price) VALUES ('ITEST-FK', 'x', -1, 1)"
        ))  # fmt: skip


def test_category_slugs_are_unique(engine: Engine) -> None:
    with pytest.raises(IntegrityError, match="uq_categories_slug"), engine.begin() as c:
        c.execute(text("INSERT INTO categories (slug, name) VALUES ('itest-cat', 'again')"))


def test_an_identity_column_cannot_be_overridden_by_the_application(engine: Engine) -> None:
    with pytest.raises(DBAPIError, match="GENERATED ALWAYS"), engine.begin() as c:
        c.execute(text("INSERT INTO categories (id, slug, name) VALUES (999999, 'itest-x', 'x')"))


def test_the_schema_is_owned_by_the_owner_role_not_the_app_role(engine: Engine) -> None:
    owners = rows(
        engine,
        "SELECT tablename, tableowner FROM pg_tables WHERE schemaname='public' "
        "AND tablename IN ('products', 'categories', 'alembic_version')",
    )
    assert {owner for _, owner in owners} == {"product_owner"}


def test_the_app_role_has_exactly_dml_on_the_catalog_tables(engine: Engine) -> None:
    grants = rows(
        engine,
        "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
        "WHERE grantee = 'product_app' AND table_name IN ('products', 'categories')",
    )
    for table in ("products", "categories"):
        assert {p for t, p in grants if t == table} == {"SELECT", "INSERT", "UPDATE", "DELETE"}


@pytest.mark.parametrize(
    "ddl",
    ["CREATE TABLE itest_forbidden (x int)", "ALTER TABLE products ADD COLUMN x int",
     "DROP TABLE categories", "TRUNCATE products"],
)  # fmt: skip
def test_the_running_service_cannot_change_its_own_schema(engine: Engine, ddl: str) -> None:
    with pytest.raises(DBAPIError, match=r"permission denied|must be owner"), engine.begin() as c:
        c.execute(text(ddl))
