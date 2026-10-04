"""Build the outbox events order-service publishes (DESIGN.md section 6)."""

from app.domain.models import MarketActivity, Order, OutboxEvent
from app.domain.transitions import TransitionContext
from retail_common.events.envelope import Envelope
from retail_common.events.schemas import (
    EventType,
    ItemQuantity,
    MarketActivityData,
    OrderCreatedData,
    OrderStatusUpdatedData,
)

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
        # Set for an accepted bid: inventory then moves ownership only if the seller still owns
        # it (DESIGN.md section 16.5). None is a purchase from the platform.
        seller=order.seller,
    )
    envelope = Envelope.create(event_type=EventType.ORDER_CREATED, producer=PRODUCER, data=data)
    return OutboxEvent(
        event_id=envelope.event_id,
        detail_type=envelope.event_type,
        payload=envelope.model_dump(mode="json"),
    )


def order_status_updated_event(context: TransitionContext, causation_id: str) -> OutboxEvent:
    """The ``OrderStatusUpdated`` event for a status change, linked to the event that caused it.

    Built inside the consumer's message context, so it inherits the correlation id of the
    original request through the whole saga."""
    data = OrderStatusUpdatedData(
        order_id=context.order_id,
        customer_id=context.customer_id,
        old_status=context.old_status,
        new_status=context.new_status,
        reason=context.reason,
    )
    envelope = Envelope.create(
        event_type=EventType.ORDER_STATUS_UPDATED,
        producer=PRODUCER,
        data=data,
        causation_id=causation_id,
    )
    return OutboxEvent(
        event_id=envelope.event_id,
        detail_type=envelope.event_type,
        payload=envelope.model_dump(mode="json"),
    )


def market_activity_event(activity: MarketActivity, causation_id: str | None = None) -> OutboxEvent:
    """The ``MarketActivity`` event for one listing, bid or sale (DESIGN.md section 16.11). Built
    inside the transaction that made the change, so it carries that request's (or, for a sale, that
    saga's) correlation id."""
    data = MarketActivityData(
        kind=activity.kind,
        sku=activity.sku,
        customer_id=activity.customer_id,
        counterparty=activity.counterparty,
        amount=activity.amount,
        currency=activity.currency,
        listing_id=activity.listing_id,
        bid_id=activity.bid_id,
        order_id=activity.order_id,
    )
    envelope = Envelope.create(
        event_type=EventType.MARKET_ACTIVITY,
        producer=PRODUCER,
        data=data,
        causation_id=causation_id,
    )
    return OutboxEvent(
        event_id=envelope.event_id,
        detail_type=envelope.event_type,
        payload=envelope.model_dump(mode="json"),
    )
