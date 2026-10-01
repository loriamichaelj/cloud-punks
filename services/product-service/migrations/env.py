"""Alembic environment. Online only: every migration runs in a transaction (PostgreSQL DDL is
transactional, so a failed migration leaves no half-applied schema)."""

from alembic import context
from sqlalchemy import create_engine

config = context.config

if context.is_offline_mode():
    raise RuntimeError("offline migrations are not supported; run `python -m app migrate`")

engine = create_engine(config.attributes["url"])
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
