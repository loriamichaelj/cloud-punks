"""Stock reservation for an order (DESIGN.md sections 5 to 7, ADR-05).

The reservation record in ``inventory_reservations`` is the single source of truth for an order's
outcome. It is written exactly once, atomically with the stock change (or, for a failure, on its
own), and every later delivery of the same ``OrderCreated`` only *reads* it and re-emits the same
outcome event. That is what makes redelivery safe without an outbox: if publishing fails, the
message is not deleted and the retry re-emits from the stored record (ADR-05).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from app.domain.errors import InvalidOrder
from app.domain.models import FailureReason
from app.domain.ports import InventoryRepository

ReservationStatus = Literal["RESERVED", "FAILED"]


@dataclass(frozen=True)
class ReservedLine:
    sku: str
    quantity: int


@dataclass(frozen=True)
class FailedLine:
    sku: str
    requested: int
    available: int  # 0 for an unknown SKU


@dataclass(frozen=True)
class Reservation:
    order_id: str
    status: ReservationStatus
    items: tuple[ReservedLine, ...]
    event_id: str  # the id of the outcome event, fixed at creation so a re-emission carries it
    created_at: datetime
    reason: FailureReason | None = None
    failed_items: tuple[FailedLine, ...] = ()
    remaining: Mapping[str, int] | None = field(default=None, compare=False)  # RESERVED only


@dataclass(frozen=True)
class ReserveResult:
    reservation: Reservation
    created: bool  # False: a record for this order already existed (a redelivery)


@dataclass(frozen=True)
class ProcessedOrder:
    reservation: Reservation
    duplicate: bool


class ReservationStore(Protocol):
    def reserve(
        self, order_id: str, items: Sequence[ReservedLine], event_id: str, created_at: datetime
    ) -> ReserveResult:
        """Reserve every line atomically, or record a FAILED outcome, or return the existing one.

        All lines succeed or none do. Raises ``StoreUnavailable`` for transient failures.
        """
        ...

    def get(self, order_id: str) -> Reservation | None: ...

    def store_remaining(self, order_id: str, remaining: Mapping[str, int]) -> Reservation:
        """Record the stock left after a RESERVED outcome, once; returns the stored record."""
        ...


class ReservationService:
    def __init__(
        self,
        store: ReservationStore,
        inventory: InventoryRepository,
        *,
        new_event_id: Callable[[], str],
        now: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._inventory = inventory
        self._new_event_id = new_event_id
        self._now = now

    def process(self, order_id: str, lines: Sequence[ReservedLine]) -> ProcessedOrder:
        skus = [line.sku for line in lines]
        if len(set(skus)) != len(skus):
            # DynamoDB refuses two operations on one item in a transaction, so this can never work.
            raise InvalidOrder(f"order {order_id} lists the same SKU more than once")

        result = self._store.reserve(order_id, lines, self._new_event_id(), self._now())
        reservation = result.reservation

        # `remaining` (stock left, for the low-stock alert) cannot be returned by a transaction,
        # so it is read right after the commit and stored once. If the process dies in between, the
        # redelivery lands here with a RESERVED record that has no `remaining` and completes it.
        if reservation.status == "RESERVED" and reservation.remaining is None:
            stock = self._inventory.get_many(skus)
            remaining = {sku: stock[sku].available if sku in stock else 0 for sku in skus}
            reservation = self._store.store_remaining(order_id, remaining)

        return ProcessedOrder(reservation=reservation, duplicate=not result.created)
