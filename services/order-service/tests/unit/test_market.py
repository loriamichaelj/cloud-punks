"""The CloudPunks market through the API (DESIGN.md section 16.4), on in-memory fakes.

What these cannot show (the row locks deciding a race, the settlement in the consumer's
transaction) is in tests/integration/test_market_db.py.
"""

from typing import Any

import pytest
from fakes import FakeCatalog, FakeRepository, FakeStock, make_settings, product
from fakes_market import FakeMarket, FakeOwners
from fastapi.testclient import TestClient

from app.domain.models import Order, OrderItem
from app.main import create_app

PUNK = "CP-0042"
ALICE, BOB, CAROL = "cust-alice", "cust-bob", "cust-carol"


class Market:
    def __init__(self) -> None:
        self.orders = FakeRepository()
        self.market = FakeMarket(self.orders)
        self.owners = FakeOwners({PUNK: ALICE, "CP-0001": None})
        catalog = FakeCatalog(product(PUNK, "30.00", currency="ETH"), product("CP-0001", "20.00"))
        self.client = TestClient(
            create_app(
                make_settings(),
                repository=self.orders,
                catalog=catalog,
                stock=FakeStock({PUNK: 0}),
                market=self.market,
                owners=self.owners,
            )
        )
        self.keys = 0

    def put_up(self, customer: str = ALICE, sku: str = PUNK) -> Any:
        return self.client.post("/api/v1/listings", json={"customer_id": customer, "sku": sku})

    def bid(self, customer: str, amount: Any, key: str | None = None, sku: str = PUNK) -> Any:
        self.keys += 1
        return self.client.post(
            "/api/v1/bids",
            json={"customer_id": customer, "sku": sku, "amount": amount},
            headers={"Idempotency-Key": key or f"bid-key-{self.keys}"},
        )

    def accept(self, bid_id: str, customer: str = ALICE) -> Any:
        return self.client.post(f"/api/v1/bids/{bid_id}/accept", json={"customer_id": customer})


@pytest.fixture
def m() -> Market:
    return Market()


def code(response: Any) -> str:
    return str(response.json()["error"]["code"])


# --- up for bid ---------------------------------------------------------------------------------


def test_the_owner_puts_it_up_for_bid_and_doing_it_again_is_the_same_listing(m: Market) -> None:
    first = m.put_up()
    again = m.put_up()

    assert first.status_code == 201
    assert again.status_code == 200
    assert first.json()["listing_id"] == again.json()["listing_id"]
    assert (first.json()["sku"], first.json()["seller"], first.json()["status"]) == (
        PUNK,
        ALICE,
        "OPEN",
    )


def test_only_the_owner_can_put_it_up(m: Market) -> None:
    assert (m.put_up(BOB).status_code, code(m.put_up(BOB))) == (409, "NOT_OWNER")


def test_the_platforms_unsold_cloudpunks_are_bought_not_bid_on(m: Market) -> None:
    response = m.put_up(ALICE, "CP-0001")  # owner None: the platform holds it (red)
    assert (response.status_code, code(response)) == (409, "NOT_OWNER")


def test_an_item_inventory_does_not_know_is_404(m: Market) -> None:
    response = m.put_up(ALICE, "CP-9999")
    assert (response.status_code, code(response)) == (404, "ITEM_NOT_FOUND")


def test_taking_it_off_cancels_the_listing_and_closes_its_open_bids(m: Market) -> None:
    m.put_up()
    bid = m.bid(BOB, "25.00").json()

    off = m.client.delete(f"/api/v1/listings/{PUNK}", params={"customer_id": ALICE})

    assert (off.status_code, off.json()["status"]) == (200, "CANCELLED")
    assert m.market.bids[bid["bid_id"]].status == "CLOSED"
    assert m.client.get("/api/v1/listings").json()["total"] == 0


@pytest.mark.parametrize(
    ("customer", "listed", "expected"),
    [(BOB, True, "NOT_OWNER"), (ALICE, False, "NOT_LISTED")],
)
def test_taking_off_needs_the_owner_and_a_listing(
    m: Market, customer: str, listed: bool, expected: str
) -> None:
    if listed:
        m.put_up()
    response = m.client.delete(f"/api/v1/listings/{PUNK}", params={"customer_id": customer})
    assert (response.status_code, code(response)) == (409, expected)


