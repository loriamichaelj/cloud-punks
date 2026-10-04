"""HTTP routes for the CloudPunks market (DESIGN.md section 16.4): listings, bids, activity.

There is no authentication (a non-goal): ``customer_id`` names the caller, as it does for orders.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError

from app.api.schemas import (
    ActivityPageOut,
    BidAccept,
    BidCreate,
    BidId,
    BidOut,
    BidPageOut,
    CustomerId,
    IdempotencyKey,
    ListingCreate,
    ListingOut,
    ListingPageOut,
    OrderOut,
    Sku,
)
from app.domain.market import ACTIVE, MarketService
from app.domain.models import BidStatus, ListingStatus

router = APIRouter(prefix="/api/v1")

ListingFilter = Literal["ACTIVE", "OPEN", "SALE_PENDING", "SOLD", "CANCELLED", "ALL"]
_LISTING_FILTERS: dict[str, tuple[ListingStatus, ...]] = {
    "ACTIVE": ACTIVE,
    "ALL": ("OPEN", "SALE_PENDING", "SOLD", "CANCELLED"),
}


def get_market(request: Request) -> MarketService:
    service: MarketService = request.app.state.market_service
    return service


Market = Annotated[MarketService, Depends(get_market)]
PageNo = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.post("/listings", response_model=ListingOut, status_code=201)
def put_up(body: ListingCreate, response: Response, market: Market) -> ListingOut:
    """The owner puts a CloudPunk up for bid (it turns purple). Already up: 200 with that one."""
    listing, created = market.put_up(body.customer_id, body.sku)
    if not created:
        response.status_code = 200
    return ListingOut.from_domain(listing)


@router.delete("/listings/{sku}", response_model=ListingOut)
def take_off(sku: Sku, customer_id: Annotated[CustomerId, Query()], market: Market) -> ListingOut:
    """The owner takes it off the market (it turns blue); its open bids close."""
    return ListingOut.from_domain(market.take_off(customer_id, sku))


@router.get("/listings", response_model=ListingPageOut)
def list_listings(
    market: Market,
    sku: Annotated[Sku | None, Query()] = None,
    status: Annotated[ListingFilter, Query()] = "ACTIVE",
    page: PageNo = 1,
    size: PageSize = 20,
) -> ListingPageOut:
    """``status=ACTIVE`` (the default) is the purple set: open, or with a bid being confirmed."""
    statuses = _LISTING_FILTERS.get(status) or (status,)
    return ListingPageOut.from_domain(market.list_listings(sku, statuses, page, size))  # type: ignore[arg-type]


@router.post("/bids", response_model=BidOut, status_code=201)
def place_bid(
    body: BidCreate,
    response: Response,
    market: Market,
    idempotency_key: Annotated[IdempotencyKey, Header(alias="Idempotency-Key")],
) -> BidOut:
    """A bid on a CloudPunk that is up for bid. The same key and body again returns it (200)."""
    bid, created = market.place_bid(
        body.customer_id, idempotency_key, body.sku, body.decimal_amount()
    )
    if not created:
        response.status_code = 200
    return BidOut.from_domain(bid)


@router.get("/bids", response_model=BidPageOut)
def list_bids(
    market: Market,
    sku: Annotated[Sku | None, Query()] = None,
    customer_id: Annotated[CustomerId | None, Query()] = None,
    status: Annotated[BidStatus | None, Query()] = None,
    page: PageNo = 1,
    size: PageSize = 20,
) -> BidPageOut:
    """Bids on a CloudPunk (``sku``) or by a customer (``customer_id``); at least one is needed."""
    if sku is None and customer_id is None:
        raise RequestValidationError(
            [{"loc": ("query", "sku"), "msg": "give sku or customer_id", "type": "missing"}]
        )
    return BidPageOut.from_domain(market.list_bids(sku, customer_id, status, page, size))


@router.delete("/bids/{bid_id}", response_model=BidOut)
def withdraw_bid(
    bid_id: BidId, customer_id: Annotated[CustomerId, Query()], market: Market
) -> BidOut:
    return BidOut.from_domain(market.withdraw_bid(customer_id, bid_id))


@router.post("/bids/{bid_id}/accept", response_model=OrderOut, status_code=202)
def accept_bid(
    bid_id: BidId, body: Annotated[BidAccept, Body()], response: Response, market: Market
) -> OrderOut:
    """The owner accepts a bid: 202 with the bidder's order, PENDING until inventory moves the
    CloudPunk. Accepting it again returns the same order (200)."""
    result = market.accept_bid(body.customer_id, bid_id)
    if not result.created:
        response.status_code = 200
    response.headers["Location"] = f"/api/v1/orders/{result.order.order_id}"
    return OrderOut.from_domain(result.order)


@router.get("/activity", response_model=ActivityPageOut)
def activity(
    market: Market,
    sku: Annotated[Sku | None, Query()] = None,
    page: PageNo = 1,
    size: PageSize = 20,
) -> ActivityPageOut:
    """Sales, listings and bids, newest first; for one CloudPunk with ``sku``."""
    return ActivityPageOut.from_domain(market.activity(sku, page, size))
