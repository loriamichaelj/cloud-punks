"""Request/response models. Money is a decimal *string* on the wire; quantities are strict ints."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_serializer,
    model_validator,
)

from app.domain.models import Order, OrderLine, OrderPage

Sku = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
CustomerId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")]
IdempotencyKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{1,64}$")]
OrderId = Annotated[str, Field(pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$")]  # a ULID
CENT = Decimal("0.01")
MAX_LINES = 20


def _two_decimals(value: Decimal) -> str:
    return format(value.quantize(CENT), "f")


class LineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: Sku
    quantity: Annotated[StrictInt, Field(ge=1, le=100)]


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: CustomerId
    items: Annotated[list[LineIn], Field(min_length=1, max_length=MAX_LINES)]

    @model_validator(mode="after")
    def _distinct_skus(self) -> "OrderCreate":
        skus = [line.sku for line in self.items]
        if len(set(skus)) != len(skus):
            raise ValueError("items must have distinct SKUs")
        return self

    def lines(self) -> list[OrderLine]:
        return [OrderLine(line.sku, line.quantity) for line in self.items]


class ItemOut(BaseModel):
    sku: str
    quantity: int
    unit_price: Decimal  # serialized as a two-decimal string below

    @field_serializer("unit_price")
    def _serialize_price(self, value: Decimal) -> str:
        return _two_decimals(value)


class OrderOut(BaseModel):
    order_id: str
    customer_id: str
    status: str
    status_reason: str | None
    total_amount: Decimal
    currency: str
    items: list[ItemOut]
    created_at: datetime
    updated_at: datetime

    @field_serializer("total_amount")
    def _serialize_total(self, value: Decimal) -> str:
        return _two_decimals(value)

    @classmethod
    def from_domain(cls, order: Order) -> "OrderOut":
        return cls(
            order_id=order.order_id,
            customer_id=order.customer_id,
            status=order.status,
            status_reason=order.status_reason,
            total_amount=order.total_amount,
            currency=order.currency,
            items=[
                ItemOut(sku=i.sku, quantity=i.quantity, unit_price=i.unit_price)
                for i in order.items
            ],
            created_at=order.created_at,
            updated_at=order.updated_at,
        )


class OrderPageOut(BaseModel):
    items: list[OrderOut]
    page: int
    size: int
    total: int

    @classmethod
    def from_domain(cls, page: OrderPage) -> "OrderPageOut":
        return cls(
            items=[OrderOut.from_domain(order) for order in page.items],
            page=page.page,
            size=page.size,
            total=page.total,
        )
