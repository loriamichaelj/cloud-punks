"""The CloudPunks market (DESIGN.md section 16): up for bid, bids, accepting a bid, activity.

Red: unsold, bought from the platform through ``OrderService``. Blue: owned and not on the market.
Purple: the owner put it up for bid (a listing); others bid; the owner accepts one, which creates an
ordinary order for the bidder at the bid amount with the owner as ``seller``. That order travels
the existing outbox, saga and reservation path, and the reservation moves ownership (ADR-18, 19).

As everywhere in this service, downstream calls (who owns it, the product's currency) are made
before the write transaction, never while it holds a connection.
"""

import hashlib
from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal

from app.domain.errors import (
    BidNotFound,
    BidNotOpen,
    IdempotencyKeyReused,
    NotOwner,
    ProductInactive,
    UnknownProduct,
)
from app.domain.hashing import request_hash
from app.domain.models import (
    ActivityEntry,
    Bid,
    BidStatus,
    CreateResult,
    Listing,
    ListingStatus,
    Order,
    OrderItem,
    OrderLine,
    OutboxEvent,
    Page,
)
from app.domain.ports import MarketRepository, OwnerLookup, PriceCatalog

ACTIVE: tuple[ListingStatus, ...] = ("OPEN", "SALE_PENDING")
CENT = Decimal("0.01")


def bid_request_hash(bidder_id: str, sku: str, amount: Decimal) -> str:
    """What "the same bid" means for an Idempotency-Key replay: bidder, CloudPunk and amount."""
    canonical = f"{bidder_id}\n{sku}\n{amount.quantize(CENT)}"
    return hashlib.sha256(canonical.encode()).hexdigest()


def accepted_order_key(bid_id: str) -> str:
    """The Idempotency-Key of the order an accepted bid creates: one bid, one order."""
    return f"bid-{bid_id}"


class MarketService:
    def __init__(
        self,
        market: MarketRepository,
        owners: OwnerLookup,
        catalog: PriceCatalog,
        *,
        new_id: Callable[[], str],
        make_event: Callable[[Order], OutboxEvent],
        now: Callable[[], datetime],
    ) -> None:
        self._market = market
        self._owners = owners
        self._catalog = catalog
        self._new_id = new_id
        self._make_event = make_event
        self._now = now

    # -- up for bid --------------------------------------------------------------------------

    def put_up(self, customer_id: str, sku: str) -> tuple[Listing, bool]:
        """The owner puts a blue CloudPunk up for bid. Returns the listing and whether it is new.

        The platform's red CloudPunks are bought, not bid on, so they are never "yours"."""
        if self._owners.owner_of(sku) != customer_id:
            raise NotOwner(sku)
        now = self._now()
        return self._market.put_up(
            Listing(self._new_id(), sku, customer_id, "OPEN", created_at=now, updated_at=now)
        )

    def take_off(self, customer_id: str, sku: str) -> Listing:
        return self._market.take_off(sku, customer_id)

    def list_listings(
        self, sku: str | None, statuses: Sequence[ListingStatus], page: int, size: int
    ) -> Page[Listing]:
        return self._market.list_listings(sku, statuses, page, size)

    # -- bids --------------------------------------------------------------------------------

    def place_bid(
        self, customer_id: str, idempotency_key: str, sku: str, amount: Decimal
    ) -> tuple[Bid, bool]:
        fingerprint = bid_request_hash(customer_id, sku, amount)
        existing = self._market.find_bid_by_key(customer_id, idempotency_key)
        if existing is not None:
            if existing.request_hash != fingerprint:
                raise IdempotencyKeyReused
            return existing.bid, False

        product = self._catalog.get_products([sku]).get(sku)
        if product is None:
            raise UnknownProduct([sku])
        if not product.active:
            raise ProductInactive([sku])

        now = self._now()
        bid = Bid(
            bid_id=self._new_id(),
            listing_id="",  # the open listing's id, filled in by the repository under its lock
            sku=sku,
            bidder_id=customer_id,
            amount=amount.quantize(CENT),
            currency=product.currency,
            status="OPEN",
            order_id=None,
            created_at=now,
            updated_at=now,
        )
        outcome = self._market.place_bid(
            bid, request_hash=fingerprint, idempotency_key=idempotency_key
        )
        if not outcome.created and outcome.stored.request_hash != fingerprint:
            raise IdempotencyKeyReused
        return outcome.stored.bid, outcome.created

    def withdraw_bid(self, customer_id: str, bid_id: str) -> Bid:
        return self._market.withdraw_bid(bid_id, customer_id)

    def list_bids(
        self, sku: str | None, bidder_id: str | None, status: BidStatus | None, page: int, size: int
    ) -> Page[Bid]:
        return self._market.list_bids(sku, bidder_id, status, page, size)

    def accept_bid(self, customer_id: str, bid_id: str) -> CreateResult:
        """The owner accepts a bid: an order for the bidder at the bid amount, bought from them.

        Accepting the same bid again returns the same order (the button can be pressed twice)."""
        bid = self._market.get_bid(bid_id)
        if bid is None:
            raise BidNotFound(bid_id)
        if bid.status not in ("OPEN", "ACCEPTED", "FILLED"):
            raise BidNotOpen(bid_id, bid.status)
        # Inventory decides at the reservation, but refuse here what cannot work: only the owner
        # may sell it. The repository checks the listing's seller again under the listing lock.
        if self._owners.owner_of(bid.sku) != customer_id and bid.status == "OPEN":
            raise NotOwner(bid.sku)

        lines = [OrderLine(bid.sku, 1)]
        now = self._now()
        order = Order(
            order_id=self._new_id(),
            customer_id=bid.bidder_id,
            status="PENDING",
            status_reason=None,
            total_amount=bid.amount,
            currency=bid.currency,
            items=(OrderItem(bid.sku, 1, bid.amount, seller=customer_id),),
            created_at=now,
            updated_at=now,
        )
        outcome = self._market.accept_bid(
            bid_id,
            customer_id,
            order,
            idempotency_key=accepted_order_key(bid_id),
            request_hash=request_hash(bid.bidder_id, lines),
            event=self._make_event(order),
        )
        return CreateResult(order=outcome.stored.order, created=outcome.created)

    # -- activity ----------------------------------------------------------------------------

    def activity(self, sku: str | None, page: int, size: int) -> Page[ActivityEntry]:
        return self._market.activity(sku, page, size)
