from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fakes import FakeOutboxStore
from ulid import ULID

from app.relay.core import BATCH_SIZE, OutboxRelay, OutboxRow, PassResult
from retail_common.events.envelope import Envelope
from retail_common.events.publisher import PublishResult


def make_row(row_id: int) -> OutboxRow:
    envelope = Envelope.create(
        event_type="OrderCreated",
        producer="order-service",
        data={"n": row_id},
        correlation_id=f"corr-{row_id}",
    )
    return OutboxRow(
        id=row_id, event_id=envelope.event_id, payload=envelope.model_dump(mode="json")
    )


class FakePublisher:
    """Accepts everything except the event ids it is told to reject."""

    def __init__(self, reject: dict[str, str] | None = None) -> None:
        self.reject = reject or {}
        self.batches: list[list[str]] = []
        self.explode: Exception | None = None

    def publish(self, envelopes: Any) -> PublishResult:
        if self.explode is not None:
            raise self.explode
        ids = [e.event_id for e in envelopes]
        self.batches.append(ids)
        result = PublishResult()
        for event_id in ids:
            if event_id in self.reject:
                result.failed[event_id] = self.reject[event_id]
            else:
                result.succeeded.append(event_id)
        return result


def relay(store: FakeOutboxStore, publisher: FakePublisher, **kwargs: Any) -> OutboxRelay:
    return OutboxRelay(store, publisher, poll_interval_s=0.001, **kwargs)  # type: ignore[arg-type]


# --- one pass ---------------------------------------------------------------------------------


def test_every_accepted_row_is_marked_published() -> None:
    rows = [make_row(i) for i in (1, 2, 3)]
    store, publisher = FakeOutboxStore(rows), FakePublisher()

    result = relay(store, publisher).run_once()

    assert result == PassResult(published=3, failed=0)
    assert store.published_ids == {1, 2, 3}
    assert publisher.batches == [[r.event_id for r in rows]]  # oldest first, in id order


def test_a_partial_putevents_failure_marks_only_the_successful_rows_published() -> None:
    """PutEvents answers 200 with per-entry failures. Only the accepted rows may be marked."""
    rows = [make_row(i) for i in (1, 2, 3, 4)]
    store = FakeOutboxStore(rows)
    publisher = FakePublisher(
        reject={rows[1].event_id: "ThrottlingException", rows[3].event_id: "InternalFailure"}
    )

    result = relay(store, publisher).run_once()

    assert result == PassResult(published=2, failed=2)
    assert store.published_ids == {1, 3}  # 2 and 4 were rejected and stay unpublished
    assert store.errors == {2: "ThrottlingException", 4: "InternalFailure"}
    assert store.attempts == {2: 1, 4: 1}


def test_rejected_rows_are_retried_on_the_next_pass_and_attempts_accumulate() -> None:
    rows = [make_row(1), make_row(2)]
    store = FakeOutboxStore(rows)
    publisher = FakePublisher(reject={rows[1].event_id: "ThrottlingException"})
    r = relay(store, publisher)
    r.run_once()

    publisher.reject = {rows[1].event_id: "ThrottlingException"}
    r.run_once()  # still failing
    publisher.reject = {}
    last = r.run_once()  # the bus recovers

    assert last == PassResult(published=1, failed=0)
    assert store.published_ids == {1, 2}
    assert store.attempts[2] == 2  # two failed attempts before the one that worked


def test_when_the_whole_bus_is_down_every_row_stays_unpublished_with_the_error() -> None:
    rows = [make_row(i) for i in (1, 2)]
    store = FakeOutboxStore(rows)
    publisher = FakePublisher(reject={r.event_id: "EndpointConnectionError" for r in rows})

    result = relay(store, publisher).run_once()

    assert result == PassResult(published=0, failed=2)
    assert store.published_ids == set()
    assert store.errors == {1: "EndpointConnectionError", 2: "EndpointConnectionError"}


def test_a_row_with_a_broken_envelope_is_failed_without_blocking_the_rest() -> None:
    good, broken = make_row(1), OutboxRow(id=2, event_id="X" * 26, payload={"not": "an envelope"})
    store, publisher = FakeOutboxStore([broken, good]), FakePublisher()

    result = relay(store, publisher).run_once()

    assert result == PassResult(published=1, failed=1)
    assert store.published_ids == {1}
    assert "invalid envelope" in store.errors[2]
    assert publisher.batches == [[good.event_id]]  # the broken row never reached the bus


