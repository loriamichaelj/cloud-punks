"""The order state machine (DESIGN.md section 7).

        InventoryReserved
PENDING ------------------> CONFIRMED
   |      InventoryFailed
   +----------------------> REJECTED      (status_reason = the event's reason)

CONFIRMED and REJECTED are terminal: any later inventory outcome is ignored. The transition is
guarded in SQL (``UPDATE ... WHERE status = 'PENDING'``), not by trusting message order, so
duplicate and out-of-order deliveries are harmless.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from app.domain.models import OrderStatus, OutboxEvent


@dataclass(frozen=True)
class InventoryOutcome:
    """What inventory decided: ``reserved`` or failed with a reason."""

    reserved: bool
    reason: str | None = None


@dataclass(frozen=True)
class StatusChange:
    new_status: OrderStatus
    reason: str | None


def decide(outcome: InventoryOutcome) -> StatusChange:
    """The pure decision: which terminal status an inventory outcome leads to."""
    if outcome.reserved:
        return StatusChange("CONFIRMED", None)
    return StatusChange("REJECTED", outcome.reason or "REJECTED_BY_INVENTORY")


@dataclass(frozen=True)
class TransitionContext:
    """The facts about an order at the moment it changed status, for building its event."""

    order_id: str
    customer_id: str
    old_status: OrderStatus
    new_status: OrderStatus
    reason: str | None


class TransitionKind(StrEnum):
    APPLIED = "applied"  # the order changed status
    DUPLICATE = "duplicate"  # this event_id was already processed: nothing was done
    STALE = "stale"  # the order was already terminal: only the event was recorded


@dataclass(frozen=True)
class TransitionResult:
    kind: TransitionKind
    created_at: datetime | None = None  # of the order, set when APPLIED (for time-to-terminal)
    new_status: OrderStatus | None = None


class TransitionStore(Protocol):
    def apply(
        self,
        event_id: str,
        order_id: str,
        change: StatusChange,
        make_event: Callable[[TransitionContext], OutboxEvent],
    ) -> TransitionResult:
        """In ONE transaction: record ``event_id`` as processed (skip everything if already),
        move the order out of PENDING, and write the outbox event. Raises ``OrderNotFound``
        (rolling back, including the processed-event row) if there is no such order."""
        ...


class TransitionService:
    def __init__(
        self, store: TransitionStore, make_event: Callable[[TransitionContext, str], OutboxEvent]
    ) -> None:
        self._store = store
        self._make_event = make_event

    def handle(self, event_id: str, order_id: str, outcome: InventoryOutcome) -> TransitionResult:
        change = decide(outcome)
        return self._store.apply(
            event_id, order_id, change, lambda ctx: self._make_event(ctx, event_id)
        )
