"""The outbox relay loop (DESIGN.md section 6, "Order Service outbox relay").

Each pass claims up to 50 unpublished rows with ``FOR UPDATE SKIP LOCKED`` (so several relay
replicas can run side by side), publishes them with ``PutEvents`` (at most 10 per call), and marks
published only the rows the bus accepted. Failed rows stay unpublished with ``attempts`` and
``last_error`` updated, to be retried.

Delivery is at-least-once: if the process dies after ``PutEvents`` succeeds and before the
``UPDATE`` commits, the rows are published again. Every consumer is idempotent on ``event_id``
(ADR-07), which is exactly why that is acceptable.
"""

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import structlog
from pydantic import ValidationError

from retail_common.events.envelope import Envelope
from retail_common.events.publisher import EventPublisher

_log = structlog.get_logger("outbox_relay")

BATCH_SIZE = 50
POLL_INTERVAL_S = 0.5  # idle wait
MAX_BACKOFF_S = 10.0
RETENTION = timedelta(days=7)
CLEANUP_INTERVAL_S = 60.0
CLEANUP_BATCH = 1000


@dataclass(frozen=True)
class OutboxRow:
    id: int
    event_id: str
    payload: dict[str, Any]


class OutboxBatch(Protocol):
    rows: Sequence[OutboxRow]

    def mark_published(self, ids: Sequence[int]) -> None: ...

    def mark_failed(self, failures: Mapping[int, str]) -> None: ...


class OutboxStore(Protocol):
    def claim(self, limit: int) -> AbstractContextManager[OutboxBatch]:
        """Lock up to ``limit`` unpublished rows, oldest first, for the life of the context.
        Leaving the context normally commits the marks; leaving it by exception rolls back."""
        ...

    def delete_published_before(self, cutoff: datetime, limit: int) -> int: ...


@dataclass(frozen=True)
class PassResult:
    published: int = 0
    failed: int = 0

    @property
    def idle(self) -> bool:
        return self.published == 0 and self.failed == 0


class OutboxRelay:
    def __init__(
        self,
        store: OutboxStore,
        publisher: EventPublisher,
        *,
        batch_size: int = BATCH_SIZE,
        poll_interval_s: float = POLL_INTERVAL_S,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._publisher = publisher
        self._batch_size = batch_size
        self._poll_interval_s = poll_interval_s
        self._clock = clock
        self._monotonic = monotonic
        self._stopping = threading.Event()
        self._next_cleanup = 0.0

    def stop(self) -> None:
        self._stopping.set()

    @property
    def stopping(self) -> bool:
        return self._stopping.is_set()

    def run_once(self) -> PassResult:
        """One claim-publish-mark pass inside one transaction."""
        with self._store.claim(self._batch_size) as batch:
            if not batch.rows:
                return PassResult()

            failures: dict[int, str] = {}
            envelopes: list[tuple[OutboxRow, Envelope]] = []
            for row in batch.rows:
                try:
                    envelopes.append((row, Envelope.model_validate(row.payload)))
                except ValidationError:
                    # A row that can never be published must not block the rows behind it.
                    failures[row.id] = "invalid envelope in outbox payload"

            result = self._publisher.publish([envelope for _, envelope in envelopes])
            published: list[int] = []
            for row, envelope in envelopes:
                if envelope.event_id in result.succeeded:
                    published.append(row.id)
                else:
                    failures[row.id] = result.failed.get(envelope.event_id, "not acknowledged")

            batch.mark_published(published)
            batch.mark_failed(failures)

        if failures:
            _log.warning("outbox_publish_failures", failed=len(failures), published=len(published))
        return PassResult(published=len(published), failed=len(failures))

    def cleanup(self) -> int:
        """Delete rows published more than 7 days ago, in batches of 1,000. Without this every
        publish leaves a dead tuple and relay latency creeps up over weeks (section 5)."""
        cutoff = self._clock() - RETENTION
        total = 0
        while True:
            deleted = self._store.delete_published_before(cutoff, CLEANUP_BATCH)
            total += deleted
            if deleted < CLEANUP_BATCH:
                return total

    def run(self) -> None:
        backoff = self._poll_interval_s
        while not self._stopping.is_set():
            try:
                result = self.run_once()
                self._maybe_cleanup()
            except Exception:  # noqa: BLE001 - a bug or an outage must not kill the relay; it is logged below
                _log.exception("relay_pass_failed")
                self._stopping.wait(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)
                continue

            if result.published:
                backoff = self._poll_interval_s
                continue  # more may be waiting: go again immediately
            if result.failed:
                # Everything we tried was rejected (bus down?): back off instead of hammering.
                self._stopping.wait(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)
            else:
                backoff = self._poll_interval_s
                self._stopping.wait(self._poll_interval_s)

    def _maybe_cleanup(self) -> None:
        now = self._monotonic()
        if now >= self._next_cleanup:
            self._next_cleanup = now + CLEANUP_INTERVAL_S
            deleted = self.cleanup()
            if deleted:
                _log.info("outbox_cleanup", deleted=deleted)
