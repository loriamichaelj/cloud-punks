"""Create the application databases, roles and Secrets Manager secrets on the dev RDS instance.

    python scripts/db_init.py [--instance loria-retail-dev] [--secret-prefix loria-retail-dev]

Run from the in-VPC runner by the "App: database" workflow, as the database role (it may read the
RDS master secret and write the app secrets, nothing else). It mirrors local/postgres/init:
per service, ``<svc>_owner`` owns the database and runs the migrations, and ``<svc>_app`` gets
DML only, so a running service cannot change its own schema (DESIGN.md section 5).

Idempotent. Each password lives in Secrets Manager, as JSON ``{"password": ...}``, under
``<prefix>/<svc>-<owner|app>-db``. A secret that exists is reused; a missing one is generated.
Every run then sets the role's password to the secret's value, so the two never drift.

The passwords are never printed, logged, passed as an argument or put in an exception message.
The SQL is built with psycopg's composables, which quote identifiers and literals.
"""

import argparse
import json
import os
import secrets
import sys
from collections.abc import Callable
from typing import Any

import boto3
import psycopg
from botocore.exceptions import ClientError
from psycopg import sql

SERVICES = ("product", "order")
KINDS = ("owner", "app")
PASSWORD_BYTES = 32
APP_ROLE_SETTINGS = (  # a stuck transaction is the failure to kill, not to wait on (section 8)
    ("statement_timeout", "5s"),
    ("idle_in_transaction_session_timeout", "30s"),
)


def database_name(service: str) -> str:
    return f"{service}_db"


def role_name(service: str, kind: str) -> str:
    return f"{service}_{kind}"


def secret_name(prefix: str, service: str, kind: str) -> str:
    return f"{prefix}/{service}-{kind}-db"


def new_password() -> str:
    return secrets.token_urlsafe(PASSWORD_BYTES)


def get_or_create_password(client: Any, name: str, tags: list[dict[str, str]]) -> tuple[str, bool]:
    """The password in secret ``name``, creating the secret with a new one if it is missing."""
    try:
        value = client.get_secret_value(SecretId=name)["SecretString"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    else:
        try:
            return str(json.loads(value)["password"]), False
        except (ValueError, KeyError, TypeError):
            raise SystemExit(
                f"secret {name} exists but is not JSON with a 'password' key"
            ) from None
    password = new_password()
    client.create_secret(
        Name=name,
        Description="Database password, created by scripts/db_init.py",
        SecretString=json.dumps({"password": password}),
        Tags=tags,
    )
    return password, True


def _exists(conn: Any, query: str, name: str) -> bool:
    return bool(conn.execute(query, (name,)).fetchone())


def _run(label: str, action: Callable[[], None]) -> None:
    """Run one step. A database error is reduced to its class and SQLSTATE: the driver's message
    can quote the statement, and a statement can contain a password."""
    try:
        action()
    except psycopg.Error as exc:
        raise SystemExit(
            f"{label} failed: {type(exc).__name__} (sqlstate {exc.sqlstate})"
        ) from None


def setup_roles_and_database(
    admin: Any, service: str, passwords: dict[str, str], master_user: str
) -> None:
    """Roles, then the database, as the master user, connected to the ``postgres`` database."""
    owner, app = role_name(service, "owner"), role_name(service, "app")
    database = database_name(service)

    for kind in KINDS:
        role = role_name(service, kind)
        verb = (
            "ALTER"
            if _exists(admin, "SELECT 1 FROM pg_roles WHERE rolname = %s", role)
            else "CREATE"
        )
        statement = sql.SQL("{} ROLE {} LOGIN PASSWORD {}").format(
            sql.SQL(verb), sql.Identifier(role), sql.Literal(passwords[kind])
        )
        _run(f"{verb.lower()} role {role}", lambda s=statement: admin.execute(s))

    for setting, value in APP_ROLE_SETTINGS:
        statement = sql.SQL("ALTER ROLE {} SET {} = {}").format(
            sql.Identifier(app), sql.Identifier(setting), sql.Literal(value)
        )
        _run(f"set {setting} on {app}", lambda s=statement: admin.execute(s))

    # CREATE DATABASE ... OWNER needs the creator to be able to SET ROLE to the new owner.
    grant = sql.SQL("GRANT {} TO {}").format(sql.Identifier(owner), sql.Identifier(master_user))
    _run(f"grant {owner} to the master user", lambda: admin.execute(grant))

    if not _exists(admin, "SELECT 1 FROM pg_database WHERE datname = %s", database):
        create = sql.SQL("CREATE DATABASE {} OWNER {}").format(
            sql.Identifier(database), sql.Identifier(owner)
        )
        _run(f"create database {database}", lambda: admin.execute(create))

    revoke = sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
    connect = sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
        sql.Identifier(database), sql.Identifier(app)
    )
    _run(f"revoke public access to {database}", lambda: admin.execute(revoke))
    _run(f"grant connect on {database}", lambda: admin.execute(connect))


