import contextvars
import json
from collections.abc import Callable
from typing import Any

import boto3
import pytest
from helpers import FakeSqs, client_error, make_envelope, order_created_data, sqs_body
from moto import mock_aws
from prometheus_client import CollectorRegistry
from pydantic import BaseModel

from retail_common.errors import PoisonMessage
from retail_common.events.consumer import HandlerOutcome, SqsConsumer, parse_envelope
from retail_common.events.envelope import Envelope
from retail_common.events.schemas import OrderCreatedData
from retail_common.logging import get_correlation_id, set_correlation_id
from retail_common.metrics import EventMetrics

QUEUE = "inventory-order-events"
Logs = Callable[[], list[dict[str, Any]]]


class Recorder:
    """A handler that records what it saw, and can be told to misbehave."""

    def __init__(self, log: list[str] | None = None) -> None:
        self.log = log if log is not None else []
        self.seen: list[tuple[Envelope, BaseModel, str | None]] = []
        self.outcome = HandlerOutcome.PROCESSED
        self.raises: Exception | None = None
        self.side_effect: Callable[[Envelope], None] | None = None

    def __call__(self, envelope: Envelope, data: OrderCreatedData) -> HandlerOutcome:
        self.log.append(f"handle:{envelope.event_id}")
        self.seen.append((envelope, data, get_correlation_id()))
        if self.side_effect is not None:
            self.side_effect(envelope)
        if self.raises is not None:
            raise self.raises
        return self.outcome


def build(
    bodies: list[str], handler: Recorder | None = None, *, log: list[str] | None = None
) -> tuple[SqsConsumer, FakeSqs, Recorder, CollectorRegistry]:
    log = log if log is not None else []
    sqs = FakeSqs(bodies, log=log)
    handler = handler or Recorder(log)
    registry = CollectorRegistry()
    consumer = SqsConsumer(sqs, QUEUE, metrics=EventMetrics(registry), error_backoff_s=0)
    consumer.register("OrderCreated", handler)
    return consumer, sqs, handler, registry


def outcome_count(registry: CollectorRegistry, event_type: str, outcome: str) -> float:
    labels = {"event_type": event_type, "outcome": outcome}
    return registry.get_sample_value("events_consumed_total", labels) or 0.0


# --- the happy path and the ordering guarantee --------------------------------------------


def test_a_valid_event_reaches_the_handler_with_typed_data_then_is_deleted() -> None:
    envelope = make_envelope()
    consumer, sqs, handler, registry = build([sqs_body(envelope)])

    assert consumer.poll_once() == 1

    ((seen, data, _),) = handler.seen
    assert seen == envelope
    assert isinstance(data, OrderCreatedData)
    assert sqs.deleted == ["rh-0"]
    assert outcome_count(registry, "OrderCreated", "processed") == 1


def test_the_message_is_deleted_only_after_the_handler_returns() -> None:
    """Delete-after-commit: if the handler dies, the message must still be in the queue."""
    log: list[str] = []
    envelope = make_envelope()
    consumer, _, _, _ = build([sqs_body(envelope)], log=log)

    consumer.poll_once()

    assert log == [f"handle:{envelope.event_id}", "delete:rh-0"]


def test_receive_uses_long_polling_and_the_resolved_queue_url() -> None:
    consumer, sqs, _, _ = build([])

    assert consumer.poll_once() == 0

    (call,) = sqs.receive_calls
    assert call["QueueUrl"] == f"http://sqs.test/000000000000/{QUEUE}"
    assert call["WaitTimeSeconds"] == 20
    assert call["MaxNumberOfMessages"] == 10


def test_a_duplicate_is_acknowledged_deleted_and_counted_as_duplicate() -> None:
    handler = Recorder()
    handler.outcome = HandlerOutcome.DUPLICATE
    consumer, sqs, _, registry = build([sqs_body(make_envelope())], handler)

    consumer.poll_once()

    assert sqs.deleted == ["rh-0"]
    assert outcome_count(registry, "OrderCreated", "duplicate") == 1
    assert outcome_count(registry, "OrderCreated", "processed") == 0


