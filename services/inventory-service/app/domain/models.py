"""Plain domain objects. Quantities are integers; there is no money in this service."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

FailureReason = Literal["OUT_OF_STOCK", "UNKNOWN_SKU"]


@dataclass(frozen=True)
class StockItem:
    sku: str
    available: int
    reserved: int
    updated_at: datetime


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


@dataclass(frozen=True)
class AvailabilityReport:
    available: bool  # True only if every line is sufficient
    lines: tuple[LineAvailability, ...]
