"""What the use-cases need from the outside world."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from app.domain.models import (
    ActivityEntry,
    Bid,
    BidOutcome,
    BidStatus,
    CreateOutcome,
    Listing,
    ListingStatus,
    Order,
    OrderLine,
    OrderPage,
    OutboxEvent,
    Page,
    ProductInfo,
    StockReport,
    StoredBid,
    StoredOrder,
)


class OrderRepository(Protocol):
    def find_by_idempotency_key(self, customer_id: str, key: str) -> StoredOrder | None: ...

    def create_order(
        self, order: Order, *, idempotency_key: str, request_hash: str, event: OutboxEvent
    ) -> CreateOutcome:
        """Write the order, its items and the outbox row in ONE transaction (ADR-04).

        If ``(customer_id, idempotency_key)`` already holds an order, write nothing and return it
        with ``created=False``. Raises ``StoreUnavailable`` if PostgreSQL cannot be used.
        """
        ...

    def get_order(self, order_id: str) -> Order | None: ...

    def list_orders(self, customer_id: str, page: int, size: int) -> OrderPage:
        """Newest first."""
        ...


class PriceCatalog(Protocol):
    def get_products(self, skus: Sequence[str]) -> Mapping[str, ProductInfo]:
        """Only SKUs that exist appear in the result. Raises ``UpstreamUnavailable``."""
        ...


class StockChecker(Protocol):
    def check(self, lines: Sequence[OrderLine]) -> StockReport:
        """Advisory availability pre-check. Raises ``UpstreamUnavailable``."""
        ...


class OwnerLookup(Protocol):
    def owner_of(self, sku: str) -> str | None:
        """Who owns ``sku`` now, read consistently from inventory; None for the platform.

        Raises ``UnknownItem`` if inventory has no such SKU, ``UpstreamUnavailable`` if it cannot
        answer."""
        ...


class MarketRepository(Protocol):
    """Listings and bids (DESIGN.md section 16.4). Every change is ONE transaction that locks the
    CloudPunk's active listing row, so putting up, bidding, accepting and taking off serialize."""

    def put_up(self, listing: Listing) -> tuple[Listing, bool]:
        """Insert ``listing`` as the CloudPunk's active listing; return it and ``True``.

        If its seller already has it up, return that listing and ``False``. A stale open listing by
        someone else (the caller has checked who owns it now) is cancelled first; raises
        ``SalePending`` if an accepted bid is being confirmed."""
        ...

    def take_off(self, sku: str, seller_id: str) -> Listing:
        """Cancel the active listing and close its open bids. Raises ``NotListed``, ``NotOwner``
        or ``SalePending``."""
        ...

    def list_listings(
        self, sku: str | None, statuses: Sequence[ListingStatus], page: int, size: int
    ) -> Page[Listing]:
        """Newest first."""
        ...

    def find_bid_by_key(self, bidder_id: str, key: str) -> StoredBid | None: ...

    def place_bid(self, bid: Bid, *, request_hash: str, idempotency_key: str) -> BidOutcome:
        """Insert an OPEN bid on the CloudPunk's open listing (``bid.listing_id`` is filled in
        here). Raises ``NotListed``, ``SalePending`` or ``OwnItem``. If the bidder's key already
        holds a bid, write nothing and return it with ``created=False``."""
        ...

    def get_bid(self, bid_id: str) -> Bid | None: ...

    def withdraw_bid(self, bid_id: str, bidder_id: str) -> Bid:
        """OPEN -> WITHDRAWN. Raises ``BidNotFound``, ``NotBidder`` or ``BidNotOpen``."""
        ...

    def accept_bid(
        self,
        bid_id: str,
        seller_id: str,
        order: Order,
        *,
        idempotency_key: str,
        request_hash: str,
        event: OutboxEvent,
    ) -> CreateOutcome:
        """In ONE transaction: listing OPEN -> SALE_PENDING, bid OPEN -> ACCEPTED, and the order,
        its items and its outbox row written (ADR-04). If the bid was already accepted, write
        nothing and return its order with ``created=False``. Raises ``BidNotFound``,
        ``BidNotOpen``, ``NotListed``, ``NotOwner`` or ``SalePending``."""
        ...

    def list_bids(
        self, sku: str | None, bidder_id: str | None, status: BidStatus | None, page: int, size: int
    ) -> Page[Bid]:
        """Newest first."""
        ...

    def activity(self, sku: str | None, page: int, size: int) -> Page[ActivityEntry]:
        """Sales, listings and bids, newest first."""
        ...
