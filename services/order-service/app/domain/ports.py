"""What the use-cases need from the outside world."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from app.domain.models import (
    CreateOutcome,
    Order,
    OrderLine,
    OrderPage,
    OutboxEvent,
    ProductInfo,
    StockReport,
    StoredOrder,
)


class OrderRepository(Protocol):
    def find_by_idempotency_key(self, customer_id: str, key: str) -> StoredOrder | None: ...

    def create_order(
        self, order: Order, *, idempotency_key: str, request_hash: str, event: OutboxEvent
    ) -> CreateOutcome:
        """Write the order, its items and the outbox row in ONE transaction (ADR-04).

        If ``(customer_id, idempotency_key)`` already holds an order, write nothing and return it
        with ``created=False``. Raises ``StoreUnavailable`` if PostgreSQL cannot be used.
        """
        ...

    def get_order(self, order_id: str) -> Order | None: ...

    def list_orders(self, customer_id: str, page: int, size: int) -> OrderPage:
        """Newest first."""
        ...


class PriceCatalog(Protocol):
    def get_products(self, skus: Sequence[str]) -> Mapping[str, ProductInfo]:
        """Only SKUs that exist appear in the result. Raises ``UpstreamUnavailable``."""
        ...


class StockChecker(Protocol):
    def check(self, lines: Sequence[OrderLine]) -> StockReport:
        """Advisory availability pre-check. Raises ``UpstreamUnavailable``."""
        ...
