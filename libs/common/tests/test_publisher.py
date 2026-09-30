import json
from typing import Any

import boto3
from botocore.exceptions import EndpointConnectionError
from helpers import FakeEvents, client_error, make_envelope
from moto import mock_aws
from prometheus_client import CollectorRegistry

from retail_common.events.publisher import EventBridgePublisher, source_for
from retail_common.metrics import EventMetrics

BUS = "retail-events"


def metrics() -> tuple[EventMetrics, CollectorRegistry]:
    registry = CollectorRegistry()
    return EventMetrics(registry), registry


def count(registry: CollectorRegistry, name: str, event_type: str = "OrderCreated") -> float:
    return registry.get_sample_value(name, {"event_type": event_type}) or 0.0


def test_source_is_derived_from_the_producer() -> None:
    assert source_for("order-service") == "retail.order"
    assert source_for("inventory-service") == "retail.inventory"
    assert source_for("notification-service") == "retail.notification"


def test_entries_follow_the_documented_eventbridge_shape() -> None:
    client = FakeEvents()
    envelope = make_envelope()

    result = EventBridgePublisher(client, BUS).publish([envelope])

    (entry,) = client.calls[0]
    assert entry["Source"] == "retail.order"
    assert entry["DetailType"] == "OrderCreated"
    assert entry["EventBusName"] == BUS
    assert json.loads(entry["Detail"]) == json.loads(envelope.model_dump_json())
    assert result.succeeded == [envelope.event_id]
    assert result.failed == {}
    assert result.all_succeeded


def test_nothing_is_sent_for_an_empty_list() -> None:
    client = FakeEvents()
    result = EventBridgePublisher(client, BUS).publish([])
    assert client.calls == []
    assert result.all_succeeded


def test_large_lists_are_split_into_calls_of_at_most_ten() -> None:
    client = FakeEvents()
    envelopes = [make_envelope() for _ in range(25)]

    result = EventBridgePublisher(client, BUS).publish(envelopes)

    assert [len(call) for call in client.calls] == [10, 10, 5]
    assert result.succeeded == [e.event_id for e in envelopes]


def test_a_partial_putevents_failure_only_fails_the_rejected_entries() -> None:
    """PutEvents answers HTTP 200 with FailedEntryCount > 0; success is decided per entry."""

    def respond(_call: int, entries: list[dict[str, Any]]) -> dict[str, Any]:
        assert len(entries) == 4
        return {
            "FailedEntryCount": 2,
            "Entries": [
                {"EventId": "a"},
                {"ErrorCode": "ThrottlingException", "ErrorMessage": "slow down"},
                {"EventId": "c"},
                {"ErrorCode": "InternalFailure", "ErrorMessage": "oops"},
            ],
        }

    client = FakeEvents(respond)
    envelopes = [make_envelope() for _ in range(4)]
    event_metrics, registry = metrics()

    result = EventBridgePublisher(client, BUS, event_metrics).publish(envelopes)

    assert result.succeeded == [envelopes[0].event_id, envelopes[2].event_id]
    assert result.failed == {
        envelopes[1].event_id: "ThrottlingException",
        envelopes[3].event_id: "InternalFailure",
    }
    assert not result.all_succeeded
    assert count(registry, "events_published_total") == 2
    assert count(registry, "events_publish_failures_total") == 2


def test_partial_failure_in_a_later_batch_does_not_hide_earlier_successes() -> None:
    def respond(call: int, entries: list[dict[str, Any]]) -> dict[str, Any]:
        if call == 1:
            return {"FailedEntryCount": 0, "Entries": [{"EventId": "x"} for _ in entries]}
        return {
            "FailedEntryCount": 1,
            "Entries": [{"ErrorCode": "InternalFailure"}, *[{"EventId": "y"}] * (len(entries) - 1)],
        }

    envelopes = [make_envelope() for _ in range(13)]

    result = EventBridgePublisher(FakeEvents(respond), BUS).publish(envelopes)

    assert result.failed == {envelopes[10].event_id: "InternalFailure"}
    assert len(result.succeeded) == 12


def test_a_failed_call_fails_its_whole_batch_but_later_batches_still_go_out() -> None:
    def respond(call: int, entries: list[dict[str, Any]]) -> dict[str, Any]:
        if call == 1:
            raise client_error("ThrottlingException", "PutEvents")
        return {"FailedEntryCount": 0, "Entries": [{"EventId": "ok"} for _ in entries]}

    envelopes = [make_envelope() for _ in range(12)]

    result = EventBridgePublisher(FakeEvents(respond), BUS).publish(envelopes)

    assert set(result.failed) == {e.event_id for e in envelopes[:10]}
    assert set(result.failed.values()) == {"ClientError"}
    assert result.succeeded == [e.event_id for e in envelopes[10:]]


def test_a_connection_error_is_reported_not_raised() -> None:
    def respond(_call: int, _entries: list[dict[str, Any]]) -> dict[str, Any]:
        raise EndpointConnectionError(endpoint_url="http://localstack:4566")

    envelope = make_envelope()

    result = EventBridgePublisher(FakeEvents(respond), BUS).publish([envelope])

    assert result.failed == {envelope.event_id: "EndpointConnectionError"}
    assert result.succeeded == []


def test_a_short_response_never_counts_the_missing_entries_as_published() -> None:
    def respond(_call: int, _entries: list[dict[str, Any]]) -> dict[str, Any]:
        return {"FailedEntryCount": 0, "Entries": [{"EventId": "only-one"}]}

    envelopes = [make_envelope() for _ in range(3)]

    result = EventBridgePublisher(FakeEvents(respond), BUS).publish(envelopes)

    assert result.succeeded == [envelopes[0].event_id]
    assert set(result.failed) == {envelopes[1].event_id, envelopes[2].event_id}


def test_metrics_are_labelled_by_event_type() -> None:
    event_metrics, registry = metrics()
    envelopes = [make_envelope(), make_envelope("InventoryReserved", data={"x": 1})]

    EventBridgePublisher(FakeEvents(), BUS, event_metrics).publish(envelopes)

    assert count(registry, "events_published_total", "OrderCreated") == 1
    assert count(registry, "events_published_total", "InventoryReserved") == 1


@mock_aws
def test_the_real_eventbridge_api_accepts_our_entries() -> None:
    """Guards against a wrong parameter name or shape that a hand-written fake would accept."""
    client = boto3.client("events", region_name="us-east-1")
    client.create_event_bus(Name=BUS)
    envelopes = [make_envelope() for _ in range(3)]

    result = EventBridgePublisher(client, BUS).publish(envelopes)

    assert result.all_succeeded
    assert result.succeeded == [e.event_id for e in envelopes]
