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
    MARKET_ACTIVITY = "MarketActivity"


class ItemQuantity(BaseModel):
    sku: Sku
    quantity: int = Field(ge=1, le=100)


class OrderCreatedData(BaseModel):
    order_id: Ulid
    customer_id: str = Field(min_length=1, max_length=64)
    items: list[ItemQuantity] = Field(min_length=1, max_length=20)
    total_amount: Money
    currency: Currency
    # The customer it is bought from: None for a purchase from the platform, else a resale (an
    # accepted bid, DESIGN.md section 16.5). Additive, so absent in older events means None.
    seller: str | None = Field(default=None, min_length=1, max_length=64)


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
    # Why an OUT_OF_STOCK item could not be had, when it is a CloudPunk: "SOLD" (someone already
    # owns it) or "OWNER_CHANGED" (a resale whose seller no longer owns it). A plain string, not a
    # Literal, so a value added later is not poison to a consumer that predates it (ADR-21).
    detail: str | None = Field(default=None, max_length=32)


class OrderStatusUpdatedData(BaseModel):
    order_id: Ulid
    customer_id: str = Field(min_length=1, max_length=64)
    old_status: OrderStatus
    new_status: OrderStatus
    reason: str | None = Field(default=None, max_length=255)


class MarketActivityKind(StrEnum):
    """What happened on the market. ``MarketActivityData.kind`` stays a plain string (ADR-21): a
    kind added later must not be poison to a consumer that predates it."""

    LISTED = "LISTED"  # the owner put it up for bid
    UNLISTED = "UNLISTED"  # the owner took it off the market
    BID_PLACED = "BID_PLACED"
    BID_WITHDRAWN = "BID_WITHDRAWN"
    SALE = "SALE"  # an order for it confirmed: bought from CloudPunks or by an accepted bid


class MarketActivityData(BaseModel):
    """One thing that happened to one CloudPunk, written by order-service through the outbox in
    the same transaction as the change itself (DESIGN.md section 16.11)."""

    kind: str = Field(min_length=1, max_length=32)
    sku: Sku
    # Who did it: the seller for LISTED and UNLISTED, the bidder for bids, the buyer for a SALE.
    customer_id: str = Field(min_length=1, max_length=64)
    # A SALE's seller: None when it was bought from CloudPunks (the platform).
    counterparty: str | None = Field(default=None, min_length=1, max_length=64)
    amount: Money | None = None  # a bid's amount, a sale's price
    currency: Currency | None = None
    listing_id: Ulid | None = None
    bid_id: Ulid | None = None
    order_id: Ulid | None = None


# (event_type, major schema version) -> payload model. A breaking change adds a (type, 2) entry
# while the producer dual-publishes; consumers that do not know a version simply skip it.
SCHEMAS: dict[tuple[str, int], type[BaseModel]] = {
    (EventType.ORDER_CREATED, 1): OrderCreatedData,
    (EventType.INVENTORY_RESERVED, 1): InventoryReservedData,
    (EventType.INVENTORY_FAILED, 1): InventoryFailedData,
    (EventType.ORDER_STATUS_UPDATED, 1): OrderStatusUpdatedData,
    (EventType.MARKET_ACTIVITY, 1): MarketActivityData,
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
