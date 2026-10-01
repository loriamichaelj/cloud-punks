"""PostgreSQL settings and engine construction shared by the services that own a database.

Pool settings follow DESIGN.md section 8. The role-level ``statement_timeout`` (5 s) and
``idle_in_transaction_session_timeout`` (30 s) are set on the ``<svc>_app`` roles by the
PostgreSQL init script, so every connection the running service opens inherits them.
"""

from typing import Literal

from pydantic import Field, SecretStr
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from retail_common.config import BaseServiceSettings

CONNECT_TIMEOUT_S = 3

# "PostgreSQL cannot serve this right now": a refused or dropped connection, a statement
# cancelled by statement_timeout (all OperationalError) and an exhausted connection pool.
# Anything else (a constraint, a bug) is a real error and must not be mistaken for an outage.
STORE_ERRORS = (OperationalError, InterfaceError, PoolTimeoutError)


class DatabaseSettings(BaseServiceSettings):
    """DB_* variables. A service subclasses this to give ``service_name`` its default."""

    db_host: str = Field(min_length=1)
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = Field(min_length=1)
    db_user: str = Field(min_length=1)
    db_password: SecretStr
    db_sslmode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = (
        "disable"
    )


def database_url(settings: DatabaseSettings) -> URL:
    """Build the URL from parts so passwords with special characters need no escaping."""
    return URL.create(
        "postgresql+psycopg",
        username=settings.db_user,
        password=settings.db_password.get_secret_value(),
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
        query={"sslmode": settings.db_sslmode},
    )


def build_engine(settings: DatabaseSettings) -> Engine:
    # Each PostgreSQL connection is a backend process: keep replicas x (pool_size + max_overflow)
    # well under max_connections (RDS Proxy in the cloud).
    return create_engine(
        database_url(settings),
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_S},
    )


def ping(engine: Engine) -> None:
    """Readiness probe: raises if PostgreSQL cannot answer ``SELECT 1``."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
