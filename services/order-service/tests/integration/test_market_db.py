"""The CloudPunks market against the real PostgreSQL (DESIGN.md section 16, ADR-19).

What the unit tests cannot show is here: the listing row lock really serializes accepting, bidding
and taking off, so two bids on one listing are never both accepted; and the order consumer settles
the bid and its listing in the same transaction as the order's status change.
"""

import threading
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from conftest import FakeCatalog, count
from sqlalchemy import Engine, text
from ulid import ULID

from app.domain.errors import BidNotOpen, NotListed, SalePending
from app.domain.market import MarketService
from app.domain.models import Order, OrderItem
from app.domain.transitions import InventoryOutcome, TransitionService
from app.events import order_created_event, order_status_updated_event
from app.repo.market import PostgresMarketRepository
from app.repo.transitions import PostgresTransitionStore

SELLER, BIDDER, OTHER = "itest-seller", "itest-bidder", "itest-other"


class Owners:
    def __init__(self) -> None:
        self.owners: dict[str, str | None] = {}

    def owner_of(self, sku: str) -> str | None:
        return self.owners[sku]


@pytest.fixture
def sku() -> str:
    return f"ITEST-CP-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def owners(sku: str) -> Owners:
    fake = Owners()
    fake.owners[sku] = SELLER
    return fake


@pytest.fixture
def market(engine: Engine, owners: Owners, sku: str) -> MarketService:
    catalog = FakeCatalog()
    catalog.add(sku, "30.00", currency="ETH")
    return MarketService(
        PostgresMarketRepository(engine),
        owners,
        catalog,
        new_id=lambda: str(ULID()),
        make_event=order_created_event,
        now=lambda: datetime.now(UTC),
    )


@pytest.fixture
def transitions(engine: Engine) -> TransitionService:
    return TransitionService(PostgresTransitionStore(engine), order_status_updated_event)


def bid(market: MarketService, bidder: str, sku: str, amount: str = "25.00") -> str:
    placed, _ = market.place_bid(bidder, f"itest-{uuid.uuid4()}", sku, Decimal(amount))
    return placed.bid_id


def statuses(engine: Engine, sku: str) -> tuple[list[str], dict[str, str]]:
    with engine.connect() as c:
        listing = c.execute(
            text("SELECT status FROM listings WHERE sku = :s ORDER BY created_at"), {"s": sku}
        ).scalars()
        bids = c.execute(text("SELECT bid_id, status FROM bids WHERE sku = :s"), {"s": sku}).all()
    return list(listing), {b.bid_id: b.status for b in bids}


def _order_for(customer: str, sku: str) -> Order:
    now = datetime.now(UTC)
    price = Decimal("25.00")
    items = (OrderItem(sku, 1, price, seller=SELLER),)
    return Order(str(ULID()), customer, "PENDING", None, price, "ETH", items, now, now)


def event_id() -> str:
    return "01TEST" + uuid.uuid4().hex[:20].upper()


def race(*calls: Any) -> list[Any]:
    """Run the calls together; return each one's result or the exception it raised."""
    results: list[Any] = [None] * len(calls)
    barrier = threading.Barrier(len(calls))

    def run(i: int) -> None:
        barrier.wait(timeout=10)
        try:
            results[i] = calls[i]()
        except Exception as exc:  # noqa: BLE001 - the outcome under test
            results[i] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(calls))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def test_the_migration_keeps_one_active_listing_per_cloudpunk(engine: Engine, sku: str) -> None:
    insert = "INSERT INTO listings (listing_id, sku, seller_id, status) VALUES (:i, :s, :u, 'OPEN')"
    with engine.begin() as c:
        c.execute(text(insert), {"i": str(ULID()), "s": sku, "u": SELLER})
    with pytest.raises(Exception, match="uq_listings_active_sku"), engine.begin() as c:
        c.execute(text(insert), {"i": str(ULID()), "s": sku, "u": OTHER})


def test_bid_amounts_and_statuses_are_checked_by_the_database(
    engine: Engine, market: MarketService, sku: str
) -> None:
    market.put_up(SELLER, sku)
    bid_id = bid(market, BIDDER, sku)
    for sql in (
        "UPDATE bids SET amount = 0 WHERE bid_id = :b",
        "UPDATE bids SET status = 'LOST' WHERE bid_id = :b",
    ):
        with pytest.raises(Exception, match="ck_bids_"), engine.begin() as c:
            c.execute(text(sql), {"b": bid_id})


def test_accepting_writes_the_order_its_seller_and_the_outbox_row_together(
    engine: Engine, market: MarketService, sku: str
) -> None:
    market.put_up(SELLER, sku)
    bid_id = bid(market, BIDDER, sku, "27.50")

    result = market.accept_bid(SELLER, bid_id)

    order = result.order
    assert (order.customer_id, order.total_amount, order.items[0].seller) == (
        BIDDER,
        Decimal("27.50"),
        SELLER,
    )
    payload_seller = count(
        engine,
        "SELECT count(*) FROM outbox WHERE payload->'data'->>'order_id' = :o "
        "AND payload->'data'->>'seller' = :s",
        o=order.order_id,
        s=SELLER,
    )
    assert payload_seller == 1
    assert statuses(engine, sku) == (["SALE_PENDING"], {bid_id: "ACCEPTED"})


