"""Request/response models. Quantities are strict integers: ``"2"``, ``2.0`` and ``true`` fail."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.domain.models import AvailabilityReport, LineAvailability, RequestedLine, StockItem

RESERVED_SKUS = frozenset({"availability"})  # the literal name of the batch endpoint


def _not_reserved(value: str) -> str:
    if value.lower() in RESERVED_SKUS:
        raise ValueError(f"{value!r} is reserved and cannot be used as an SKU")
    return value


Sku = Annotated[
    str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"), AfterValidator(_not_reserved)
]
MAX_LINES = 20  # the order cap (DESIGN.md section 4)
MAX_STOCK = 1_000_000


class StockOut(BaseModel):
    sku: str
    available: int
    reserved: int
    updated_at: datetime

    @classmethod
    def from_domain(cls, item: StockItem) -> "StockOut":
        return cls(**item.__dict__)


class StockSet(BaseModel):
    """Body of ``PUT /inventory/{sku}``: the new ``available`` quantity."""

    model_config = ConfigDict(extra="forbid")

    available: Annotated[StrictInt, Field(ge=0, le=MAX_STOCK)]


class LineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: Sku
    quantity: Annotated[StrictInt, Field(ge=1, le=100)]


class AvailabilityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: Annotated[list[LineIn], Field(min_length=1, max_length=MAX_LINES)]

    @model_validator(mode="after")
    def _distinct_skus(self) -> "AvailabilityIn":
        skus = [line.sku for line in self.items]
        if len(set(skus)) != len(skus):
            raise ValueError("items must have distinct SKUs")
        return self

    def to_domain(self) -> list[RequestedLine]:
        return [RequestedLine(line.sku, line.quantity) for line in self.items]


class LineOut(BaseModel):
    sku: str
    requested: int
    available: int
    sufficient: bool
    reason: Literal["OUT_OF_STOCK", "UNKNOWN_SKU"] | None

    @classmethod
    def from_domain(cls, line: LineAvailability) -> "LineOut":
        return cls(**line.__dict__)


class AvailabilityOut(BaseModel):
    available: bool
    items: list[LineOut]

    @classmethod
    def from_domain(cls, report: AvailabilityReport) -> "AvailabilityOut":
        return cls(
            available=report.available, items=[LineOut.from_domain(line) for line in report.lines]
        )
