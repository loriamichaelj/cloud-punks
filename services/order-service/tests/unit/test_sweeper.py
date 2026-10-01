"""The stuck-order sweeper with a fake store: no database, no clock."""

from datetime import timedelta

import pytest
from prometheus_client import CollectorRegistry, Gauge

from app.relay.sweeper import LOGGED_IDS, STUCK_AFTER, StuckOrders, StuckOrderSweeper


class FakeStore:
    def __init__(self, result: StuckOrders | Exception) -> None:
        self.result = result
        self.asked: list[tuple[timedelta, int]] = []

    def stuck_orders(self, older_than: timedelta, sample: int) -> StuckOrders:
        self.asked.append((older_than, sample))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def make(result: StuckOrders | Exception) -> tuple[StuckOrderSweeper, Gauge, FakeStore]:
    gauge = Gauge("orders_stuck", "x", registry=CollectorRegistry())
    store = FakeStore(result)
    return StuckOrderSweeper(store, gauge), gauge, store


def test_the_gauge_counts_orders_pending_longer_than_five_minutes() -> None:
    sweeper, gauge, store = make(StuckOrders(3, 912.0, ("A", "B", "C")))

    found = sweeper.sweep()

    assert found is not None
    assert found.count == 3
    assert gauge._value.get() == 3
    assert store.asked == [(STUCK_AFTER, LOGGED_IDS)]
    assert timedelta(minutes=5) == STUCK_AFTER


def test_the_gauge_returns_to_zero_when_the_orders_clear() -> None:
    sweeper, gauge, store = make(StuckOrders(2, 400.0, ("A", "B")))
    sweeper.sweep()
    store.result = StuckOrders(0, None, ())

    sweeper.sweep()

    assert gauge._value.get() == 0


def test_a_database_outage_makes_the_gauge_unknown_not_zero() -> None:
    sweeper, gauge, store = make(StuckOrders(0, None, ()))
    sweeper.sweep()
    store.result = RuntimeError("db down")

    assert sweeper.sweep() is None

    assert gauge._value.get() != gauge._value.get()


def test_a_stuck_batch_is_logged_with_a_bounded_list_of_ids(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sweeper, _, _ = make(StuckOrders(50, 700.0, tuple(f"O{i}" for i in range(LOGGED_IDS))))

    sweeper.sweep()

    out = capsys.readouterr().out
    assert '"message": "orders_stuck"' in out
    assert '"count": 50' in out
    assert '"order_ids": ["O0"' in out


def test_stop_ends_the_loop_after_the_current_sweep() -> None:
    sweeper, _, store = make(StuckOrders(0, None, ()))
    sweeper.stop()

    sweeper.run()

    assert store.asked == []
