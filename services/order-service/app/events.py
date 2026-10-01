"""Build the ``OrderCreated`` outbox event for an order (DESIGN.md section 6)."""

from app.domain.models import Order, OutboxEvent
from retail_common.events.envelope import Envelope
from retail_common.events.schemas import EventType, ItemQuantity, OrderCreatedData

PRODUCER = "order-service"


def order_created_event(order: Order) -> OutboxEvent:
    """The envelope is built here, in the request's context, so it carries the request's
    correlation id; the relay publishes it later, possibly minutes later, unchanged."""
    data = OrderCreatedData(
        order_id=order.order_id,
        customer_id=order.customer_id,
        items=[ItemQuantity(sku=item.sku, quantity=item.quantity) for item in order.items],
        total_amount=order.total_amount,
        currency=order.currency,
    )
    envelope = Envelope.create(event_type=EventType.ORDER_CREATED, producer=PRODUCER, data=data)
    return OutboxEvent(
        event_id=envelope.event_id,
        detail_type=envelope.event_type,
        payload=envelope.model_dump(mode="json"),
    )
