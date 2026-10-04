"""In-memory stand-ins for the market's ports, with the PostgreSQL adapter's rules."""

from collections.abc import Sequence
from dataclasses import replace

from fakes import NOW, FakeRepository

from app.domain.errors import (
    BidNotFound,
    BidNotOpen,
    NotBidder,
    NotListed,
    NotOwner,
    OwnItem,
    SalePending,
    UnknownItem,
)
from app.domain.models import (
    ActivityEntry,
    Bid,
    BidOutcome,
    BidStatus,
    CreateOutcome,
    Listing,
    ListingStatus,
    Order,
    OutboxEvent,
    Page,
    StoredBid,
)

ACTIVE = ("OPEN", "SALE_PENDING")


class FakeOwners:
    """Inventory's answer to "who owns it": None is the platform; a missing SKU is unknown."""

    def __init__(self, owners: dict[str, str | None] | None = None) -> None:
        self.owners: dict[str, str | None] = dict(owners or {})
        self.calls: list[str] = []

    def owner_of(self, sku: str) -> str | None:
        self.calls.append(sku)
        if sku not in self.owners:
            raise UnknownItem(sku)
        return self.owners[sku]


def _page[T](items: Sequence[T], page: int, size: int) -> Page[T]:
    start = (page - 1) * size
    return Page(tuple(items[start : start + size]), page, size, len(items))


class FakeMarket:
    def __init__(self, orders: FakeRepository) -> None:
        self.orders = orders
        self.listings: dict[str, Listing] = {}
        self.bids: dict[str, Bid] = {}
        self.bid_keys: dict[tuple[str, str], tuple[str, str]] = {}  # (bidder, key) -> (id, hash)

    def _active(self, sku: str) -> Listing | None:
        return next(
            (x for x in self.listings.values() if x.sku == sku and x.status in ACTIVE), None
        )

    def _set_listing(self, listing: Listing, status: ListingStatus) -> Listing:
        self.listings[listing.listing_id] = replace(listing, status=status)
        return self.listings[listing.listing_id]

    def _close_open_bids(self, listing_id: str) -> None:
        for bid in list(self.bids.values()):
            if bid.listing_id == listing_id and bid.status == "OPEN":
                self.bids[bid.bid_id] = replace(bid, status="CLOSED")

    def put_up(self, listing: Listing) -> tuple[Listing, bool]:
        existing = self._active(listing.sku)
        if existing is not None:
            if existing.seller_id == listing.seller_id:
                return existing, False
            if existing.status == "SALE_PENDING":
                raise SalePending(listing.sku)
            self._set_listing(existing, "CANCELLED")
            self._close_open_bids(existing.listing_id)
        self.listings[listing.listing_id] = listing
        return listing, True

    def take_off(self, sku: str, seller_id: str) -> Listing:
        existing = self._active(sku)
        if existing is None:
            raise NotListed(sku)
        if existing.seller_id != seller_id:
            raise NotOwner(sku)
        if existing.status == "SALE_PENDING":
            raise SalePending(sku)
        self._close_open_bids(existing.listing_id)
        return self._set_listing(existing, "CANCELLED")

    def list_listings(
        self, sku: str | None, statuses: Sequence[ListingStatus], page: int, size: int
    ) -> Page[Listing]:
        found = [
            x for x in reversed(self.listings.values())
            if x.status in statuses and (sku is None or x.sku == sku)
        ]  # fmt: skip
        return _page(found, page, size)

    def find_bid_by_key(self, bidder_id: str, key: str) -> StoredBid | None:
        hit = self.bid_keys.get((bidder_id, key))
        return StoredBid(self.bids[hit[0]], hit[1]) if hit else None

    def place_bid(self, bid: Bid, *, request_hash: str, idempotency_key: str) -> BidOutcome:
        listing = self._active(bid.sku)
        if listing is None:
            raise NotListed(bid.sku)
        if listing.status == "SALE_PENDING":
            raise SalePending(bid.sku)
        if listing.seller_id == bid.bidder_id:
            raise OwnItem(bid.sku)
        existing = self.find_bid_by_key(bid.bidder_id, idempotency_key)
        if existing is not None:
            return BidOutcome(existing, created=False)
        stored = replace(bid, listing_id=listing.listing_id)
        self.bids[stored.bid_id] = stored
        self.bid_keys[(bid.bidder_id, idempotency_key)] = (stored.bid_id, request_hash)
        return BidOutcome(StoredBid(stored, request_hash), created=True)

    def get_bid(self, bid_id: str) -> Bid | None:
        return self.bids.get(bid_id)

    def withdraw_bid(self, bid_id: str, bidder_id: str) -> Bid:
        bid = self.bids.get(bid_id)
        if bid is None:
            raise BidNotFound(bid_id)
        if bid.bidder_id != bidder_id:
            raise NotBidder(bid_id)
        if bid.status != "OPEN":
            raise BidNotOpen(bid_id, bid.status)
        self.bids[bid_id] = replace(bid, status="WITHDRAWN")
        return self.bids[bid_id]

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
        bid = self.bids.get(bid_id)
        if bid is None:
            raise BidNotFound(bid_id)
        listing = self.listings[bid.listing_id]
        if listing.seller_id != seller_id:
            raise NotOwner(listing.sku)
        if bid.status in ("ACCEPTED", "FILLED") and bid.order_id:
            stored = next(
                s for s in self.orders.by_key.values() if s.order.order_id == bid.order_id
            )
            return CreateOutcome(stored=stored, created=False)
        if bid.status != "OPEN":
            raise BidNotOpen(bid_id, bid.status)
        if listing.status == "SALE_PENDING":
            raise SalePending(listing.sku)
        if listing.status != "OPEN":
            raise NotListed(listing.sku)
        outcome = self.orders.create_order(
            order, idempotency_key=idempotency_key, request_hash=request_hash, event=event
        )
        self._set_listing(listing, "SALE_PENDING")
        self.bids[bid_id] = replace(bid, status="ACCEPTED", order_id=order.order_id)
        return outcome

    def list_bids(
        self, sku: str | None, bidder_id: str | None, status: BidStatus | None, page: int, size: int
    ) -> Page[Bid]:
        found = [
            b for b in reversed(self.bids.values())
            if (sku is None or b.sku == sku)
            and (bidder_id is None or b.bidder_id == bidder_id)
            and (status is None or b.status == status)
        ]  # fmt: skip
        return _page(found, page, size)

    def activity(self, sku: str | None, page: int, size: int) -> Page[ActivityEntry]:
        entries = [
            ActivityEntry("LISTED", x.sku, x.created_at, from_id=x.seller_id)
            for x in self.listings.values()
        ] + [
            ActivityEntry("BID", b.sku, b.created_at, b.amount, b.currency, to_id=b.bidder_id, bid_id=b.bid_id)
            for b in self.bids.values()
        ]  # fmt: skip
        found = sorted(
            (e for e in entries if sku is None or e.sku == sku), key=lambda e: e.at, reverse=True
        )
        return _page(found, page, size)


__all__ = ["NOW", "FakeMarket", "FakeOwners"]
