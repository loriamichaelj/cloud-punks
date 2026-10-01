"""Order use-cases: the synchronous path of the saga (DESIGN.md sections 4 and 7).

``create_order`` never calls the event bus. It writes the order and an outbox row in one
transaction (ADR-04) and a separate relay process publishes later. Everything that can fail
without leaving a trace (price lookup, stock pre-check) happens *before* that write.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from app.domain.errors import (
    IdempotencyKeyReused,
    MixedCurrency,
    OrderNotFound,
    OutOfStock,
    ProductInactive,
    UnknownProduct,
)
from app.domain.hashing import request_hash
from app.domain.models import (
    CreateResult,
    Order,
    OrderItem,
    OrderLine,
    OrderPage,
    OutboxEvent,
    ProductInfo,
    StoredOrder,
)
from app.domain.ports import OrderRepository, PriceCatalog, StockChecker

CENT = Decimal("0.01")


class OrderService:
    def __init__(
        self,
        repository: OrderRepository,
        catalog: PriceCatalog,
        stock: StockChecker,
        *,
        new_order_id: Callable[[], str],
        make_event: Callable[[Order], OutboxEvent],
        now: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._catalog = catalog
        self._stock = stock
        self._new_order_id = new_order_id
        self._make_event = make_event
        self._now = now

    def create_order(
        self, customer_id: str, idempotency_key: str, lines: Sequence[OrderLine]
    ) -> CreateResult:
        fingerprint = request_hash(customer_id, lines)

        # A replay must return the original order even if prices or stock have changed since,
        # so it is answered before any downstream call is made.
        existing = self._repository.find_by_idempotency_key(customer_id, idempotency_key)
        if existing is not None:
            return self._replay(existing, fingerprint)

        products = self._catalog.get_products([line.sku for line in lines])
        currency = self._validate_products(lines, products)

        report = self._stock.check(lines)
        if not report.available:
            raise OutOfStock([line for line in report.lines if not line.sufficient])

        order = self._build_order(customer_id, lines, products, currency)
        outcome = self._repository.create_order(
            order,
            idempotency_key=idempotency_key,
            request_hash=fingerprint,
            event=self._make_event(order),
        )
        if outcome.created:
            return CreateResult(order=outcome.stored.order, created=True)
        # Lost a race with a concurrent request carrying the same key: behave as a replay.
        return self._replay(outcome.stored, fingerprint)

    def get_order(self, order_id: str) -> Order:
        order = self._repository.get_order(order_id)
        if order is None:
            raise OrderNotFound(order_id)
        return order

    def list_orders(self, customer_id: str, page: int, size: int) -> OrderPage:
        return self._repository.list_orders(customer_id, page, size)

    # -- helpers ----------------------------------------------------------------------------

    @staticmethod
    def _replay(stored: StoredOrder, fingerprint: str) -> CreateResult:
        if stored.request_hash != fingerprint:
            raise IdempotencyKeyReused
        return CreateResult(order=stored.order, created=False)

    @staticmethod
    def _validate_products(lines: Sequence[OrderLine], products: Mapping[str, ProductInfo]) -> str:
        """Every SKU must exist, be on sale, and share one currency. Returns that currency."""
        unknown = [line.sku for line in lines if line.sku not in products]
        if unknown:
            raise UnknownProduct(unknown)
        inactive = [line.sku for line in lines if not products[line.sku].active]
        if inactive:
            raise ProductInactive(inactive)
        currencies = sorted({products[line.sku].currency for line in lines})
        if len(currencies) != 1:
            raise MixedCurrency(currencies)
        return currencies[0]

    def _build_order(
        self,
        customer_id: str,
        lines: Sequence[OrderLine],
        products: Mapping[str, ProductInfo],
        currency: str,
    ) -> Order:
        # unit_price is a snapshot: later price changes never alter an existing order.
        items = tuple(
            OrderItem(line.sku, line.quantity, products[line.sku].price) for line in lines
        )
        total = sum((item.unit_price * item.quantity for item in items), Decimal(0)).quantize(CENT)
        now = self._now()
        return Order(
            order_id=self._new_order_id(),
            customer_id=customer_id,
            status="PENDING",
            status_reason=None,
            total_amount=total,
            currency=currency,
            items=items,
            created_at=now,
            updated_at=now,
        )
