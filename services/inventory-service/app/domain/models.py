"""Plain domain objects. Quantities are integers; there is no money in this service."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

FailureReason = Literal["OUT_OF_STOCK", "UNKNOWN_SKU"]
# Why an existing item could not be had (DESIGN.md section 16.5): someone already owns it, or a
# resale's seller no longer does. None for a plain shortfall in counted stock.
FailureDetail = Literal["SOLD", "OWNER_CHANGED"]


@dataclass(frozen=True)
class StockItem:
    sku: str
    available: int
    reserved: int
    updated_at: datetime
    owner: str | None = None  # the customer who owns it; None while the platform holds it


@dataclass(frozen=True)
class RequestedLine:
    sku: str
    quantity: int


@dataclass(frozen=True)
class LineAvailability:
    sku: str
    requested: int
    available: int  # 0 for an unknown SKU
    sufficient: bool
    reason: FailureReason | None  # None when sufficient
    owner: str | None = None  # None for the platform, or for an unknown SKU


@dataclass(frozen=True)
class AvailabilityReport:
    available: bool  # True only if every line is sufficient
    lines: tuple[LineAvailability, ...]
