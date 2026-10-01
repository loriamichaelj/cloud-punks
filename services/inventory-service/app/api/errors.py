"""Map domain errors to the shared error response shape."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.errors import StockNotFound, StoreUnavailable
from retail_common.errors import error_response, store_unavailable_response


async def _not_found(_request: Request, exc: Exception) -> JSONResponse:
    return error_response(404, "INVENTORY_NOT_FOUND", str(exc))


async def _store_unavailable(_request: Request, _exc: Exception) -> JSONResponse:
    return store_unavailable_response("the inventory store is temporarily unavailable")


def install_domain_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StockNotFound, _not_found)
    app.add_exception_handler(StoreUnavailable, _store_unavailable)
