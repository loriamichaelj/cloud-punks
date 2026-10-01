"""PostgreSQL implementation of the order state machine's single write (DESIGN.md section 7).

Everything happens in ONE transaction, in this order:

1. ``INSERT INTO processed_events ... ON CONFLICT DO NOTHING``. ``rowcount = 0`` means this
   ``event_id`` was already processed: stop, change nothing (a duplicate delivery).
2. ``UPDATE orders SET status = :new, version = version + 1 WHERE order_id = :id AND status =
   'PENDING'``. ``rowcount = 0`` means the order is already terminal (or missing): this guard,
   not message ordering, keeps out-of-order and duplicate deliveries harmless.
3. If the order changed, ``INSERT INTO outbox`` the ``OrderStatusUpdated`` event.

Dedupe, the business write and the event commit together or not at all.
"""

from collections.abc import Callable

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.domain.errors import OrderNotFound
from app.domain.models import OutboxEvent
from app.domain.transitions import (
    StatusChange,
    TransitionContext,
    TransitionKind,
    TransitionResult,
)
from app.repo.orders import store_errors
from app.repo.tables import orders, outbox, processed_events


class PostgresTransitionStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def apply(
        self,
        event_id: str,
        order_id: str,
        change: StatusChange,
        make_event: Callable[[TransitionContext], OutboxEvent],
    ) -> TransitionResult:
        with store_errors(), self._engine.begin() as connection:
            recorded = connection.execute(
                pg_insert(processed_events)
                .values(event_id=event_id)
                .on_conflict_do_nothing(index_elements=[processed_events.c.event_id])
                .returning(processed_events.c.event_id)
            ).scalar_one_or_none()
            if recorded is None:
                return TransitionResult(TransitionKind.DUPLICATE)

            changed = connection.execute(
                update(orders)
                .where(orders.c.order_id == order_id, orders.c.status == "PENDING")
                .values(
                    status=change.new_status,
                    status_reason=change.reason,
                    version=orders.c.version + 1,
                )
                .returning(orders.c.customer_id, orders.c.created_at)
            ).one_or_none()

            if changed is None:
                exists = connection.execute(
                    select(orders.c.order_id).where(orders.c.order_id == order_id)
                ).scalar_one_or_none()
                if exists is None:
                    # Raising inside the transaction rolls back the processed_events row too, so
                    # the event is not marked done for an order that does not exist.
                    raise OrderNotFound(order_id)
                # Already CONFIRMED or REJECTED: commit only the processed_events row.
                return TransitionResult(TransitionKind.STALE)

            event = make_event(
                TransitionContext(
                    order_id=order_id,
                    customer_id=changed.customer_id,
                    old_status="PENDING",
                    new_status=change.new_status,
                    reason=change.reason,
                )
            )
            connection.execute(
                insert(outbox).values(
                    event_id=event.event_id, detail_type=event.detail_type, payload=event.payload
                )
            )
            return TransitionResult(
                TransitionKind.APPLIED, created_at=changed.created_at, new_status=change.new_status
            )