def setup_schema(db: Any, service: str) -> None:
    """Schema privileges, as the master user, connected to ``<svc>_db``."""
    owner, app = role_name(service, "owner"), role_name(service, "app")
    statements = [
        sql.SQL("REVOKE CREATE ON SCHEMA public FROM PUBLIC"),
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(app)),
        # Tables the owner creates later (Alembic) are automatically usable by the app role.
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
        ).format(sql.Identifier(owner), sql.Identifier(app)),
        # And tables that already exist, so a re-run repairs a database set up before this.
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(
            sql.Identifier(app)
        ),
    ]
    for index, statement in enumerate(statements, start=1):
        _run(f"schema grant {index} on {database_name(service)}", lambda s=statement: db.execute(s))


def describe_instance(rds: Any, identifier: str) -> tuple[str, int, str]:
    """(host, port, master secret ARN) of the RDS instance."""
    instance = rds.describe_db_instances(DBInstanceIdentifier=identifier)["DBInstances"][0]
    return (
        instance["Endpoint"]["Address"],
        int(instance["Endpoint"]["Port"]),
        instance["MasterUserSecret"]["SecretArn"],
    )


def connect(host: str, port: int, dbname: str, user: str, password: str) -> Any:
    # RDS refuses non-TLS connections (rds.force_ssl), so require it here as well.
    return psycopg.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        sslmode="require",
        connect_timeout=10,
        autocommit=True,
    )


def run(instance: str, secret_prefix: str) -> list[str]:
    rds = boto3.client("rds")
    sm = boto3.client("secretsmanager")
    host, port, master_arn = describe_instance(rds, instance)
    master = json.loads(sm.get_secret_value(SecretId=master_arn)["SecretString"])
    user, master_password = master["username"], master["password"]
    tags = [
        {"Key": "Project", "Value": "retail-platform"},
        {"Key": "Stack", "Value": "app-database"},
    ]

    rows = [
        "| Database | Owner role | App role | Owner secret | App secret |",
        "| --- | --- | --- | --- | --- |",
    ]
    prepared: dict[str, dict[str, str]] = {}
    outcome: dict[str, dict[str, str]] = {}
    for service in SERVICES:
        prepared[service], outcome[service] = {}, {}
        for kind in KINDS:
            password, created = get_or_create_password(
                sm, secret_name(secret_prefix, service, kind), tags
            )
            prepared[service][kind] = password
            outcome[service][kind] = "created" if created else "reused"

    try:
        with connect(host, port, "postgres", user, master_password) as admin:
            for service in SERVICES:
                setup_roles_and_database(admin, service, prepared[service], user)
        for service in SERVICES:
            with connect(host, port, database_name(service), user, master_password) as db:
                setup_schema(db, service)
    except psycopg.Error as exc:
        raise SystemExit(
            f"database connection failed: {type(exc).__name__} (sqlstate {exc.sqlstate})"
        ) from None

    for service in SERVICES:
        owner_result, app_result = outcome[service]["owner"], outcome[service]["app"]
        rows.append(
            f"| `{database_name(service)}` | `{role_name(service, 'owner')}` | "
            f"`{role_name(service, 'app')}` | {owner_result} | {app_result} |"
        )
    return rows


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--instance", default="loria-retail-dev", help="RDS instance identifier")
    parser.add_argument("--secret-prefix", default="loria-retail-dev")
    args = parser.parse_args(argv)

    rows = run(args.instance, args.secret_prefix)
    text = "### App databases\n\n" + "\n".join(rows) + "\n"
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