def test_two_bids_accepted_at_once_make_exactly_one_order(
    engine: Engine, market: MarketService, owners: Owners
) -> None:
    """Five rounds, each on a fresh listing: one round is a coin toss, five are not."""
    for _ in range(5):
        sku = f"ITEST-CP-{uuid.uuid4().hex[:8]}"
        owners.owners[sku] = SELLER
        market._catalog.add(sku, "30.00", currency="ETH")  # type: ignore[attr-defined]
        market.put_up(SELLER, sku)
        first, second = bid(market, BIDDER, sku), bid(market, OTHER, sku, "26.00")

        results = race(
            lambda f=first: market.accept_bid(SELLER, f),
            lambda s=second: market.accept_bid(SELLER, s),
        )

        refused = [r for r in results if isinstance(r, Exception)]
        assert [type(e) for e in refused] == [SalePending], results
        assert count(engine, "SELECT count(*) FROM order_items WHERE sku = :s", s=sku) == 1


def test_accepting_and_taking_off_at_once_leave_one_consistent_outcome(
    engine: Engine, market: MarketService, sku: str
) -> None:
    market.put_up(SELLER, sku)
    bid_id = bid(market, BIDDER, sku)

    accepted, taken_off = race(
        lambda: market.accept_bid(SELLER, bid_id), lambda: market.take_off(SELLER, sku)
    )

    listing, bids = statuses(engine, sku)
    if isinstance(accepted, Exception):  # taking off won: no order, the bid closed
        assert isinstance(accepted, (BidNotOpen, NotListed))
        assert (listing, bids) == (["CANCELLED"], {bid_id: "CLOSED"})
    else:  # accepting won: the listing is mid-sale and cannot be taken off
        assert isinstance(taken_off, SalePending)
        assert (listing, bids) == (["SALE_PENDING"], {bid_id: "ACCEPTED"})


def test_putting_it_up_twice_at_once_makes_one_listing(
    engine: Engine, market: MarketService, sku: str
) -> None:
    results = race(lambda: market.put_up(SELLER, sku), lambda: market.put_up(SELLER, sku))

    assert sorted(created for _, created in results) == [False, True]
    assert results[0][0].listing_id == results[1][0].listing_id
    assert count(engine, "SELECT count(*) FROM listings WHERE sku = :s", s=sku) == 1


def test_a_confirmed_resale_fills_the_bid_sells_the_listing_and_closes_the_rest(
    engine: Engine, market: MarketService, transitions: TransitionService, sku: str
) -> None:
    market.put_up(SELLER, sku)
    winner, loser = bid(market, BIDDER, sku), bid(market, OTHER, sku, "20.00")
    order = market.accept_bid(SELLER, winner).order

    transitions.handle(event_id(), order.order_id, InventoryOutcome(reserved=True))

    assert statuses(engine, sku) == (["SOLD"], {winner: "FILLED", loser: "CLOSED"})
    feed = market.activity(sku, 1, 20).items
    sale = next(e for e in feed if e.kind == "SALE")
    assert (sale.from_id, sale.to_id, sale.amount, sale.currency) == (
        SELLER,
        BIDDER,
        Decimal("25.00"),
        "ETH",
    )
    assert {e.kind for e in feed} == {"SALE", "LISTED", "BID"}


def test_a_rejected_resale_fails_the_bid_and_opens_the_listing_again(
    engine: Engine, market: MarketService, transitions: TransitionService, sku: str
) -> None:
    market.put_up(SELLER, sku)
    first, waiting = bid(market, BIDDER, sku), bid(market, OTHER, sku, "20.00")
    order = market.accept_bid(SELLER, first).order

    transitions.handle(
        event_id(), order.order_id, InventoryOutcome(reserved=False, reason="OUT_OF_STOCK")
    )

    assert statuses(engine, sku) == (["OPEN"], {first: "FAILED", waiting: "OPEN"})
    assert market.accept_bid(SELLER, waiting).order.customer_id == OTHER  # bids again


def test_withdrawals_and_unlistings_appear_in_the_activity_feed(
    market: MarketService, sku: str
) -> None:
    market.put_up(SELLER, sku)
    market.withdraw_bid(BIDDER, bid(market, BIDDER, sku))
    market.take_off(SELLER, sku)

    kinds = [e.kind for e in market.activity(sku, 1, 20).items]

    assert sorted(kinds) == ["BID", "BID_WITHDRAWN", "LISTED", "UNLISTED"]
    assert market.activity(sku, 1, 2).total == 4


def test_a_withdrawn_bid_cannot_be_accepted_while_the_listing_is_still_open(
    engine: Engine, market: MarketService, sku: str
) -> None:
    market.put_up(SELLER, sku)
    bid_id = bid(market, BIDDER, sku)
    market.withdraw_bid(BIDDER, bid_id)

    with pytest.raises(BidNotOpen):
        market.accept_bid(SELLER, bid_id)
    # The repository refuses it too, under the lock: a bid withdrawn after the service read it.
    with pytest.raises(BidNotOpen):
        PostgresMarketRepository(engine).accept_bid(
            bid_id,
            SELLER,
            _order_for(BIDDER, sku),
            idempotency_key=f"bid-{bid_id}",
            request_hash="0" * 64,
            event=order_created_event(_order_for(BIDDER, sku)),
        )

    assert statuses(engine, sku) == (["OPEN"], {bid_id: "WITHDRAWN"})
    assert count(engine, "SELECT count(*) FROM order_items WHERE sku = :s", s=sku) == 0
