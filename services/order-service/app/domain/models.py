"""Plain domain objects. Money is ``Decimal``, never ``float``; ids are ULIDs."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

OrderStatus = Literal["PENDING", "CONFIRMED", "REJECTED"]


@dataclass(frozen=True)
class OrderLine:
    """What the customer asked for."""

    sku: str
    quantity: int


@dataclass(frozen=True)
class OrderItem:
    """A line as ordered, with the unit price snapshotted at order time."""

    sku: str
    quantity: int
    unit_price: Decimal


@dataclass(frozen=True)
class Order:
    order_id: str
    customer_id: str
    status: OrderStatus
    status_reason: str | None
    total_amount: Decimal
    currency: str
    items: tuple[OrderItem, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ProductInfo:
    sku: str
    price: Decimal
    currency: str
    active: bool


@dataclass(frozen=True)
class StockLine:
    sku: str
    requested: int
    available: int
    sufficient: bool
    reason: str | None


@dataclass(frozen=True)
class StockReport:
    available: bool
    lines: tuple[StockLine, ...]


@dataclass(frozen=True)
class OutboxEvent:
    """An event to publish, written in the same transaction as the order that caused it."""

    event_id: str
    detail_type: str
    payload: dict[str, Any]  # the full envelope, stored as JSONB


@dataclass(frozen=True)
class StoredOrder:
    order: Order
    request_hash: str


@dataclass(frozen=True)
class CreateOutcome:
    """What the repository did: stored a new order, or found the one that already held the key."""

    stored: StoredOrder
    created: bool


@dataclass(frozen=True)
class CreateResult:
    order: Order
    created: bool  # False for an idempotent replay


@dataclass(frozen=True)
class OrderPage:
    items: tuple[Order, ...]
    page: int
    size: int
    total: int
