import contextvars
import json
import re
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from helpers import make_envelope, order_created_data
from pydantic import ValidationError

from retail_common.events.envelope import Envelope
from retail_common.events.schemas import OrderCreatedData
from retail_common.logging import set_correlation_id

ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
MILLIS_Z = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


def test_create_fills_the_documented_fields() -> None:
    envelope = Envelope.create(
        event_type="OrderCreated", producer="order-service", data={"a": 1}, correlation_id="c-1"
    )

    assert ULID_RE.match(envelope.event_id)
    assert envelope.schema_version == "1.0"
    assert envelope.major_version == 1
    assert envelope.producer == "order-service"
    assert envelope.causation_id is None
    assert envelope.occurred_at.tzinfo is not None
    assert abs(datetime.now(UTC) - envelope.occurred_at) < timedelta(seconds=5)


def test_every_envelope_gets_a_distinct_event_id() -> None:
    ids = {make_envelope().event_id for _ in range(50)}
    assert len(ids) == 50


def test_correlation_id_defaults_to_the_current_context() -> None:
    """A handler that builds a follow-up event inherits the incoming event's correlation id."""

    def build() -> str:
        set_correlation_id("from-the-request")
        return Envelope.create(event_type="X", producer="p", data={}).correlation_id

    assert contextvars.copy_context().run(build) == "from-the-request"


def test_correlation_id_is_generated_when_there_is_no_context() -> None:
    envelope = contextvars.copy_context().run(
        lambda: Envelope.create(event_type="X", producer="p", data={})
    )
    assert ULID_RE.match(envelope.correlation_id)


def test_an_explicit_correlation_id_wins_over_the_context() -> None:
    def build() -> str:
        set_correlation_id("ambient")
        return Envelope.create(
            event_type="X", producer="p", data={}, correlation_id="explicit"
        ).correlation_id

    assert contextvars.copy_context().run(build) == "explicit"


def test_causation_id_links_to_the_triggering_event() -> None:
    cause = make_envelope()
    effect = make_envelope("InventoryReserved", data={}, causation_id=cause.event_id)
    assert effect.causation_id == cause.event_id


def test_json_uses_millisecond_utc_timestamps() -> None:
    envelope = make_envelope(occurred_at=datetime(2026, 10, 5, 14, 3, 11, 412345, tzinfo=UTC))

    wire = json.loads(envelope.model_dump_json())

    assert wire["occurred_at"] == "2026-10-05T14:03:11.412Z"
    assert MILLIS_Z.match(wire["occurred_at"])


def test_timestamps_are_truncated_to_milliseconds_at_construction() -> None:
    """What we build must equal what a consumer parses back off the wire."""
    envelope = make_envelope(occurred_at=datetime(2026, 10, 5, 14, 3, 11, 412999, tzinfo=UTC))
    assert envelope.occurred_at.microsecond == 412000
    assert Envelope.model_validate_json(envelope.model_dump_json()) == envelope


def test_a_non_utc_timestamp_is_normalized_to_utc() -> None:
    eastern = timezone(timedelta(hours=-5))
    envelope = make_envelope(occurred_at=datetime(2026, 10, 5, 9, 0, 0, tzinfo=eastern))
    assert json.loads(envelope.model_dump_json())["occurred_at"] == "2026-10-05T14:00:00.000Z"


def test_the_wire_format_has_exactly_the_documented_keys() -> None:
    wire = json.loads(make_envelope().model_dump_json())
    assert set(wire) == {
        "event_id",
        "event_type",
        "schema_version",
        "occurred_at",
        "producer",
        "correlation_id",
        "causation_id",
        "data",
    }


def test_round_trips_through_json() -> None:
    original = make_envelope()
    assert Envelope.model_validate_json(original.model_dump_json()) == original


def test_money_in_the_payload_is_a_json_string() -> None:
    payload = OrderCreatedData.model_validate(order_created_data(total_amount="39.98"))
    envelope = Envelope.create(event_type="OrderCreated", producer="p", data=payload)

    assert payload.total_amount == Decimal("39.98")
    assert envelope.data["total_amount"] == "39.98"
    assert isinstance(envelope.data["total_amount"], str)


def test_unknown_fields_are_ignored_so_additive_changes_are_safe() -> None:
    wire = json.loads(make_envelope().model_dump_json())
    wire["added_in_1_1"] = {"anything": True}

    parsed = Envelope.model_validate(wire)

    assert not hasattr(parsed, "added_in_1_1")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_id", "not-a-ulid"),
        ("event_id", "01J9Z6R0C4" + "I" * 16),  # 'I' is not in the Crockford alphabet
        ("schema_version", "1"),
        ("schema_version", "v1.0"),
        ("causation_id", "nope"),
        ("correlation_id", ""),
        ("event_type", ""),
        ("occurred_at", "2026-10-05T14:03:11"),  # no timezone
    ],
)
def test_invalid_envelopes_are_rejected(field: str, value: str) -> None:
    wire = json.loads(make_envelope().model_dump_json())
    wire[field] = value
    with pytest.raises(ValidationError):
        Envelope.model_validate(wire)


def test_envelopes_are_immutable() -> None:
    envelope = make_envelope()
    with pytest.raises(ValidationError, match="frozen"):
        envelope.event_type = "Other"  # type: ignore[misc]
