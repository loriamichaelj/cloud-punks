"""Map domain errors to the shared error response shape."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.errors import (
    BidNotFound,
    BidNotOpen,
    IdempotencyKeyReused,
    MixedCurrency,
    NotBidder,
    NotListed,
    NotOwner,
    OrderNotFound,
    OutOfStock,
    OwnItem,
    ProductInactive,
    SalePending,
    StoreUnavailable,
    UnknownItem,
    UnknownProduct,
    UpstreamUnavailable,
)
from retail_common.errors import error_response, store_unavailable_response


async def _not_found(_request: Request, exc: Exception) -> JSONResponse:
    return error_response(404, "ORDER_NOT_FOUND", str(exc))


async def _out_of_stock(_request: Request, exc: Exception) -> JSONResponse:
    # "SKU-TSHIRT-BLK-M: requested 2, available 1" (DESIGN.md section 4)
    return error_response(409, "OUT_OF_STOCK", str(exc))


async def _key_reused(_request: Request, exc: Exception) -> JSONResponse:
    return error_response(422, "IDEMPOTENCY_KEY_REUSED", str(exc))


async def _unknown_product(_request: Request, exc: Exception) -> JSONResponse:
    return error_response(422, "UNKNOWN_PRODUCT", str(exc))


async def _product_inactive(_request: Request, exc: Exception) -> JSONResponse:
    return error_response(422, "PRODUCT_INACTIVE", str(exc))


async def _mixed_currency(_request: Request, exc: Exception) -> JSONResponse:
    return error_response(422, "MIXED_CURRENCY", str(exc))


async def _upstream_unavailable(_request: Request, exc: Exception) -> JSONResponse:
    # Nothing was written: the client can simply retry the same request with the same key.
    return error_response(503, "UPSTREAM_UNAVAILABLE", str(exc), {"Retry-After": "1"})


async def _store_unavailable(_request: Request, _exc: Exception) -> JSONResponse:
    return store_unavailable_response("the order store is temporarily unavailable")


# The market (DESIGN.md section 16.4): a 409 is "not now, the state says no"; a 422 is "never".
_MARKET_ERRORS: tuple[tuple[type[Exception], int, str], ...] = (
    (NotOwner, 409, "NOT_OWNER"),
    (NotListed, 409, "NOT_LISTED"),
    (SalePending, 409, "SALE_PENDING"),
    (BidNotOpen, 409, "BID_NOT_OPEN"),
    (NotBidder, 409, "NOT_BIDDER"),  # there is no auth, so no 403
    (OwnItem, 422, "OWN_ITEM"),
    (BidNotFound, 404, "BID_NOT_FOUND"),
    (UnknownItem, 404, "ITEM_NOT_FOUND"),
)


def _market_handler(
    status: int, code: str
) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handle(_request: Request, exc: Exception) -> JSONResponse:
        return error_response(status, code, str(exc))

    return handle


def install_domain_error_handlers(app: FastAPI) -> None:
    for error, status, code in _MARKET_ERRORS:
        app.add_exception_handler(error, _market_handler(status, code))
    app.add_exception_handler(OrderNotFound, _not_found)
    app.add_exception_handler(OutOfStock, _out_of_stock)
    app.add_exception_handler(IdempotencyKeyReused, _key_reused)
    app.add_exception_handler(UnknownProduct, _unknown_product)
    app.add_exception_handler(ProductInactive, _product_inactive)
    app.add_exception_handler(MixedCurrency, _mixed_currency)
    app.add_exception_handler(UpstreamUnavailable, _upstream_unavailable)
    app.add_exception_handler(StoreUnavailable, _store_unavailable)