def test_an_empty_outbox_does_nothing() -> None:
    store, publisher = FakeOutboxStore(), FakePublisher()
    result = relay(store, publisher).run_once()
    assert result.idle
    assert publisher.batches == []


def test_a_pass_claims_at_most_one_batch() -> None:
    store = FakeOutboxStore([make_row(i) for i in range(1, 121)])
    relay(store, FakePublisher()).run_once()
    assert store.claim_limits == [BATCH_SIZE] == [50]
    assert len(store.published_ids) == 50


def test_a_crash_while_publishing_rolls_the_claim_back_so_nothing_is_lost() -> None:
    store, publisher = FakeOutboxStore([make_row(1)]), FakePublisher()
    publisher.explode = RuntimeError("process dying mid-publish")

    with pytest.raises(RuntimeError):
        relay(store, publisher).run_once()

    assert store.rollbacks == 1
    assert store.published_ids == set()  # nothing marked: the row will be published again


# --- the loop ---------------------------------------------------------------------------------


class StoppingStore(FakeOutboxStore):
    """Stops the relay after a number of claims, so ``run()`` terminates deterministically."""

    def __init__(self, rows: list[OutboxRow], stop_after: int) -> None:
        super().__init__(rows)
        self.stop_after = stop_after
        self.relay: OutboxRelay | None = None

    def claim(self, limit: int) -> Any:
        if len(self.claim_limits) + 1 >= self.stop_after and self.relay is not None:
            self.relay.stop()
        return super().claim(limit)


def test_run_drains_the_outbox_and_stops_when_asked() -> None:
    rows = [make_row(i) for i in range(1, 121)]
    store = StoppingStore(rows, stop_after=5)
    r = relay(store, FakePublisher())
    store.relay = r

    r.run()

    assert len(store.published_ids) == 120  # 50 + 50 + 20, back to back
    assert r.stopping


def test_a_failing_pass_does_not_kill_the_loop() -> None:
    store = StoppingStore([make_row(1)], stop_after=4)
    publisher = FakePublisher()
    publisher.explode = ConnectionError("bus and database blip")
    r = relay(store, publisher)
    store.relay = r

    def recover() -> None:
        publisher.explode = None

    # fail the first passes, then recover: the relay must survive and finish the work
    original = store.claim
    calls = {"n": 0}

    def claim(limit: int) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:
            recover()
        return original(limit)

    store.claim = claim  # type: ignore[method-assign]

    r.run()

    assert store.published_ids == {1}
    assert store.rollbacks >= 1


# --- cleanup of old published rows ------------------------------------------------------------


def test_cleanup_deletes_rows_published_more_than_seven_days_ago_in_batches_of_1000() -> None:
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    store = FakeOutboxStore()
    store.delete_results = [1000, 1000, 342]

    deleted = relay(store, FakePublisher(), clock=lambda: now).cleanup()

    assert deleted == 2342
    assert [limit for _, limit in store.deleted_calls] == [1000, 1000, 1000]
    assert {cutoff for cutoff, _ in store.deleted_calls} == {now - timedelta(days=7)}


def test_cleanup_stops_after_a_short_batch() -> None:
    store = FakeOutboxStore()
    store.delete_results = [10]
    assert relay(store, FakePublisher()).cleanup() == 10
    assert len(store.deleted_calls) == 1


def test_the_loop_runs_cleanup_at_most_once_a_minute() -> None:
    clock = {"t": 0.0}
    store = StoppingStore([], stop_after=6)
    r = relay(store, FakePublisher(), monotonic=lambda: clock["t"])
    store.relay = r
    original = store.claim

    def claim(limit: int) -> Any:
        clock["t"] += 20.0  # every pass takes 20 s
        return original(limit)

    store.claim = claim  # type: ignore[method-assign]
    r.run()

    # passes at t = 20, 40, 60, 80, 100, 120 -> cleanups at t = 20, 80 (>= 60 s apart)
    assert len(store.deleted_calls) == 2


def test_event_ids_are_ulids() -> None:
    assert len(str(ULID())) == 26  # sanity for the generator the fixtures rely on
