"""``python -m app migrate``: apply Alembic migrations as ``order_owner`` (ADR-11).

Migrations never run at application startup. In Compose this is the ``order-migrate`` one-shot
service; on Kubernetes it becomes a ``pre-install,pre-upgrade`` Helm hook Job.
"""

from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config

from app.config import DatabaseSettings
from retail_common.database import database_url
from retail_common.logging import configure_logging

# Resolves to services/order-service/migrations locally and /srv/migrations in the image.
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

_log = structlog.get_logger("migrate")


def run_migrations(settings: DatabaseSettings, revision: str = "head") -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    # Passed as an object, not through the ini file, so passwords with '%' etc. need no escaping.
    config.attributes["url"] = database_url(settings)
    command.upgrade(config, revision)


def main() -> int:
    settings = DatabaseSettings()  # type: ignore[call-arg]  # values come from the environment
    configure_logging("order-migrate", settings.environment, settings.log_level)
    _log.info("migrate_started", database=settings.db_name, user=settings.db_user)
    run_migrations(settings)
    _log.info("migrate_complete")
    return 0
