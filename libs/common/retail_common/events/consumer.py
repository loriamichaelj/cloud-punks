"""SQS consumer loop implementing the consumer contract (DESIGN.md section 6).

For every message:

1. Parse the EventBridge event from the SQS body and read ``detail`` as an ``Envelope``.
   Unparseable -> poison. An event type with no registered handler, or a schema major version
   this build does not know, is logged and **deleted** (not an error: dual-publishing relies on it).
2. Validate ``data`` against the Pydantic model. Invalid -> poison.
3. Call the handler. **Dedupe on ``event_id`` and the business write happen inside the handler,
   in one database transaction**; the handler reports ``DUPLICATE`` or ``PROCESSED``.
4. Only after the handler returns (its transaction committed) delete the SQS message.

Poison and transient failures both *leave the message undeleted*. SQS redelivers it after the
visibility timeout and moves it to the DLQ after ``maxReceiveCount``, so nothing is retried
in-process and nothing is ever lost. The difference is classification: poison is counted as
``outcome=poison`` and logged at error level, anything else the handler raises is ``error``.
"""

import json
import threading
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any, cast

import structlog
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ValidationError

from retail_common.errors import PoisonMessage, describe_validation_errors
from retail_common.events.envelope import Envelope
from retail_common.events.schemas import validate_data
from retail_common.logging import (
    is_valid_correlation_id,
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from retail_common.metrics import EventMetrics

_log = structlog.get_logger("retail_common.consumer")

UNKNOWN_EVENT_TYPE = "unknown"  # metric label when the envelope could not be parsed


class HandlerOutcome(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"


type Handler = Callable[[Envelope, BaseModel], HandlerOutcome]


def parse_envelope(body: str) -> Envelope:
    """Extract the envelope from an EventBridge-wrapped SQS body, or raise ``PoisonMessage``."""
    try:
        event = json.loads(body)
    except ValueError:
        raise PoisonMessage("message body is not valid JSON") from None
    detail = event.get("detail") if isinstance(event, dict) else None
    if not isinstance(detail, dict):
        raise PoisonMessage("message has no EventBridge 'detail' object")
    try:
        return Envelope.model_validate(detail)
    except ValidationError as exc:
        raise PoisonMessage(
            f"malformed envelope: {describe_validation_errors(exc.errors())}"
        ) from None


class SqsConsumer:
    def __init__(
        self,
        client: Any,
        queue_name: str,
        *,
        metrics: EventMetrics | None = None,
        wait_time_s: int = 20,
        batch_size: int = 10,
        error_backoff_s: float = 1.0,
    ) -> None:
        self._client = client
        self._queue_name = queue_name
        self._metrics = metrics
        self._wait_time_s = wait_time_s
        self._batch_size = batch_size
        self._error_backoff_s = error_backoff_s
        self._handlers: dict[str, Handler] = {}
        self._queue_url: str | None = None
        self._stopping = threading.Event()

    def register[T: BaseModel](
        self, event_type: str, handler: Callable[[Envelope, T], HandlerOutcome]
    ) -> None:
        """Register the handler for one event type; its payload arrives already validated."""
        self._handlers[event_type] = cast("Handler", handler)

    def start(self) -> None:
        """Resolve the queue URL once, so no LocalStack-specific URL format leaks into config."""
        self._queue_url = self._client.get_queue_url(QueueName=self._queue_name)["QueueUrl"]

    def stop(self) -> None:
        """Ask ``run`` to return after the batch in flight (wired to SIGTERM by the entrypoint)."""
        self._stopping.set()

    @property
    def stopping(self) -> bool:
        return self._stopping.is_set()

    def run(self) -> None:
        self.start()
        _log.info("consumer_started", queue=self._queue_name)
        while not self._stopping.is_set():
            self.poll_once()
        _log.info("consumer_stopped", queue=self._queue_name)

    def poll_once(self) -> int:
        """Receive one batch and process every message in it. Returns the number received."""
        if self._queue_url is None:
            self.start()
        try:
            response = self._client.receive_message(
                QueueUrl=self._queue_url,
                MaxNumberOfMessages=self._batch_size,
                WaitTimeSeconds=self._wait_time_s,
                AttributeNames=["ApproximateReceiveCount"],
            )
        except (BotoCoreError, ClientError) as exc:
            _log.error("receive_failed", queue=self._queue_name, error=type(exc).__name__)
            self._stopping.wait(self._error_backoff_s)  # returns early if stop() is called
            return 0

        messages: list[dict[str, Any]] = response.get("Messages", [])
        for message in messages:  # the whole batch is finished even if stop() is called
            self._process(message)
        return len(messages)

    def _count(self, event_type: str, outcome: str) -> None:
        if self._metrics is not None:
            self._metrics.consumed_total.labels(event_type, outcome).inc()

    def _process(self, message: dict[str, Any]) -> None:
        # Every message starts from a fresh correlation context and leaves the caller's context
        # exactly as it found it, so one message's id can never label another's log lines.
        token = set_correlation_id(new_correlation_id())
        try:
            self._handle_message(message)
        finally:
            reset_correlation_id(token)

    def _handle_message(self, message: dict[str, Any]) -> None:
        message_id = message.get("MessageId")
        receive_count = message.get("Attributes", {}).get("ApproximateReceiveCount")

        try:
            envelope = parse_envelope(message["Body"])
        except PoisonMessage as exc:
            self._count(UNKNOWN_EVENT_TYPE, EventMetrics.POISON)
            _log.error(
                "poison_message",
                message_id=message_id,
                receive_count=receive_count,
                reason=str(exc),
            )
            return

        if is_valid_correlation_id(envelope.correlation_id):
            set_correlation_id(envelope.correlation_id)  # propagate the originating request's id
        log = _log.bind(
            event_id=envelope.event_id,
            event_type=envelope.event_type,
            message_id=message_id,
            receive_count=receive_count,
        )

        handler = self._handlers.get(envelope.event_type)
        if handler is None:
            log.info("event_ignored", reason="no handler for event type")
            self._delete(message, log)
            return

        try:
            data = validate_data(envelope)
        except PoisonMessage as exc:
            self._count(envelope.event_type, EventMetrics.POISON)
            log.error("poison_message", reason=str(exc))
            return
        if data is None:
            log.info(
                "event_ignored",
                reason="unsupported schema version",
                version=envelope.schema_version,
            )
            self._delete(message, log)
            return

        started = time.perf_counter()
        try:
            outcome = handler(envelope, data)
        except PoisonMessage as exc:
            self._count(envelope.event_type, EventMetrics.POISON)
            log.error("poison_message", reason=str(exc))
            return
        except Exception:
            self._count(envelope.event_type, EventMetrics.ERROR)
            log.exception("handler_failed")
            return
        finally:
            if self._metrics is not None:
                self._metrics.handler_duration.labels(envelope.event_type).observe(
                    time.perf_counter() - started
                )

        self._count(envelope.event_type, outcome.value)
        log.info("event_handled", outcome=outcome.value)
        self._delete(message, log)

    def _delete(self, message: dict[str, Any], log: Any) -> None:
        try:
            self._client.delete_message(
                QueueUrl=self._queue_url, ReceiptHandle=message["ReceiptHandle"]
            )
        except (BotoCoreError, ClientError) as exc:
            # Safe: the message is redelivered and the handler's dedupe absorbs the repeat.
            log.warning("delete_failed", error=type(exc).__name__)
