"""Pydantic Settings base classes for the env-var contract (DESIGN.md section 8).

Only variables every service shares live here. Per-service settings (database, cache, queue,
upstream URLs) subclass these in the service's own package. AWS endpoint and credentials are
deliberately absent: boto3 reads ``AWS_ENDPOINT_URL`` and the default credential chain from
the environment itself (ADR-10), so no code path differs between LocalStack and AWS.
"""

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class BaseServiceSettings(BaseSettings):
    """Settings common to every process; values come from the environment only."""

    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    service_name: str = Field(min_length=1)
    environment: str = "local"
    log_level: LogLevel = "INFO"
    http_timeout_connect_s: float = Field(default=1.0, gt=0)
    http_timeout_read_s: float = Field(default=2.0, gt=0)

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


class AwsSettings(BaseServiceSettings):
    """For processes that talk to AWS (EventBridge, SQS, DynamoDB)."""

    aws_region: str = Field(min_length=1)
