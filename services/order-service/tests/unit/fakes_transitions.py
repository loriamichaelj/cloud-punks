"""An in-memory TransitionStore that follows the same rules as the PostgreSQL one."""

from collections.abc import Callable
from datetime import UTC, datetime

from app.domain.errors import OrderNotFound
from app.domain.models import OrderStatus, OutboxEvent
from app.domain.transitions import (
    StatusChange,
    TransitionContext,
    TransitionKind,
    TransitionResult,
)

CREATED_AT = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


class FakeTransitionStore:
    def __init__(self, orders: dict[str, OrderStatus] | None = None) -> None:
        self.orders: dict[str, OrderStatus] = dict(orders or {})
        self.reasons: dict[str, str | None] = {}
        self.processed: set[str] = set()
        self.outbox: list[OutboxEvent] = []

    def apply(
        self,
        event_id: str,
        order_id: str,
        change: StatusChange,
        make_event: Callable[[TransitionContext], OutboxEvent],
    ) -> TransitionResult:
        if event_id in self.processed:
            return TransitionResult(TransitionKind.DUPLICATE)
        if order_id not in self.orders:
            raise OrderNotFound(order_id)  # nothing recorded: the "transaction" rolled back
        self.processed.add(event_id)
        if self.orders[order_id] != "PENDING":
            return TransitionResult(TransitionKind.STALE)
        self.orders[order_id] = change.new_status
        self.reasons[order_id] = change.reason
        self.outbox.append(
            make_event(
                TransitionContext(order_id, "cust-1", "PENDING", change.new_status, change.reason)
            )
        )
        return TransitionResult(
            TransitionKind.APPLIED, created_at=CREATED_AT, new_status=change.new_status
        )
