"""Version 1 payload schemas for the event catalog (DESIGN.md section 6).

Money is ``Decimal`` and serializes to a JSON string. Unknown fields are ignored (pydantic's
default), so additive changes keep the major version.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, ValidationError

from retail_common.errors import PoisonMessage, describe_validation_errors
from retail_common.events.envelope import ULID_PATTERN, Envelope

Ulid = Annotated[str, Field(pattern=ULID_PATTERN)]
Sku = Annotated[str, Field(min_length=1, max_length=64)]
Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
OrderStatus = Literal["PENDING", "CONFIRMED", "REJECTED"]


class EventType(StrEnum):
    ORDER_CREATED = "OrderCreated"
    INVENTORY_RESERVED = "InventoryReserved"
    INVENTORY_FAILED = "InventoryFailed"
    ORDER_STATUS_UPDATED = "OrderStatusUpdated"


class ItemQuantity(BaseModel):
    sku: Sku
    quantity: int = Field(ge=1, le=100)


class OrderCreatedData(BaseModel):
    order_id: Ulid
    customer_id: str = Field(min_length=1, max_length=64)
    items: list[ItemQuantity] = Field(min_length=1, max_length=20)
    total_amount: Money
    currency: Currency


class ReservedItem(BaseModel):
    sku: Sku
    quantity: int = Field(ge=1)
    remaining: int = Field(ge=0)


class InventoryReservedData(BaseModel):
    order_id: Ulid
    items: list[ReservedItem] = Field(min_length=1)


class FailedItem(BaseModel):
    sku: Sku
    requested: int = Field(ge=1)
    available: int = Field(ge=0)  # 0 for an unknown SKU


class InventoryFailedData(BaseModel):
    order_id: Ulid
    reason: Literal["OUT_OF_STOCK", "UNKNOWN_SKU"]
    failed_items: list[FailedItem] = Field(min_length=1)


class OrderStatusUpdatedData(BaseModel):
    order_id: Ulid
    customer_id: str = Field(min_length=1, max_length=64)
    old_status: OrderStatus
    new_status: OrderStatus
    reason: str | None = Field(default=None, max_length=255)


# (event_type, major schema version) -> payload model. A breaking change adds a (type, 2) entry
# while the producer dual-publishes; consumers that do not know a version simply skip it.
SCHEMAS: dict[tuple[str, int], type[BaseModel]] = {
    (EventType.ORDER_CREATED, 1): OrderCreatedData,
    (EventType.INVENTORY_RESERVED, 1): InventoryReservedData,
    (EventType.INVENTORY_FAILED, 1): InventoryFailedData,
    (EventType.ORDER_STATUS_UPDATED, 1): OrderStatusUpdatedData,
}


def validate_data(envelope: Envelope) -> BaseModel | None:
    """Return the validated payload, ``None`` for an event type/version this build doesn't know.

    Raises ``PoisonMessage`` when the type is known but the payload is invalid.
    """
    model = SCHEMAS.get((envelope.event_type, envelope.major_version))
    if model is None:
        return None
    try:
        return model.model_validate(envelope.data)
    except ValidationError as exc:
        # Field paths and messages only: pydantic's own str() embeds the rejected input values,
        # which may be customer data and must not reach the logs.
        problems = describe_validation_errors(exc.errors())
        raise PoisonMessage(f"invalid {envelope.event_type} payload: {problems}") from None
