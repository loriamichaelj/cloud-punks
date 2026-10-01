import contextvars
from datetime import UTC, datetime
from decimal import Decimal

from app.domain.models import Order, OrderItem
from app.events import order_created_event
from retail_common.events.envelope import Envelope
from retail_common.events.schemas import OrderCreatedData, validate_data
from retail_common.logging import set_correlation_id

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
ORDER = Order(
    order_id="01J9Z6Q4W8K3M2N1P0R7S5T4V3",
    customer_id="cust-1001",
    status="PENDING",
    status_reason=None,
    total_amount=Decimal("39.98"),
    currency="USD",
    items=(OrderItem("SKU-TSHIRT-BLK-M", 2, Decimal("19.99")),),
    created_at=NOW,
    updated_at=NOW,
)


def test_the_event_is_a_complete_valid_order_created_envelope() -> None:
    event = order_created_event(ORDER)

    envelope = Envelope.model_validate(event.payload)
    assert event.detail_type == "OrderCreated" == envelope.event_type
    assert event.event_id == envelope.event_id
    assert envelope.producer == "order-service"
    assert envelope.schema_version == "1.0"
    assert envelope.causation_id is None  # triggered by an HTTP request, not by another event


def test_the_payload_validates_against_the_shared_v1_schema() -> None:
    event = order_created_event(ORDER)

    data = validate_data(Envelope.model_validate(event.payload))

    assert isinstance(data, OrderCreatedData)
    assert data.order_id == ORDER.order_id
    assert data.total_amount == Decimal("39.98")
    assert [(i.sku, i.quantity) for i in data.items] == [("SKU-TSHIRT-BLK-M", 2)]


def test_money_in_the_stored_json_is_a_string() -> None:
    payload = order_created_event(ORDER).payload
    assert payload["data"]["total_amount"] == "39.98"
    assert isinstance(payload["data"]["total_amount"], str)


def test_unit_prices_are_not_part_of_the_event() -> None:
    """Inventory needs SKUs and quantities; prices stay in the order."""
    items = order_created_event(ORDER).payload["data"]["items"]
    assert items == [{"sku": "SKU-TSHIRT-BLK-M", "quantity": 2}]


def test_the_event_carries_the_requests_correlation_id_for_the_whole_saga() -> None:
    def build() -> Envelope:
        set_correlation_id("corr-from-the-http-request")
        return Envelope.model_validate(order_created_event(ORDER).payload)

    assert contextvars.copy_context().run(build).correlation_id == "corr-from-the-http-request"


def test_every_event_has_a_distinct_id() -> None:
    assert order_created_event(ORDER).event_id != order_created_event(ORDER).event_id