# --- bids ---------------------------------------------------------------------------------------


def test_a_bid_on_a_listed_cloudpunk_is_open_and_in_the_products_currency(m: Market) -> None:
    m.put_up()

    response = m.bid(BOB, "25.50")

    assert response.status_code == 201
    body = response.json()
    assert (body["sku"], body["bidder"], body["amount"], body["currency"], body["status"]) == (
        PUNK, BOB, "25.50", "ETH", "OPEN",
    )  # fmt: skip
    assert body["listing_id"] == m.put_up().json()["listing_id"]


def test_the_same_key_and_body_returns_the_same_bid_and_a_different_body_is_refused(
    m: Market,
) -> None:
    m.put_up()
    first = m.bid(BOB, "25.00", key="k-1")
    replay = m.bid(BOB, "25.00", key="k-1")
    changed = m.bid(BOB, "26.00", key="k-1")

    assert (first.status_code, replay.status_code) == (201, 200)
    assert first.json()["bid_id"] == replay.json()["bid_id"]
    assert (changed.status_code, code(changed)) == (422, "IDEMPOTENCY_KEY_REUSED")
    assert len(m.market.bids) == 1


def test_bids_need_a_listing_and_the_owner_cannot_bid(m: Market) -> None:
    not_listed = m.bid(BOB, "25.00")
    m.put_up()
    own = m.bid(ALICE, "25.00")

    assert (not_listed.status_code, code(not_listed)) == (409, "NOT_LISTED")
    assert (own.status_code, code(own)) == (422, "OWN_ITEM")


@pytest.mark.parametrize("amount", [25, 25.5, "0", "0.00", "25.001", "-1", "1e3", "", "100000000"])
def test_an_amount_must_be_a_positive_two_decimal_string(m: Market, amount: Any) -> None:
    m.put_up()
    response = m.bid(BOB, amount)
    assert (response.status_code, code(response)) == (422, "VALIDATION_ERROR")


def test_a_bid_needs_an_idempotency_key(m: Market) -> None:
    m.put_up()
    response = m.client.post(
        "/api/v1/bids", json={"customer_id": BOB, "sku": PUNK, "amount": "25.00"}
    )
    assert response.status_code == 422


def test_listing_bids_needs_a_cloudpunk_or_a_customer(m: Market) -> None:
    m.put_up()
    m.bid(BOB, "25.00")

    assert m.client.get("/api/v1/bids").status_code == 422
    assert m.client.get("/api/v1/bids", params={"sku": PUNK}).json()["total"] == 1
    assert m.client.get("/api/v1/bids", params={"customer_id": BOB}).json()["total"] == 1
    assert m.client.get("/api/v1/bids", params={"customer_id": CAROL}).json()["total"] == 0


def test_the_bidder_withdraws_an_open_bid_once(m: Market) -> None:
    m.put_up()
    bid_id = m.bid(BOB, "25.00").json()["bid_id"]
    url = f"/api/v1/bids/{bid_id}"

    wrong = m.client.delete(url, params={"customer_id": CAROL})
    done = m.client.delete(url, params={"customer_id": BOB})
    again = m.client.delete(url, params={"customer_id": BOB})

    assert (wrong.status_code, code(wrong)) == (409, "NOT_BIDDER")
    assert (done.status_code, done.json()["status"]) == (200, "WITHDRAWN")
    assert (again.status_code, code(again)) == (409, "BID_NOT_OPEN")


def test_an_unknown_bid_is_404(m: Market) -> None:
    response = m.client.delete(
        "/api/v1/bids/01J9Z6Q4W8K3M2N1P0R7S5T999", params={"customer_id": BOB}
    )
    assert (response.status_code, code(response)) == (404, "BID_NOT_FOUND")


# --- accepting a bid ----------------------------------------------------------------------------