def test_the_whole_batch_is_processed_in_order() -> None:
    envelopes = [make_envelope() for _ in range(3)]
    consumer, sqs, handler, _ = build([sqs_body(e) for e in envelopes])

    assert consumer.poll_once() == 3

    assert [seen.event_id for seen, _, _ in handler.seen] == [e.event_id for e in envelopes]
    assert sqs.deleted == ["rh-0", "rh-1", "rh-2"]


# --- events this consumer does not handle are not errors ------------------------------------


def test_an_event_type_without_a_handler_is_logged_and_deleted() -> None:
    other = make_envelope("InventoryReserved", data={"anything": 1})
    consumer, sqs, handler, registry = build([sqs_body(other)])

    consumer.poll_once()

    assert handler.seen == []
    assert sqs.deleted == ["rh-0"]
    assert outcome_count(registry, "InventoryReserved", "poison") == 0
    assert outcome_count(registry, "InventoryReserved", "error") == 0


def test_an_unsupported_schema_major_version_is_skipped_and_deleted() -> None:
    v2 = make_envelope(schema_version="2.0")
    consumer, sqs, handler, _ = build([sqs_body(v2)])

    consumer.poll_once()

    assert handler.seen == []
    assert sqs.deleted == ["rh-0"]


# --- poison: can never succeed, so never retried in-process and never deleted ---------------


@pytest.mark.parametrize(
    "body",
    [
        "this is not json",
        json.dumps(["not", "an", "object"]),
        json.dumps({"detail-type": "OrderCreated"}),  # no detail
        json.dumps({"detail": "a string, not an object"}),
        json.dumps({"detail": {"event_id": "missing-everything-else"}}),
    ],
)
def test_unparseable_messages_are_poison_and_left_in_the_queue(body: str) -> None:
    consumer, sqs, handler, registry = build([body])

    consumer.poll_once()

    assert handler.seen == []
    assert sqs.deleted == []  # SQS redelivers it and moves it to the DLQ after maxReceiveCount
    assert outcome_count(registry, "unknown", "poison") == 1


def test_a_payload_that_fails_validation_is_poison() -> None:
    bad = make_envelope(data=order_created_data(items=[]))
    consumer, sqs, handler, registry = build([sqs_body(bad)])

    consumer.poll_once()

    assert handler.seen == []
    assert sqs.deleted == []
    assert outcome_count(registry, "OrderCreated", "poison") == 1


def test_a_handler_can_declare_a_message_poison() -> None:
    handler = Recorder()
    handler.raises = PoisonMessage("references an order that can never exist")
    consumer, sqs, _, registry = build([sqs_body(make_envelope())], handler)

    consumer.poll_once()

    assert sqs.deleted == []
    assert outcome_count(registry, "OrderCreated", "poison") == 1
    assert outcome_count(registry, "OrderCreated", "error") == 0


def test_one_poison_message_does_not_block_the_messages_behind_it() -> None:
    good = make_envelope()
    consumer, sqs, handler, _ = build(["garbage", sqs_body(good)])

    consumer.poll_once()

    assert [seen.event_id for seen, _, _ in handler.seen] == [good.event_id]
    assert sqs.deleted == ["rh-1"]


def test_poison_logs_never_contain_the_message_body(read_logs: Logs) -> None:
    bad = make_envelope(data=order_created_data(customer_id="", currency="SECRET-CARD-1234"))
    consumer, _, _, _ = build([sqs_body(bad)])

    consumer.poll_once()

    lines = read_logs()
    poison = next(line for line in lines if line["message"] == "poison_message")
    assert poison["level"] == "error"
    assert poison["event_id"] == bad.event_id
    assert "SECRET-CARD-1234" not in json.dumps(lines)


# --- transient: may succeed later, so the message stays for SQS to redeliver ----------------


