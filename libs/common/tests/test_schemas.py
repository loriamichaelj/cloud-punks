from decimal import Decimal
from typing import Any

import pytest
from helpers import make_envelope, order_created_data
from pydantic import ValidationError
from ulid import ULID

from retail_common.errors import PoisonMessage
from retail_common.events.schemas import (
    SCHEMAS,
    EventType,
    InventoryFailedData,
    InventoryReservedData,
    OrderCreatedData,
    OrderStatusUpdatedData,
    validate_data,
)

ORDER_ID = str(ULID())


def test_order_created_accepts_the_documented_payload() -> None:
    data = OrderCreatedData.model_validate(order_created_data())
    assert data.customer_id == "cust-1001"
    assert data.items[0].quantity == 2
    assert data.total_amount == Decimal("39.98")


@pytest.mark.parametrize(
    "overrides",
    [
        {"total_amount": "39.999"},  # more than 2 decimal places
        {"total_amount": "-1.00"},
        {"total_amount": "12345678901.00"},  # more than 12 digits
        {"currency": "usd"},
        {"currency": "US"},
        {"order_id": "short"},
        {"customer_id": ""},
        {"items": []},
        {"items": [{"sku": "S", "quantity": 0}]},
        {"items": [{"sku": "S", "quantity": 101}]},
        {"items": [{"sku": "", "quantity": 1}]},
        {"items": [{"sku": f"S{i}", "quantity": 1} for i in range(21)]},  # 20-line cap
    ],
)
def test_order_created_rejects_invalid_payloads(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        OrderCreatedData.model_validate(order_created_data(**overrides))


def test_order_created_allows_exactly_twenty_lines() -> None:
    items = [{"sku": f"S{i}", "quantity": 1} for i in range(20)]
    assert len(OrderCreatedData.model_validate(order_created_data(items=items)).items) == 20


def test_inventory_reserved_payload() -> None:
    data = InventoryReservedData.model_validate(
        {"order_id": ORDER_ID, "items": [{"sku": "A", "quantity": 2, "remaining": 8}]}
    )
    assert data.items[0].remaining == 8


def test_inventory_failed_payload_and_reasons() -> None:
    wire = {
        "order_id": ORDER_ID,
        "reason": "OUT_OF_STOCK",
        "failed_items": [{"sku": "A", "requested": 2, "available": 1}],
    }
    assert InventoryFailedData.model_validate(wire).failed_items[0].available == 1

    assert InventoryFailedData.model_validate({**wire, "reason": "UNKNOWN_SKU"}).reason == (
        "UNKNOWN_SKU"
    )
    with pytest.raises(ValidationError):
        InventoryFailedData.model_validate({**wire, "reason": "SOMETHING_ELSE"})


def test_order_status_updated_payload() -> None:
    data = OrderStatusUpdatedData.model_validate(
        {
            "order_id": ORDER_ID,
            "customer_id": "cust-1",
            "old_status": "PENDING",
            "new_status": "REJECTED",
            "reason": "OUT_OF_STOCK",
        }
    )
    assert data.new_status == "REJECTED"
    with pytest.raises(ValidationError):
        OrderStatusUpdatedData.model_validate(
            {
                "order_id": ORDER_ID,
                "customer_id": "c",
                "old_status": "PENDING",
                "new_status": "DONE",
            }
        )


def test_unknown_payload_fields_are_ignored() -> None:
    data = OrderCreatedData.model_validate(order_created_data(added_later="fine"))
    assert not hasattr(data, "added_later")


def test_every_catalog_event_has_a_v1_schema() -> None:
    assert {event_type for event_type, version in SCHEMAS if version == 1} == set(EventType)


def test_validate_data_returns_the_typed_model() -> None:
    data = validate_data(make_envelope())
    assert isinstance(data, OrderCreatedData)


def test_validate_data_returns_none_for_an_unknown_event_type() -> None:
    assert validate_data(make_envelope("SomethingNew", data={"x": 1})) is None


def test_validate_data_returns_none_for_an_unknown_major_version() -> None:
    """Dual-publishing a breaking change relies on old consumers skipping the new version."""
    assert validate_data(make_envelope(schema_version="2.0")) is None


def test_a_minor_version_bump_still_validates() -> None:
    assert isinstance(validate_data(make_envelope(schema_version="1.3")), OrderCreatedData)


def test_invalid_payload_is_poison_and_the_error_never_echoes_the_input() -> None:
    envelope = make_envelope(data=order_created_data(customer_id="", currency="SECRET-CARD-1234"))

    with pytest.raises(PoisonMessage) as raised:
        validate_data(envelope)

    message = str(raised.value)
    assert "OrderCreated" in message
    assert "currency" in message
    assert "SECRET-CARD-1234" not in message