def test_accepting_creates_the_bidders_order_at_the_bid_amount_bought_from_the_owner(
    m: Market,
) -> None:
    m.put_up()
    bid_id = m.bid(BOB, "25.00").json()["bid_id"]

    response = m.accept(bid_id)

    assert response.status_code == 202
    order = response.json()
    assert response.headers["Location"] == f"/api/v1/orders/{order['order_id']}"
    assert (order["customer_id"], order["status"], order["total_amount"], order["currency"]) == (
        BOB, "PENDING", "25.00", "ETH",
    )  # fmt: skip
    assert order["items"] == [{"sku": PUNK, "quantity": 1, "unit_price": "25.00", "seller": ALICE}]
    (event,) = m.orders.outbox
    assert (event.payload["data"]["customer_id"], event.payload["data"]["seller"]) == (BOB, ALICE)
    assert m.market.bids[bid_id].status == "ACCEPTED"
    (listing,) = m.client.get("/api/v1/listings").json()["items"]  # still purple
    assert listing["status"] == "SALE_PENDING"


def test_accepting_the_same_bid_again_returns_the_same_order(m: Market) -> None:
    m.put_up()
    bid_id = m.bid(BOB, "25.00").json()["bid_id"]

    first, again = m.accept(bid_id), m.accept(bid_id)

    assert (first.status_code, again.status_code) == (202, 200)
    assert first.json()["order_id"] == again.json()["order_id"]
    assert len(m.orders.outbox) == 1


def test_a_second_bid_cannot_be_accepted_while_the_first_is_being_confirmed(m: Market) -> None:
    m.put_up()
    first = m.bid(BOB, "25.00").json()["bid_id"]
    second = m.bid(CAROL, "26.00").json()["bid_id"]
    m.accept(first)

    response = m.accept(second)

    assert (response.status_code, code(response)) == (409, "SALE_PENDING")
    late = m.bid("cust-dave", "40.00")
    assert (late.status_code, code(late)) == (409, "SALE_PENDING")


def test_only_the_owner_accepts_and_only_an_open_bid(m: Market) -> None:
    m.put_up()
    bid_id = m.bid(BOB, "25.00").json()["bid_id"]
    stranger = m.accept(bid_id, CAROL)
    m.client.delete(f"/api/v1/bids/{bid_id}", params={"customer_id": BOB})
    withdrawn = m.accept(bid_id)

    assert (stranger.status_code, code(stranger)) == (409, "NOT_OWNER")
    assert (withdrawn.status_code, code(withdrawn)) == (409, "BID_NOT_OPEN")
    assert m.orders.outbox == []


# --- reads --------------------------------------------------------------------------------------


def test_listings_default_to_the_active_purple_set(m: Market) -> None:
    m.put_up()
    m.client.delete(f"/api/v1/listings/{PUNK}", params={"customer_id": ALICE})
    m.put_up()

    active = m.client.get("/api/v1/listings").json()
    everything = m.client.get("/api/v1/listings", params={"status": "ALL"}).json()

    assert active["total"] == 1
    assert everything["total"] == 2
    assert m.client.get("/api/v1/listings", params={"status": "nope"}).status_code == 422


def test_activity_entries_name_who_it_came_from_and_went_to(m: Market) -> None:
    m.put_up()
    m.bid(BOB, "25.00")

    items = m.client.get("/api/v1/activity", params={"sku": PUNK}).json()["items"]

    kinds = {i["kind"]: i for i in items}
    assert kinds["LISTED"]["from"] == ALICE
    assert (kinds["BID"]["to"], kinds["BID"]["amount"], kinds["BID"]["currency"]) == (
        BOB,
        "25.00",
        "ETH",
    )
    assert set(kinds["BID"]) == {
        "kind",
        "sku",
        "at",
        "amount",
        "currency",
        "from",
        "to",
        "order_id",
        "bid_id",
    }


# --- the order's seller -------------------------------------------------------------------------


def _order(*sellers: str | None) -> Order:
    from fakes import NOW

    items = tuple(
        OrderItem(f"CP-{i:04d}", 1, product().price, seller=s) for i, s in enumerate(sellers)
    )
    return Order(
        "01J9Z6Q4W8K3M2N1P0R7S5T001", "c", "PENDING", None, product().price, "ETH", items, NOW, NOW
    )


def test_an_order_has_a_seller_only_when_every_item_comes_from_the_same_one() -> None:
    assert _order(None).seller is None
    assert _order(ALICE).seller == ALICE
    assert _order(ALICE, BOB).seller is None
    assert _order(ALICE, None).seller is None
