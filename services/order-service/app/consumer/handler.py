"""Handlers for the inventory outcome events (``InventoryReserved`` / ``InventoryFailed``).

The consumer contract (DESIGN.md section 6): the payload arrives validated; dedupe on
``event_id`` happens inside the same transaction as the status change (the store does both);
the SQS message is deleted by the consumer only after this returns, i.e. after the commit.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import structlog

from app.domain.errors import OrderNotFound
from app.domain.transitions import InventoryOutcome, TransitionKind, TransitionService
from app.metrics import OrderMetrics
from retail_common.errors import PoisonMessage
from retail_common.events.consumer import HandlerOutcome
from retail_common.events.envelope import Envelope
from retail_common.events.schemas import InventoryFailedData, InventoryReservedData

_log = structlog.get_logger("order_consumer")


class InventoryOutcomeHandler:
    def __init__(
        self,
        service: TransitionService,
        metrics: OrderMetrics,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._service = service
        self._metrics = metrics
        self._now = now

    def on_reserved(self, envelope: Envelope, data: InventoryReservedData) -> HandlerOutcome:
        return self._handle(envelope, data.order_id, InventoryOutcome(reserved=True))

    def on_failed(self, envelope: Envelope, data: InventoryFailedData) -> HandlerOutcome:
        return self._handle(
            envelope, data.order_id, InventoryOutcome(reserved=False, reason=data.reason)
        )

    def _handle(
        self, envelope: Envelope, order_id: str, outcome: InventoryOutcome
    ) -> HandlerOutcome:
        try:
            result = self._service.handle(envelope.event_id, order_id, outcome)
        except OrderNotFound as exc:
            # Can never succeed by retrying: it goes to the DLQ for a human to look at.
            raise PoisonMessage(str(exc)) from exc

        if result.kind is TransitionKind.APPLIED and result.new_status and result.created_at:
            self._metrics.orders_total.labels(result.new_status).inc()
            self._metrics.time_to_terminal.observe(
                max((self._now() - result.created_at).total_seconds(), 0.0)
            )
            return HandlerOutcome.PROCESSED
        if result.kind is TransitionKind.STALE:
            _log.warning("stale_event", order_id=order_id, event_id=envelope.event_id)
        return HandlerOutcome.DUPLICATE
