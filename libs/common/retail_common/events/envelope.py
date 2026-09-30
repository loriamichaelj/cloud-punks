"""The versioned event envelope shared by every producer and consumer (DESIGN.md section 6).

``event_id`` is a ULID and is the idempotency key for every consumer. ``correlation_id`` is
inherited unchanged from the originating HTTP request; ``causation_id`` is the ``event_id`` of the
event that triggered this one. Unknown fields are ignored so additive changes never break readers.
"""

from datetime import UTC, datetime
from typing import Any, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)
from ulid import ULID

from retail_common.logging import get_correlation_id, new_correlation_id

ULID_PATTERN = r"^[0-9A-HJKMNP-TV-Z]{26}$"
SCHEMA_VERSION_V1 = "1.0"


def new_event_id() -> str:
    return str(ULID())


class Envelope(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    event_id: str = Field(pattern=ULID_PATTERN)
    event_type: str = Field(min_length=1, max_length=64)
    schema_version: str = Field(pattern=r"^\d+\.\d+$")
    occurred_at: AwareDatetime
    producer: str = Field(min_length=1, max_length=64)
    correlation_id: str = Field(min_length=1, max_length=128)
    causation_id: str | None = Field(default=None, pattern=ULID_PATTERN)
    data: dict[str, Any]

    @field_validator("occurred_at")
    @classmethod
    def _truncate_to_milliseconds(cls, value: datetime) -> datetime:
        """The wire format has millisecond precision; keep memory and wire identical."""
        return value.replace(microsecond=value.microsecond // 1000 * 1000)

    @field_serializer("occurred_at")
    def _serialize_occurred_at(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    @property
    def major_version(self) -> int:
        return int(self.schema_version.split(".", 1)[0])

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        producer: str,
        data: BaseModel | dict[str, Any],
        correlation_id: str | None = None,
        causation_id: str | None = None,
        schema_version: str = SCHEMA_VERSION_V1,
        occurred_at: datetime | None = None,
    ) -> Self:
        """Build an envelope; the correlation id defaults to the current request/event context."""
        payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
        return cls(
            event_id=new_event_id(),
            event_type=event_type,
            schema_version=schema_version,
            occurred_at=occurred_at or datetime.now(UTC),
            producer=producer,
            correlation_id=correlation_id or get_correlation_id() or new_correlation_id(),
            causation_id=causation_id,
            data=payload,
        )
