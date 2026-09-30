"""EventBridge publisher with per-entry partial-failure handling (DESIGN.md section 6).

``PutEvents`` returns HTTP 200 even when some entries fail, reporting them in
``FailedEntryCount`` and per-entry ``ErrorCode``. So success is decided entry by entry: the caller
(the outbox relay, or the inventory consumer) marks only the returned ``succeeded`` ids as
published and retries the rest. A whole-call failure (network, throttling, auth) is reported the
same way, with every entry in ``failed``; ``publish`` never raises for delivery problems.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog
from botocore.exceptions import BotoCoreError, ClientError

from retail_common.events.envelope import Envelope
from retail_common.metrics import EventMetrics

_log = structlog.get_logger("retail_common.publisher")

MAX_ENTRIES_PER_CALL = 10  # PutEvents hard limit


@dataclass
class PublishResult:
    succeeded: list[str] = field(default_factory=list)  # event_ids the bus accepted
    failed: dict[str, str] = field(default_factory=dict)  # event_id -> error code/message

    @property
    def all_succeeded(self) -> bool:
        return not self.failed


class EventPublisher(Protocol):
    """The port services depend on; ``EventBridgePublisher`` is the AWS adapter."""

    def publish(self, envelopes: Sequence[Envelope]) -> PublishResult: ...


def source_for(producer: str) -> str:
    """``order-service`` -> ``retail.order`` (the EventBridge ``Source``)."""
    return "retail." + producer.removesuffix("-service")


class EventBridgePublisher:
    def __init__(self, client: Any, bus_name: str, metrics: EventMetrics | None = None) -> None:
        self._client = client
        self._bus_name = bus_name
        self._metrics = metrics

    def publish(self, envelopes: Sequence[Envelope]) -> PublishResult:
        result = PublishResult()
        for start in range(0, len(envelopes), MAX_ENTRIES_PER_CALL):
            self._publish_batch(envelopes[start : start + MAX_ENTRIES_PER_CALL], result)
        return result

    def _publish_batch(self, batch: Sequence[Envelope], result: PublishResult) -> None:
        entries = [
            {
                "Source": source_for(envelope.producer),
                "DetailType": envelope.event_type,
                "Detail": envelope.model_dump_json(),
                "EventBusName": self._bus_name,
            }
            for envelope in batch
        ]
        try:
            response = self._client.put_events(Entries=entries)
        except (BotoCoreError, ClientError) as exc:
            _log.warning("put_events_failed", error=type(exc).__name__, entries=len(batch))
            for envelope in batch:
                self._record_failure(result, envelope, type(exc).__name__)
            return

        response_entries: list[dict[str, Any]] = response.get("Entries", [])
        for index, envelope in enumerate(batch):
            # A missing or short response entry counts as a failure, never as success.
            entry = response_entries[index] if index < len(response_entries) else {}
            if entry.get("ErrorCode"):
                self._record_failure(result, envelope, str(entry["ErrorCode"]))
            elif entry.get("EventId"):
                result.succeeded.append(envelope.event_id)
                if self._metrics is not None:
                    self._metrics.published_total.labels(envelope.event_type).inc()
            else:
                self._record_failure(result, envelope, "NoEntryInResponse")

    def _record_failure(self, result: PublishResult, envelope: Envelope, error: str) -> None:
        result.failed[envelope.event_id] = error
        _log.warning(
            "event_publish_failed",
            event_id=envelope.event_id,
            event_type=envelope.event_type,
            error=error,
        )
        if self._metrics is not None:
            self._metrics.publish_failures_total.labels(envelope.event_type).inc()