def test_a_failing_handler_leaves_the_message_for_redelivery() -> None:
    handler = Recorder()
    handler.raises = ConnectionError("database is down")
    consumer, sqs, _, registry = build([sqs_body(make_envelope())], handler)

    consumer.poll_once()

    assert sqs.deleted == []
    assert outcome_count(registry, "OrderCreated", "error") == 1
    assert outcome_count(registry, "OrderCreated", "poison") == 0


def test_a_transient_failure_does_not_stop_the_rest_of_the_batch() -> None:
    first, second = make_envelope(), make_envelope()
    handler = Recorder()

    def fail_on_first(envelope: Envelope) -> None:
        if envelope.event_id == first.event_id:
            raise RuntimeError("boom")

    handler.side_effect = fail_on_first
    consumer, sqs, _, _ = build([sqs_body(first), sqs_body(second)], handler)

    consumer.poll_once()

    assert [seen.event_id for seen, _, _ in handler.seen] == [first.event_id, second.event_id]
    assert sqs.deleted == ["rh-1"]  # only the one that succeeded


def test_transient_failures_are_logged_with_the_traceback(read_logs: Logs) -> None:
    handler = Recorder()
    handler.raises = ConnectionError("database is down")
    consumer, _, _, _ = build([sqs_body(make_envelope())], handler)

    consumer.poll_once()

    failure = next(line for line in read_logs() if line["message"] == "handler_failed")
    assert failure["level"] == "error"
    assert "ConnectionError: database is down" in failure["exception"]


def test_the_handler_duration_is_observed_even_when_it_fails() -> None:
    handler = Recorder()
    handler.raises = RuntimeError("boom")
    consumer, _, _, registry = build([sqs_body(make_envelope())], handler)

    consumer.poll_once()

    count = registry.get_sample_value(
        "event_handler_duration_seconds_count", {"event_type": "OrderCreated"}
    )
    assert count == 1


def test_a_failed_delete_is_survivable_because_redelivery_is_deduplicated() -> None:
    consumer, sqs, handler, registry = build([sqs_body(make_envelope())])
    sqs.delete_error = client_error("ReceiptHandleIsInvalid", "DeleteMessage")

    assert consumer.poll_once() == 1

    assert len(handler.seen) == 1
    assert outcome_count(registry, "OrderCreated", "processed") == 1


def test_a_receive_error_is_absorbed_and_the_loop_can_continue() -> None:
    consumer, sqs, _, _ = build([sqs_body(make_envelope())])
    sqs.receive_error = client_error("ServiceUnavailable", "ReceiveMessage")

    assert consumer.poll_once() == 0

    sqs.receive_error = None
    assert consumer.poll_once() == 1


# --- correlation propagation ----------------------------------------------------------------


def test_the_handler_runs_under_the_events_correlation_id() -> None:
    envelope = make_envelope(correlation_id="corr-from-the-original-request")
    consumer, _, handler, _ = build([sqs_body(envelope)])

    consumer.poll_once()

    assert handler.seen[0][2] == "corr-from-the-original-request"


def test_each_message_gets_its_own_correlation_id_with_no_leakage() -> None:
    first = make_envelope(correlation_id="corr-one")
    second = make_envelope(correlation_id="corr-two")
    consumer, _, handler, _ = build([sqs_body(first), sqs_body(second)])

    consumer.poll_once()

    assert [seen[2] for seen in handler.seen] == ["corr-one", "corr-two"]


def test_the_callers_correlation_context_is_restored_after_each_message() -> None:
    """A consumer thread must not keep the last message's id attached to later log lines."""

    def run() -> tuple[str | None, str | None]:
        set_correlation_id("caller-context")
        consumer, _, _, _ = build([sqs_body(make_envelope(correlation_id="corr-msg"))])
        consumer.poll_once()
        after_message = get_correlation_id()

        bare_consumer, _, _, _ = build(["garbage"])  # the poison path also restores it
        bare_consumer.poll_once()
        return after_message, get_correlation_id()

    assert contextvars.copy_context().run(run) == ("caller-context", "caller-context")


