"""Adapters for the synchronous dependencies (DESIGN.md section 3): prices from the product service,
and the advisory stock pre-check and a CloudPunk's owner from the inventory service."""

import contextvars
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from app.domain.errors import UnexpectedUpstreamResponse, UnknownItem, UpstreamUnavailable
from app.domain.models import OrderLine, ProductInfo, StockLine, StockReport
from retail_common.errors import UpstreamUnavailableError
from retail_common.http_client import ServiceHttpClient

MAX_PARALLEL_LOOKUPS = 8


def _parallel[T, R](
    executor: ThreadPoolExecutor, fn: Callable[[T], R], items: Sequence[T]
) -> list[R]:
    """Run ``fn`` over ``items`` in worker threads, each inside a copy of the caller's context so
    the correlation id (a ContextVar) reaches the outbound ``X-Correlation-ID`` header."""
    futures = [executor.submit(contextvars.copy_context().run, fn, item) for item in items]
    return [future.result() for future in futures]


class HttpPriceCatalog:
    def __init__(self, client: ServiceHttpClient, executor: ThreadPoolExecutor) -> None:
        self._client = client
        self._executor = executor

    def get_products(self, skus: Sequence[str]) -> Mapping[str, ProductInfo]:
        try:
            results = _parallel(self._executor, self._fetch, list(skus))
        except UpstreamUnavailableError as exc:
            raise UpstreamUnavailable("product-service") from exc
        return {info.sku: info for info in results if info is not None}

    def _fetch(self, sku: str) -> ProductInfo | None:
        response = self._client.get(f"/api/v1/products/{quote(sku, safe='')}")
        if response.status_code == 404:
            return None  # an unknown SKU is the customer's problem, not an outage
        if response.status_code != 200:
            raise UnexpectedUpstreamResponse(f"product-service answered {response.status_code}")
        body = response.json()
        return ProductInfo(
            sku=body["sku"],
            price=Decimal(body["price"]),  # a decimal string on the wire, never a float
            currency=body["currency"],
            active=body["active"],
        )


class HttpStockChecker:
    def __init__(self, client: ServiceHttpClient) -> None:
        self._client = client

    def check(self, lines: Sequence[OrderLine]) -> StockReport:
        try:
            # The one POST allowed to retry: the availability check is read-only (section 8).
            response = self._client.post(
                "/api/v1/inventory/availability",
                json={"items": [{"sku": line.sku, "quantity": line.quantity} for line in lines]},
                retry_safe=True,
            )
        except UpstreamUnavailableError as exc:
            raise UpstreamUnavailable("inventory-service") from exc
        if response.status_code != 200:
            raise UnexpectedUpstreamResponse(f"inventory-service answered {response.status_code}")
        body: dict[str, Any] = response.json()
        return StockReport(
            available=body["available"],
            lines=tuple(
                StockLine(
                    sku=item["sku"],
                    requested=item["requested"],
                    available=item["available"],
                    sufficient=item["sufficient"],
                    reason=item["reason"],
                )
                for item in body["items"]
            ),
        )


class HttpOwnerLookup:
    """Who owns a CloudPunk now. Inventory reads with ``ConsistentRead`` and never caches."""

    def __init__(self, client: ServiceHttpClient) -> None:
        self._client = client

    def owner_of(self, sku: str) -> str | None:
        try:
            response = self._client.get(f"/api/v1/inventory/{quote(sku, safe='')}")
        except UpstreamUnavailableError as exc:
            raise UpstreamUnavailable("inventory-service") from exc
        if response.status_code == 404:
            raise UnknownItem(sku)
        if response.status_code != 200:
            raise UnexpectedUpstreamResponse(f"inventory-service answered {response.status_code}")
        owner: str | None = response.json()["owner"]
        return owner
