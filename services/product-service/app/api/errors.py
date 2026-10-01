"""Map domain errors to the shared error response shape."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.errors import DuplicateSku, ProductNotFound, StoreUnavailable, UnknownCategory
from retail_common.errors import error_response


async def _not_found(_request: Request, exc: Exception) -> JSONResponse:
    return error_response(404, "PRODUCT_NOT_FOUND", str(exc))


async def _duplicate(_request: Request, exc: Exception) -> JSONResponse:
    return error_response(409, "SKU_EXISTS", str(exc))


async def _unknown_category(_request: Request, exc: Exception) -> JSONResponse:
    return error_response(422, "UNKNOWN_CATEGORY", str(exc))


async def _store_unavailable(_request: Request, _exc: Exception) -> JSONResponse:
    # Generic on purpose: exception text from a driver can contain hostnames.
    return error_response(
        503,
        "STORE_UNAVAILABLE",
        "the product store is temporarily unavailable",
        {"Retry-After": "1"},
    )


def install_domain_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ProductNotFound, _not_found)
    app.add_exception_handler(DuplicateSku, _duplicate)
    app.add_exception_handler(UnknownCategory, _unknown_category)
    app.add_exception_handler(StoreUnavailable, _store_unavailable)
