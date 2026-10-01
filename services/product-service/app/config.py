"""product-service settings (DESIGN.md section 8). Everything comes from the environment."""

from pydantic import Field

from retail_common.database import DatabaseSettings as CommonDatabaseSettings


class DatabaseSettings(CommonDatabaseSettings):
    """Just what the ``migrate`` job needs (it runs as ``product_owner``)."""

    service_name: str = "product-service"


class Settings(DatabaseSettings):
    """The running service (it runs as ``product_app``) also needs the cache."""

    cache_url: str = Field(min_length=1)
