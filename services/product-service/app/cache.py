"""Valkey adapter for ``ProductCache`` (DESIGN.md section 5, "Cache design").

The cache is optional at runtime: every failure is logged, counted in ``cache_errors_total`` and
reported to the caller as a miss, so the service keeps answering from PostgreSQL and stays ready
with Valkey down. Methods therefore never raise.

Listings are tracked in a set (``products:v1:listkeys``) so a write can delete them without
``KEYS *`` or ``SCAN``, which block or walk the whole keyspace on a large instance.
"""

import json
from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Self

import structlog
from prometheus_client import CollectorRegistry, Counter
from redis import Redis
from redis.exceptions import RedisError

from app.domain.keys import (
    CATEGORIES_KEY,
    CATEGORIES_TTL_S,
    LIST_KEYS_SET,
    LIST_TTL_S,
    PRODUCT_TTL_S,
    list_key,
    product_key,
)
from app.domain.models import Category, Product, ProductPage

_log = structlog.get_logger("product_cache")

KEYSPACE_PRODUCT = "product"
KEYSPACE_LIST = "product_list"
KEYSPACE_CATEGORIES = "categories"

SOCKET_TIMEOUT_S = 0.25  # a dead cache must cost a request fractions of a second, not seconds
LIST_KEYS_SET_TTL_S = 3600  # refreshed on every add; always outlives the 300 s entries it tracks
DELETE_CHUNK = 500


class CacheMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.hits = Counter(
            "cache_hits_total", "Cache hits by keyspace.", ["keyspace"], registry=registry
        )
        self.misses = Counter(
            "cache_misses_total", "Cache misses by keyspace.", ["keyspace"], registry=registry
        )
        self.errors = Counter(
            "cache_errors_total",
            "Cache operations that failed (the request fell through to PostgreSQL).",
            ["keyspace"],
            registry=registry,
        )


def _product_to_dict(product: Product) -> dict[str, Any]:
    return {
        "sku": product.sku,
        "name": product.name,
        "description": product.description,
        "category": product.category,
        "price": str(product.price),  # money is a string on the wire, never a float
        "currency": product.currency,
        "active": product.active,
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
    }


def _product_from_dict(data: dict[str, Any]) -> Product:
    return Product(
        sku=data["sku"],
        name=data["name"],
        description=data["description"],
        category=data["category"],
        price=Decimal(data["price"]),
        currency=data["currency"],
        active=data["active"],
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
    )


def _page_to_dict(page: ProductPage) -> dict[str, Any]:
    return {
        "items": [_product_to_dict(item) for item in page.items],
        "page": page.page,
        "size": page.size,
        "total": page.total,
    }


def _page_from_dict(data: dict[str, Any]) -> ProductPage:
    return ProductPage(
        items=tuple(_product_from_dict(item) for item in data["items"]),
        page=data["page"],
        size=data["size"],
        total=data["total"],
    )


class ValkeyProductCache:
    def __init__(self, client: Redis, metrics: CacheMetrics) -> None:
        self._client = client
        self._metrics = metrics

    @classmethod
    def from_url(cls, url: str, metrics: CacheMetrics) -> Self:
        client = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=SOCKET_TIMEOUT_S,
            socket_timeout=SOCKET_TIMEOUT_S,
        )
        return cls(client, metrics)

    def ping(self) -> None:
        """Readiness probe (optional dependency): raises if Valkey does not answer."""
        self._client.ping()

    def close(self) -> None:
        self._client.close()

    # -- failure handling ---------------------------------------------------------------------

    def _failed(self, keyspace: str, operation: str, exc: Exception) -> None:
        self._metrics.errors.labels(keyspace).inc()
        _log.warning(
            "cache_error", keyspace=keyspace, operation=operation, error=type(exc).__name__
        )

    def _get[T](self, keyspace: str, key: str, decode: Callable[[Any], T]) -> T | None:
        try:
            raw = self._client.get(key)
        except RedisError as exc:
            self._failed(keyspace, "get", exc)
            return None
        if raw is None:
            self._metrics.misses.labels(keyspace).inc()
            return None
        try:
            value = decode(json.loads(raw))
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            # A corrupt entry (e.g. written by a different version) must not break reads: count
            # it, drop it best-effort, and serve from PostgreSQL.
            self._failed(keyspace, "decode", exc)
            self._drop(keyspace, key)
            return None
        self._metrics.hits.labels(keyspace).inc()
        return value

    def _drop(self, keyspace: str, key: str) -> None:
        try:
            self._client.delete(key)
        except RedisError as exc:
            self._failed(keyspace, "delete", exc)

    def _set(self, keyspace: str, key: str, payload: dict[str, Any] | list[Any], ttl: int) -> None:
        try:
            self._client.set(key, json.dumps(payload), ex=ttl)
        except RedisError as exc:
            self._failed(keyspace, "set", exc)

    # -- ProductCache -------------------------------------------------------------------------

    def get_product(self, sku: str) -> Product | None:
        return self._get(KEYSPACE_PRODUCT, product_key(sku), _product_from_dict)

    def set_product(self, product: Product) -> None:
        self._set(
            KEYSPACE_PRODUCT, product_key(product.sku), _product_to_dict(product), PRODUCT_TTL_S
        )

    def get_page(self, category: str | None, page: int, size: int) -> ProductPage | None:
        return self._get(KEYSPACE_LIST, list_key(category, page, size), _page_from_dict)

    def set_page(self, category: str | None, page: ProductPage) -> None:
        key = list_key(category, page.page, page.size)
        try:
            with self._client.pipeline(transaction=False) as pipe:
                # Track the key *before* writing it, so a crash in between leaves a tracked key
                # that does not exist (harmless) and never an untracked one (stale for its TTL).
                pipe.sadd(LIST_KEYS_SET, key)
                pipe.expire(LIST_KEYS_SET, LIST_KEYS_SET_TTL_S)
                pipe.set(key, json.dumps(_page_to_dict(page)), ex=LIST_TTL_S)
                pipe.execute()
        except RedisError as exc:
            self._failed(KEYSPACE_LIST, "set", exc)

    def get_categories(self) -> Sequence[Category] | None:
        return self._get(
            KEYSPACE_CATEGORIES,
            CATEGORIES_KEY,
            lambda data: [Category(slug=item["slug"], name=item["name"]) for item in data],
        )

    def set_categories(self, categories: Sequence[Category]) -> None:
        payload = [{"slug": c.slug, "name": c.name} for c in categories]
        self._set(KEYSPACE_CATEGORIES, CATEGORIES_KEY, payload, CATEGORIES_TTL_S)

    def invalidate_product(self, sku: str) -> None:
        try:
            self._client.delete(product_key(sku))
        except RedisError as exc:
            self._failed(KEYSPACE_PRODUCT, "delete", exc)

    def invalidate_listings(self) -> None:
        try:
            # Read the tracking set and delete it in one MULTI/EXEC, so a listing cached by a
            # concurrent request lands in a fresh set instead of being lost from the tracking.
            with self._client.pipeline(transaction=True) as pipe:
                pipe.smembers(LIST_KEYS_SET)
                pipe.delete(LIST_KEYS_SET)
                members, _ = pipe.execute()
            keys = sorted(members)
            for start in range(0, len(keys), DELETE_CHUNK):
                self._client.delete(*keys[start : start + DELETE_CHUNK])
        except RedisError as exc:
            self._failed(KEYSPACE_LIST, "invalidate", exc)
