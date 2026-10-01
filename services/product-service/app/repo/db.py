"""Engine construction. Pool settings follow DESIGN.md section 8."""

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL

from app.config import DatabaseSettings

CONNECT_TIMEOUT_S = 3


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
