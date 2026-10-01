"""Map domain errors to the shared error response shape."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.errors import StoreUnavailable
from retail_common.errors import store_unavailable_response


async def _store_unavailable(_request: Request, _exc: Exception) -> JSONResponse:
    return store_unavailable_response("the notification store is temporarily unavailable")


def install_domain_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StoreUnavailable, _store_unavailable)
