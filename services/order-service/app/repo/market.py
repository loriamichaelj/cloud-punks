"""PostgreSQL adapter for ``MarketRepository``: listings, bids and the activity feed.

Every change runs in ONE transaction that first locks the CloudPunk's listing row
(``SELECT ... FOR UPDATE``), so putting it up, bidding, accepting and taking it off are serialized
per CloudPunk: a bid can never be accepted twice, nor accepted after the listing was taken off,
and two bids on one listing cannot both be accepted (DESIGN.md section 16, ADR-19). Locks are
always taken listing first, then bid, here and in the order consumer, so they cannot deadlock.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import (
    ColumnElement,
    DateTime,
    Engine,
    Numeric,
    Row,
    String,
    cast,
    func,
    literal,
    null,
    select,
    union_all,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app.domain.errors import (
    BidNotFound,
    BidNotOpen,
    NotBidder,
    NotListed,
    NotOwner,
    OwnItem,
    SalePending,
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
from app.repo.orders import fetch_order, insert_order, store_errors
from app.repo.tables import ACTIVE_LISTING, bids, listings, order_items, orders


def _to_listing(row: Row[Any]) -> Listing:
    return Listing(
        listing_id=row.listing_id,
        sku=row.sku,
        seller_id=row.seller_id,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_bid(row: Row[Any]) -> Bid:
    return Bid(
        bid_id=row.bid_id,
        listing_id=row.listing_id,
        sku=row.sku,
        bidder_id=row.bidder_id,
        amount=row.amount,
        currency=row.currency,
        status=row.status,
        order_id=row.order_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _active_listing(connection: Connection, sku: str) -> Row[Any] | None:
    """The CloudPunk's active listing, locked until the transaction ends."""
    return connection.execute(
        select(listings)
        .where(listings.c.sku == sku, listings.c.status.in_(ACTIVE_LISTING))
        .with_for_update()
    ).one_or_none()


def _close_open_bids(connection: Connection, listing_id: str) -> None:
    connection.execute(
        update(bids)
        .where(bids.c.listing_id == listing_id, bids.c.status == "OPEN")
        .values(status="CLOSED")
    )


def _page[T](items: Sequence[T], page: int, size: int, total: int) -> Page[T]:
    return Page(items=tuple(items), page=page, size=size, total=int(total))


class PostgresMarketRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # -- listings ------------------------------------------------------------------------------

    def put_up(self, listing: Listing) -> tuple[Listing, bool]:
        with store_errors(), self._engine.begin() as connection:
            existing = _active_listing(connection, listing.sku)
            if existing is not None:
                if existing.seller_id == listing.seller_id:
                    return _to_listing(existing), False
                if existing.status == "SALE_PENDING":
                    raise SalePending(listing.sku)
                # An open listing left by a former owner (the caller checked who owns it now):
                # it can no longer be honoured, so it ends and its bids close.
                connection.execute(
                    update(listings)
                    .where(listings.c.listing_id == existing.listing_id)
                    .values(status="CANCELLED")
                )
                _close_open_bids(connection, existing.listing_id)
            try:
                with connection.begin_nested():
                    connection.execute(
                        pg_insert(listings).values(
                            listing_id=listing.listing_id,
                            sku=listing.sku,
                            seller_id=listing.seller_id,
                            status="OPEN",
                        )
                    )
            except IntegrityError:
                # A concurrent request put it up first (the one-active-listing index decided).
                winner = _active_listing(connection, listing.sku)
                if winner is None:  # pragma: no cover - the conflicting row is committed
                    raise
                if winner.seller_id != listing.seller_id:
                    raise NotOwner(listing.sku) from None
                return _to_listing(winner), False
            row = connection.execute(
                select(listings).where(listings.c.listing_id == listing.listing_id)
            ).one()
            return _to_listing(row), True

    def take_off(self, sku: str, seller_id: str) -> Listing:
        with store_errors(), self._engine.begin() as connection:
            existing = _active_listing(connection, sku)
            if existing is None:
                raise NotListed(sku)
            if existing.seller_id != seller_id:
                raise NotOwner(sku)
            if existing.status == "SALE_PENDING":
                raise SalePending(sku)
            row = connection.execute(
                update(listings)
                .where(listings.c.listing_id == existing.listing_id)
                .values(status="CANCELLED")
                .returning(*listings.c)
            ).one()
            _close_open_bids(connection, existing.listing_id)
            return _to_listing(row)

    def list_listings(
        self, sku: str | None, statuses: Sequence[ListingStatus], page: int, size: int
    ) -> Page[Listing]:
        conditions: list[ColumnElement[bool]] = [listings.c.status.in_(list(statuses))]
        if sku is not None:
            conditions.append(listings.c.sku == sku)
        with store_errors(), self._engine.connect() as connection:
            rows = connection.execute(
                select(listings)
                .where(*conditions)
                .order_by(listings.c.created_at.desc(), listings.c.listing_id.desc())
                .limit(size)
                .offset((page - 1) * size)
            ).all()
            total = connection.execute(
                select(func.count()).select_from(listings).where(*conditions)
            ).scalar_one()
        return _page([_to_listing(r) for r in rows], page, size, total)

    # -- bids ----------------------------------------------------------------------------------

    def find_bid_by_key(self, bidder_id: str, key: str) -> StoredBid | None:
        with store_errors(), self._engine.connect() as connection:
            return self._find_bid(connection, bidder_id, key)

    def place_bid(self, bid: Bid, *, request_hash: str, idempotency_key: str) -> BidOutcome:
        with store_errors(), self._engine.begin() as connection:
            listing = _active_listing(connection, bid.sku)
            if listing is None:
                raise NotListed(bid.sku)
            if listing.status == "SALE_PENDING":
                raise SalePending(bid.sku)
            if listing.seller_id == bid.bidder_id:
                raise OwnItem(bid.sku)
            inserted = connection.execute(
                pg_insert(bids)
                .values(
                    bid_id=bid.bid_id,
                    listing_id=listing.listing_id,
                    sku=bid.sku,
                    bidder_id=bid.bidder_id,
                    amount=bid.amount,
                    currency=bid.currency,
                    status="OPEN",
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
                .on_conflict_do_nothing(index_elements=[bids.c.bidder_id, bids.c.idempotency_key])
                .returning(bids.c.bid_id)
            ).scalar_one_or_none()
            if inserted is None:
                # A concurrent request with the same key committed first. Write nothing.
                existing = self._find_bid(connection, bid.bidder_id, idempotency_key)
                if existing is None:  # pragma: no cover - a committed row cannot vanish
                    raise RuntimeError("idempotency conflict without a stored bid")
                return BidOutcome(stored=existing, created=False)
            row = connection.execute(select(bids).where(bids.c.bid_id == bid.bid_id)).one()
            return BidOutcome(StoredBid(_to_bid(row), row.request_hash.strip()), created=True)

    def get_bid(self, bid_id: str) -> Bid | None:
        with store_errors(), self._engine.connect() as connection:
            row = connection.execute(select(bids).where(bids.c.bid_id == bid_id)).one_or_none()
        return _to_bid(row) if row else None

    def withdraw_bid(self, bid_id: str, bidder_id: str) -> Bid:
        with store_errors(), self._engine.begin() as connection:
            row = connection.execute(
                select(bids).where(bids.c.bid_id == bid_id).with_for_update()
            ).one_or_none()
            if row is None:
                raise BidNotFound(bid_id)
            if row.bidder_id != bidder_id:
                raise NotBidder(bid_id)
            if row.status != "OPEN":
                raise BidNotOpen(bid_id, row.status)
            updated = connection.execute(
                update(bids)
                .where(bids.c.bid_id == bid_id)
                .values(status="WITHDRAWN")
                .returning(*bids.c)
            ).one()
            return _to_bid(updated)

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
        with store_errors(), self._engine.begin() as connection:
            listing_id = connection.execute(
                select(bids.c.listing_id).where(bids.c.bid_id == bid_id)
            ).scalar_one_or_none()
            if listing_id is None:
                raise BidNotFound(bid_id)
            # Listing first, then the bid: the order every writer takes them in.
            listing = connection.execute(
                select(listings).where(listings.c.listing_id == listing_id).with_for_update()
            ).one()
            bid = connection.execute(
                select(bids).where(bids.c.bid_id == bid_id).with_for_update()
            ).one()

            if listing.seller_id != seller_id:
                raise NotOwner(listing.sku)
            if bid.status in ("ACCEPTED", "FILLED") and bid.order_id is not None:
                stored = fetch_order(connection, bid.order_id)  # accepted already: same order
                if stored is None:  # pragma: no cover - the foreign key keeps it
                    raise RuntimeError("accepted bid without its order")
                return CreateOutcome(stored=stored, created=False)
            if bid.status != "OPEN":
                raise BidNotOpen(bid_id, bid.status)
            if listing.status == "SALE_PENDING":
                raise SalePending(listing.sku)
            if listing.status != "OPEN":
                raise NotListed(listing.sku)

            if not insert_order(
                connection,
                order,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                event=event,
            ):  # pragma: no cover - the bid's key is unique and the bid was still OPEN
                raise RuntimeError("an open bid already has an order")
            connection.execute(
                update(listings)
                .where(listings.c.listing_id == listing_id)
                .values(status="SALE_PENDING")
            )
            connection.execute(
                update(bids)
                .where(bids.c.bid_id == bid_id)
                .values(status="ACCEPTED", order_id=order.order_id)
            )
            stored = fetch_order(connection, order.order_id)
        if stored is None:  # pragma: no cover - inserted in this very transaction
            raise RuntimeError("order vanished inside its own transaction")
        return CreateOutcome(stored=stored, created=True)

    def list_bids(
        self, sku: str | None, bidder_id: str | None, status: BidStatus | None, page: int, size: int
    ) -> Page[Bid]:
        conditions: list[ColumnElement[bool]] = []
        if sku is not None:
            conditions.append(bids.c.sku == sku)
        if bidder_id is not None:
            conditions.append(bids.c.bidder_id == bidder_id)
        if status is not None:
            conditions.append(bids.c.status == status)
        with store_errors(), self._engine.connect() as connection:
            rows = connection.execute(
                select(bids)
                .where(*conditions)
                .order_by(bids.c.created_at.desc(), bids.c.bid_id.desc())
                .limit(size)
                .offset((page - 1) * size)
            ).all()
            total = connection.execute(
                select(func.count()).select_from(bids).where(*conditions)
            ).scalar_one()
        return _page([_to_bid(r) for r in rows], page, size, total)

    # -- activity ------------------------------------------------------------------------------

    def activity(self, sku: str | None, page: int, size: int) -> Page[ActivityEntry]:
        money = Numeric(10, 2)
        no_amount, no_text = cast(null(), money), cast(null(), String(64))

        def entries(kind: str, *columns: Any) -> Any:
            return literal(kind).label("kind"), *columns

        sales = (
            select(
                *entries(
                    "SALE",
                    order_items.c.sku.label("sku"),
                    cast(orders.c.updated_at, DateTime(timezone=True)).label("at"),
                    order_items.c.unit_price.label("amount"),
                    cast(orders.c.currency, String(3)).label("currency"),
                    order_items.c.seller.label("from_id"),
                    orders.c.customer_id.label("to_id"),
                    cast(orders.c.order_id, String(26)).label("order_id"),
                    cast(null(), String(26)).label("bid_id"),
                )
            )
            .select_from(orders.join(order_items, order_items.c.order_id == orders.c.order_id))
            .where(orders.c.status == "CONFIRMED")
        )

        def listing_rows(kind: str, at: Any, *where: Any) -> Any:
            return select(
                *entries(
                    kind,
                    listings.c.sku.label("sku"),
                    at.label("at"),
                    no_amount.label("amount"),
                    cast(null(), String(3)).label("currency"),
                    listings.c.seller_id.label("from_id"),
                    no_text.label("to_id"),
                    cast(null(), String(26)).label("order_id"),
                    cast(null(), String(26)).label("bid_id"),
                )
            ).where(*where)

        def bid_rows(kind: str, at: Any, *where: Any) -> Any:
            return select(
                *entries(
                    kind,
                    bids.c.sku.label("sku"),
                    at.label("at"),
                    bids.c.amount.label("amount"),
                    cast(bids.c.currency, String(3)).label("currency"),
                    no_text.label("from_id"),
                    bids.c.bidder_id.label("to_id"),
                    cast(null(), String(26)).label("order_id"),
                    cast(bids.c.bid_id, String(26)).label("bid_id"),
                )
            ).where(*where)

        parts = [
            sales.where(order_items.c.sku == sku) if sku else sales,
            listing_rows(
                "LISTED", listings.c.created_at, *([listings.c.sku == sku] if sku else [])
            ),
            listing_rows(
                "UNLISTED",
                listings.c.updated_at,
                listings.c.status == "CANCELLED",
                *([listings.c.sku == sku] if sku else []),
            ),
            bid_rows("BID", bids.c.created_at, *([bids.c.sku == sku] if sku else [])),
            bid_rows(
                "BID_WITHDRAWN",
                bids.c.updated_at,
                bids.c.status == "WITHDRAWN",
                *([bids.c.sku == sku] if sku else []),
            ),
        ]
        feed = union_all(*parts).subquery("feed")
        with store_errors(), self._engine.connect() as connection:
            rows = connection.execute(
                select(feed)
                .order_by(feed.c.at.desc(), feed.c.kind)
                .limit(size)
                .offset((page - 1) * size)
            ).all()
            total = connection.execute(select(func.count()).select_from(feed)).scalar_one()
        return _page(
            [
                ActivityEntry(
                    kind=r.kind,
                    sku=r.sku,
                    at=r.at,
                    amount=r.amount,
                    currency=r.currency.strip() if r.currency else None,
                    from_id=r.from_id,
                    to_id=r.to_id,
                    order_id=r.order_id.strip() if r.order_id else None,
                    bid_id=r.bid_id.strip() if r.bid_id else None,
                )
                for r in rows
            ],
            page,
            size,
            total,
        )

    # -- helpers -------------------------------------------------------------------------------

    @staticmethod
    def _find_bid(connection: Connection, bidder_id: str, key: str) -> StoredBid | None:
        row = connection.execute(
            select(bids).where(bids.c.bidder_id == bidder_id, bids.c.idempotency_key == key)
        ).one_or_none()
        return StoredBid(_to_bid(row), row.request_hash.strip()) if row else None
