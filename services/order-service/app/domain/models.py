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
    seller: str | None = None  # None: bought from the platform; else a resale (an accepted bid)


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

    @property
    def seller(self) -> str | None:
        """The customer this order buys from: set only when every item is a resale by one
        seller (an accepted bid). None means a purchase from the platform."""
        sellers = {item.seller for item in self.items}
        return sellers.pop() if len(sellers) == 1 else None


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
class MarketActivity:
    """One thing that happened to one CloudPunk, published as a ``MarketActivity`` event through
    the outbox in the transaction that made it happen (DESIGN.md section 16.11). ``kind`` is one of
    LISTED, UNLISTED, BID_PLACED, BID_WITHDRAWN or SALE."""

    kind: str
    sku: str
    customer_id: str  # the seller (LISTED, UNLISTED), the bidder (bids), the buyer (SALE)
    counterparty: str | None = None  # a SALE's seller; None when bought from the platform
    amount: Decimal | None = None
    currency: str | None = None
    listing_id: str | None = None
    bid_id: str | None = None
    order_id: str | None = None


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


# -- the CloudPunks market (DESIGN.md section 16) -------------------------------------------------

ListingStatus = Literal["OPEN", "SALE_PENDING", "SOLD", "CANCELLED"]
BidStatus = Literal["OPEN", "WITHDRAWN", "ACCEPTED", "FILLED", "FAILED", "CLOSED"]
ActivityKind = Literal["SALE", "LISTED", "UNLISTED", "BID", "BID_WITHDRAWN"]


@dataclass(frozen=True)
class Listing:
    """A CloudPunk its owner has put up for bid (purple, DESIGN.md 16.1)."""

    listing_id: str
    sku: str
    seller_id: str
    status: ListingStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Bid:
    bid_id: str
    listing_id: str
    sku: str
    bidder_id: str
    amount: Decimal
    currency: str
    status: BidStatus
    order_id: str | None  # set once the owner accepts it
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredBid:
    bid: Bid
    request_hash: str


@dataclass(frozen=True)
class BidOutcome:
    stored: StoredBid
    created: bool  # False: the bidder's Idempotency-Key already held a bid


@dataclass(frozen=True)
class ActivityEntry:
    """One line of the activity feed, newest first (DESIGN.md 16.4)."""

    kind: ActivityKind
    sku: str
    at: datetime
    amount: Decimal | None = None
    currency: str | None = None
    from_id: str | None = None  # the seller (None for the platform) or, for a bid, nobody
    to_id: str | None = None  # the buyer, or the bidder
    order_id: str | None = None
    bid_id: str | None = None


@dataclass(frozen=True)
class Page[T]:
    items: tuple[T, ...]
    page: int
    size: int
    total: int
