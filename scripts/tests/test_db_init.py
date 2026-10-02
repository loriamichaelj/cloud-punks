"""scripts/db_init.py: hermetic tests with fake Secrets Manager and database connections."""

import json
from typing import Any

import db_init
import psycopg
import pytest
from botocore.exceptions import ClientError

PASSWORD = "s3cret-value_that-must-never-leak"
PASSWORDS = {"owner": "owner-pw", "app": "app-pw"}


class FakeResult:
    def __init__(self, row: tuple[int] | None) -> None:
        self._row = row

    def fetchone(self) -> tuple[int] | None:
        return self._row


class FakeConn:
    """Records every statement as text. ``roles`` and ``databases`` already exist."""

    def __init__(
        self,
        roles: set[str] | None = None,
        databases: set[str] | None = None,
        fail: Exception | None = None,
    ) -> None:
        self.roles = roles or set()
        self.databases = databases or set()
        self.fail = fail
        self.statements: list[str] = []

    def execute(self, query: Any, params: tuple[str, ...] | None = None) -> FakeResult:
        if isinstance(query, str):  # the two existence checks
            names = self.roles if "pg_roles" in query else self.databases
            assert params is not None
            return FakeResult((1,) if params[0] in names else None)
        if self.fail is not None:
            raise self.fail
        self.statements.append(query.as_string(None))
        return FakeResult(None)


class FakeSecrets:
    def __init__(self, existing: dict[str, str] | None = None) -> None:
        self.store = dict(existing or {})
        self.created: list[dict[str, Any]] = []

    def get_secret_value(self, SecretId: str) -> dict[str, str]:
        if SecretId not in self.store:
            raise ClientError({"Error": {"Code": "ResourceNotFoundException"}}, "GetSecretValue")
        return {"SecretString": self.store[SecretId]}

    def create_secret(self, **kwargs: Any) -> None:
        self.created.append(kwargs)
        self.store[kwargs["Name"]] = kwargs["SecretString"]


def test_names_follow_the_local_init_and_the_helm_values() -> None:
    assert db_init.database_name("product") == "product_db"
    assert db_init.role_name("order", "owner") == "order_owner"
    assert db_init.role_name("order", "app") == "order_app"
    assert [
        db_init.secret_name("loria-retail-dev", s, k)
        for s in db_init.SERVICES
        for k in db_init.KINDS
    ] == [
        "loria-retail-dev/product-owner-db",
        "loria-retail-dev/product-app-db",
        "loria-retail-dev/order-owner-db",
        "loria-retail-dev/order-app-db",
    ]


def test_passwords_are_long_unique_and_safe_inside_a_url_or_a_literal() -> None:
    first, second = db_init.new_password(), db_init.new_password()
    assert first != second
    assert len(first) >= 40
    assert set(first) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def test_a_missing_secret_is_created_with_a_json_password() -> None:
    client = FakeSecrets()
    password, created = db_init.get_or_create_password(
        client, "p/x-app-db", [{"Key": "k", "Value": "v"}]
    )

    assert created is True
    assert json.loads(client.store["p/x-app-db"]) == {"password": password}
    assert client.created[0]["Tags"] == [{"Key": "k", "Value": "v"}]


def test_an_existing_secret_is_reused_and_not_rewritten() -> None:
    client = FakeSecrets({"p/x-app-db": json.dumps({"password": "already-there"})})

    assert db_init.get_or_create_password(client, "p/x-app-db", []) == ("already-there", False)
    assert client.created == []


def test_a_malformed_existing_secret_stops_the_run_without_echoing_it() -> None:
    client = FakeSecrets({"p/x-app-db": "not json " + PASSWORD})

    with pytest.raises(SystemExit) as stopped:
        db_init.get_or_create_password(client, "p/x-app-db", [])
    assert PASSWORD not in str(stopped.value)


def test_a_new_service_gets_roles_a_database_and_locked_down_access() -> None:
    conn = FakeConn()
    db_init.setup_roles_and_database(conn, "product", PASSWORDS, "retail_admin")
    sql_text = "\n".join(conn.statements)

    assert "CREATE ROLE \"product_owner\" LOGIN PASSWORD 'owner-pw'" in sql_text
    assert "CREATE ROLE \"product_app\" LOGIN PASSWORD 'app-pw'" in sql_text
    assert 'ALTER ROLE "product_app" SET "statement_timeout" = \'5s\'' in sql_text
    assert (
        'ALTER ROLE "product_app" SET "idle_in_transaction_session_timeout" = \'30s\'' in sql_text
    )
    assert 'GRANT "product_owner" TO "retail_admin"' in sql_text
    assert 'CREATE DATABASE "product_db" OWNER "product_owner"' in sql_text
    assert 'REVOKE ALL ON DATABASE "product_db" FROM PUBLIC' in sql_text
    assert 'GRANT CONNECT ON DATABASE "product_db" TO "product_app"' in sql_text
    # The owner exists before the database it owns, and public access goes before the app gets in.
    assert (
        sql_text.index("CREATE ROLE")
        < sql_text.index("CREATE DATABASE")
        < sql_text.index("REVOKE ALL")
    )
    assert sql_text.index("REVOKE ALL") < sql_text.index("GRANT CONNECT")


def test_a_rerun_alters_existing_roles_and_keeps_the_existing_database() -> None:
    conn = FakeConn(roles={"order_owner", "order_app"}, databases={"order_db"})
    db_init.setup_roles_and_database(conn, "order", PASSWORDS, "retail_admin")
    sql_text = "\n".join(conn.statements)

    assert 'ALTER ROLE "order_owner" LOGIN PASSWORD' in sql_text
    assert 'ALTER ROLE "order_app" LOGIN PASSWORD' in sql_text
    assert "CREATE ROLE" not in sql_text
    assert "CREATE DATABASE" not in sql_text


def test_the_app_role_gets_dml_only_and_never_ddl() -> None:
    conn = FakeConn()
    db_init.setup_schema(conn, "order")
    sql_text = "\n".join(conn.statements)

    assert "REVOKE CREATE ON SCHEMA public FROM PUBLIC" in sql_text
    assert 'GRANT USAGE ON SCHEMA public TO "order_app"' in sql_text
    assert (
        'ALTER DEFAULT PRIVILEGES FOR ROLE "order_owner" IN SCHEMA public '
        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "order_app"'
    ) in sql_text
    for forbidden in ("CREATE TABLE", "ALL PRIVILEGES", "SUPERUSER", "CREATEDB", "CREATEROLE"):
        assert forbidden not in sql_text


def test_a_database_error_never_carries_the_statement_or_the_password() -> None:
    error = psycopg.errors.SyntaxError(f"syntax error at or near PASSWORD '{PASSWORD}'")
    conn = FakeConn(fail=error)

    with pytest.raises(SystemExit) as stopped:
        db_init.setup_roles_and_database(
            conn, "product", {"owner": PASSWORD, "app": PASSWORD}, "retail_admin"
        )

    message = str(stopped.value)
    assert PASSWORD not in message
    assert "PASSWORD" not in message
    assert "SyntaxError" in message
    assert "42601" in message