def test_an_unsafe_correlation_id_in_an_event_is_not_adopted() -> None:
    first = make_envelope(correlation_id="corr-one")
    hostile = make_envelope(correlation_id="evil id\twith spaces")
    consumer, _, handler, _ = build([sqs_body(first), sqs_body(hostile)])

    consumer.poll_once()

    adopted = handler.seen[1][2]
    assert adopted not in {"corr-one", "evil id\twith spaces"}
    assert adopted is not None


def test_a_follow_up_event_built_in_the_handler_inherits_the_correlation_id() -> None:
    incoming = make_envelope(correlation_id="corr-chain")
    follow_ups: list[Envelope] = []
    handler = Recorder()
    handler.side_effect = lambda e: follow_ups.append(
        Envelope.create(
            event_type="InventoryReserved",
            producer="inventory-service",
            data={"x": 1},
            causation_id=e.event_id,
        )
    )
    consumer, _, _, _ = build([sqs_body(incoming)], handler)

    consumer.poll_once()

    assert follow_ups[0].correlation_id == "corr-chain"
    assert follow_ups[0].causation_id == incoming.event_id


def test_consumer_log_lines_carry_the_event_and_correlation_ids(read_logs: Logs) -> None:
    envelope = make_envelope(correlation_id="corr-logs")
    consumer, _, _, _ = build([sqs_body(envelope)])

    consumer.poll_once()

    handled = next(line for line in read_logs() if line["message"] == "event_handled")
    assert handled["correlation_id"] == "corr-logs"
    assert handled["event_id"] == envelope.event_id
    assert handled["event_type"] == "OrderCreated"
    assert handled["outcome"] == "processed"


# --- lifecycle --------------------------------------------------------------------------------


def test_run_stops_when_asked_between_polls() -> None:
    consumer, sqs, _, _ = build([])
    sqs.on_receive = lambda n: consumer.stop() if n == 3 else None

    consumer.run()

    assert len(sqs.receive_calls) == 3
    assert consumer.stopping


def test_stop_finishes_the_batch_in_flight() -> None:
    """Graceful shutdown: SIGTERM must not abandon messages half-way through a batch."""
    first, second = make_envelope(), make_envelope()
    handler = Recorder()
    handler.side_effect = lambda _e: consumer.stop()
    consumer, sqs, _, _ = build([sqs_body(first), sqs_body(second)], handler)

    consumer.run()

    assert [seen.event_id for seen, _, _ in handler.seen] == [first.event_id, second.event_id]
    assert sqs.deleted == ["rh-0", "rh-1"]
    assert len(sqs.receive_calls) == 1  # and it did not start another poll


def test_parse_envelope_reads_the_detail_object() -> None:
    envelope = make_envelope()
    assert parse_envelope(sqs_body(envelope)) == envelope


# --- against the real SQS API semantics (moto) ------------------------------------------------


def queue_counts(client: Any, url: str) -> tuple[int, int]:
    attrs = client.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])["Attributes"]
    return (
        int(attrs["ApproximateNumberOfMessages"]),
        int(attrs["ApproximateNumberOfMessagesNotVisible"]),
    )


@mock_aws
def test_against_real_sqs_a_handled_message_is_gone_and_a_poison_one_stays_in_flight() -> None:
    client = boto3.client("sqs", region_name="us-east-1")
    url = client.create_queue(QueueName=QUEUE, Attributes={"VisibilityTimeout": "60"})["QueueUrl"]
    good = make_envelope()
    client.send_message(QueueUrl=url, MessageBody=sqs_body(good))
    client.send_message(QueueUrl=url, MessageBody="garbage")
    handler = Recorder()
    consumer = SqsConsumer(client, QUEUE, wait_time_s=0, error_backoff_s=0)
    consumer.register("OrderCreated", handler)

    assert consumer.poll_once() == 2

    assert [seen.event_id for seen, _, _ in handler.seen] == [good.event_id]
    # The good message was deleted; the poison one is invisible (in flight) until its visibility
    # timeout expires, after which SQS redelivers it toward the DLQ.
    assert queue_counts(client, url) == (0, 1)
