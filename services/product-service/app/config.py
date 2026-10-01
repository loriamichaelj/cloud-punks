"""product-service settings (DESIGN.md section 8). Everything comes from the environment."""

from typing import Literal

from pydantic import Field, SecretStr

from retail_common.config import BaseServiceSettings


class DatabaseSettings(BaseServiceSettings):
    """Just what the ``migrate`` job needs (it runs as ``product_owner``)."""

    service_name: str = "product-service"
    db_host: str = Field(min_length=1)
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = Field(min_length=1)
    db_user: str = Field(min_length=1)
    db_password: SecretStr
    db_sslmode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = (
        "disable"
    )


class Settings(DatabaseSettings):
    """The running service (it runs as ``product_app``) also needs the cache."""

    cache_url: str = Field(min_length=1)
