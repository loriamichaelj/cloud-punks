"""The stuck-order sweeper (DESIGN.md section 8, Resilience).

Every 60 s it counts orders that have been ``PENDING`` for more than 5 minutes, sets the
``orders_stuck`` gauge and logs them. It changes nothing: no auto-reject this week. The gauge is
the alarm source for the stuck-queue runbook, and the usual cause is a consumer that is down.
"""

import threading
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

import structlog
from prometheus_client import Gauge

_log = structlog.get_logger("stuck_order_sweeper")

STUCK_AFTER = timedelta(minutes=5)
SWEEP_INTERVAL_S = 60.0
LOGGED_IDS = 10  # enough to find the cause, bounded so one outage cannot flood the log


@dataclass(frozen=True)
class StuckOrders:
    count: int
    oldest_age_s: float | None
    sample_ids: tuple[str, ...]


class StuckOrderStore(Protocol):
    def stuck_orders(self, older_than: timedelta, sample: int) -> StuckOrders: ...


class StuckOrderSweeper:
    def __init__(
        self,
        store: StuckOrderStore,
        gauge: Gauge,
        *,
        stuck_after: timedelta = STUCK_AFTER,
        interval_s: float = SWEEP_INTERVAL_S,
    ) -> None:
        self._store = store
        self._gauge = gauge
        self._stuck_after = stuck_after
        self._interval_s = interval_s
        self._stopping = threading.Event()

    def stop(self) -> None:
        self._stopping.set()

    def sweep(self) -> StuckOrders | None:
        """One pass. A database outage sets the gauge to NaN (unknown, not zero) and returns
        ``None``: reporting "0 stuck" while blind would hide exactly the incident it is for."""
        try:
            found = self._store.stuck_orders(self._stuck_after, LOGGED_IDS)
        except Exception:  # noqa: BLE001 - the sweeper must outlive any database trouble
            self._gauge.set(float("nan"))
            _log.exception("stuck_order_sweep_failed")
            return None
        self._gauge.set(found.count)
        if found.count:
            _log.warning(
                "orders_stuck",
                count=found.count,
                oldest_age_seconds=round(found.oldest_age_s or 0),
                order_ids=list(found.sample_ids),
                threshold_seconds=int(self._stuck_after.total_seconds()),
            )
        return found

    def run(self) -> None:
        while not self._stopping.is_set():
            self.sweep()
            self._stopping.wait(self._interval_s)
