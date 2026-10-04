"""The OrderCreated handler: reserve, then publish the stored outcome (ADR-05)."""

from app.consumer.events import outcome_envelope
from app.domain.errors import InvalidOrder
from app.domain.reservations import ReservationService, ReservedLine
from retail_common.errors import PoisonMessage
from retail_common.events.consumer import HandlerOutcome
from retail_common.events.envelope import Envelope
from retail_common.events.publisher import EventPublisher
from retail_common.events.schemas import OrderCreatedData


class OutcomePublishError(RuntimeError):
    """The bus did not accept the outcome event. Transient: the message is redelivered."""


class OrderCreatedHandler:
    def __init__(self, service: ReservationService, publisher: EventPublisher) -> None:
        self._service = service
        self._publisher = publisher

    def __call__(self, envelope: Envelope, data: OrderCreatedData) -> HandlerOutcome:
        lines = [ReservedLine(item.sku, item.quantity) for item in data.items]
        try:
            processed = self._service.process(
                data.order_id, lines, buyer=data.customer_id, seller=data.seller
            )
        except InvalidOrder as exc:
            raise PoisonMessage(str(exc)) from exc

        result = self._publisher.publish(
            [outcome_envelope(processed.reservation, causation_id=envelope.event_id)]
        )
        if not result.all_succeeded:
            # Not deleted, so SQS redelivers; the retry finds the stored reservation (no second
            # decrement) and publishes the same event again.
            raise OutcomePublishError(f"outcome for order {data.order_id} was not published")

        return HandlerOutcome.DUPLICATE if processed.duplicate else HandlerOutcome.PROCESSED
