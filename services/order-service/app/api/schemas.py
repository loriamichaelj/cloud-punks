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

from app.domain.models import (
    ActivityEntry,
    ActivityKind,
    Bid,
    BidStatus,
    Listing,
    ListingStatus,
    Order,
    OrderLine,
    OrderPage,
    Page,
)

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
    seller: str | None = Field(
        description="Who it was bought from: null for the platform, else the previous owner"
    )

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
                ItemOut(sku=i.sku, quantity=i.quantity, unit_price=i.unit_price, seller=i.seller)
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


# -- the CloudPunks market (DESIGN.md section 16.4) ------------------------------------------------

BidId = Annotated[str, Field(pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$")]  # a ULID
# A JSON string, never a number: a number would pass through a float on the way in.
Amount = Annotated[str, Field(pattern=r"^[0-9]{1,8}(\.[0-9]{1,2})?$", examples=["33.50"])]


class ListingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: CustomerId
    sku: Sku


class ListingOut(BaseModel):
    listing_id: str
    sku: str
    seller: str
    status: ListingStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, listing: Listing) -> "ListingOut":
        return cls(
            listing_id=listing.listing_id,
            sku=listing.sku,
            seller=listing.seller_id,
            status=listing.status,
            created_at=listing.created_at,
            updated_at=listing.updated_at,
        )


class ListingPageOut(BaseModel):
    items: list[ListingOut]
    page: int
    size: int
    total: int

    @classmethod
    def from_domain(cls, page: Page[Listing]) -> "ListingPageOut":
        return cls(
            items=[ListingOut.from_domain(x) for x in page.items],
            page=page.page,
            size=page.size,
            total=page.total,
        )


class BidCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: CustomerId
    sku: Sku
    amount: Amount

    @model_validator(mode="after")
    def _positive(self) -> "BidCreate":
        if Decimal(self.amount) <= 0:
            raise ValueError("amount must be above 0")
        return self

    def decimal_amount(self) -> Decimal:
        return Decimal(self.amount)


class BidAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: CustomerId


class BidOut(BaseModel):
    bid_id: str
    listing_id: str
    sku: str
    bidder: str
    amount: Decimal
    currency: str
    status: BidStatus
    order_id: str | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("amount")
    def _serialize_amount(self, value: Decimal) -> str:
        return _two_decimals(value)

    @classmethod
    def from_domain(cls, bid: Bid) -> "BidOut":
        return cls(
            bid_id=bid.bid_id,
            listing_id=bid.listing_id,
            sku=bid.sku,
            bidder=bid.bidder_id,
            amount=bid.amount,
            currency=bid.currency,
            status=bid.status,
            order_id=bid.order_id,
            created_at=bid.created_at,
            updated_at=bid.updated_at,
        )


class BidPageOut(BaseModel):
    items: list[BidOut]
    page: int
    size: int
    total: int

    @classmethod
    def from_domain(cls, page: Page[Bid]) -> "BidPageOut":
        return cls(
            items=[BidOut.from_domain(x) for x in page.items],
            page=page.page,
            size=page.size,
            total=page.total,
        )


class ActivityOut(BaseModel):
    kind: ActivityKind
    sku: str
    at: datetime
    amount: Decimal | None
    currency: str | None
    from_: str | None = Field(
        serialization_alias="from",
        description="The seller (null for the platform) of a SALE; the owner of a listing",
    )
    to: str | None = Field(description="The buyer of a SALE; the bidder of a bid")
    order_id: str | None
    bid_id: str | None

    @field_serializer("amount")
    def _serialize_amount(self, value: Decimal | None) -> str | None:
        return None if value is None else _two_decimals(value)

    @classmethod
    def from_domain(cls, entry: ActivityEntry) -> "ActivityOut":
        return cls(
            kind=entry.kind,
            sku=entry.sku,
            at=entry.at,
            amount=entry.amount,
            currency=entry.currency,
            from_=entry.from_id,
            to=entry.to_id,
            order_id=entry.order_id,
            bid_id=entry.bid_id,
        )


class ActivityPageOut(BaseModel):
    items: list[ActivityOut]
    page: int
    size: int
    total: int

    @classmethod
    def from_domain(cls, page: Page[ActivityEntry]) -> "ActivityPageOut":
        return cls(
            items=[ActivityOut.from_domain(x) for x in page.items],
            page=page.page,
            size=page.size,
            total=page.total,
        )
