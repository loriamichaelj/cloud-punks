"""In-memory stand-ins for the order service's ports."""

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal

from app.config import Settings
from app.domain.errors import StoreUnavailable, UpstreamUnavailable
from app.domain.models import (
    CreateOutcome,
    Order,
    OrderLine,
    OrderPage,
    OutboxEvent,
    ProductInfo,
    StockLine,
    StockReport,
    StoredOrder,
)
from app.domain.service import OrderService
from app.events import order_created_event
from app.relay.core import OutboxBatch, OutboxRow

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


def make_settings() -> Settings:
    return Settings(
        db_host="postgres",
        db_name="order_db",
        db_user="order_app",
        db_password="not-a-real-password",  # type: ignore[arg-type]
        product_service_url="http://product-service:8001",
        inventory_service_url="http://inventory-service:8002",
    )


class FakeRepository:
    """Keeps orders by idempotency key and records every outbox event written with them."""

    def __init__(self) -> None:
        self.orders: dict[str, Order] = {}
        self.by_key: dict[tuple[str, str], StoredOrder] = {}
        self.outbox: list[OutboxEvent] = []
        self.create_calls = 0
        self.down = False
        # Called inside create_order just before it checks for a conflict: lets a test play the
        # concurrent request that wins the race for an idempotency key.
        self.before_create: Callable[[], None] | None = None

    def _check(self) -> None:
        if self.down:
            raise StoreUnavailable

    def find_by_idempotency_key(self, customer_id: str, key: str) -> StoredOrder | None:
        self._check()
        return self.by_key.get((customer_id, key))

    def create_order(
        self, order: Order, *, idempotency_key: str, request_hash: str, event: OutboxEvent
    ) -> CreateOutcome:
        self._check()
        self.create_calls += 1
        if self.before_create is not None:
            self.before_create()
        existing = self.by_key.get((order.customer_id, idempotency_key))
        if existing is not None:
            return CreateOutcome(stored=existing, created=False)
        stored = StoredOrder(order=order, request_hash=request_hash)
        self.by_key[(order.customer_id, idempotency_key)] = stored
        self.orders[order.order_id] = order
        self.outbox.append(event)  # the order and its event land together
        return CreateOutcome(stored=stored, created=True)

    def get_order(self, order_id: str) -> Order | None:
        self._check()
        return self.orders.get(order_id)

    def list_orders(self, customer_id: str, page: int, size: int) -> OrderPage:
        self._check()
        mine = sorted(
            (o for o in self.orders.values() if o.customer_id == customer_id),
            key=lambda o: (o.created_at, o.order_id),
            reverse=True,
        )
        start = (page - 1) * size
        return OrderPage(tuple(mine[start : start + size]), page, size, len(mine))


class FakeCatalog:
    def __init__(self, *products: ProductInfo, log: list[str] | None = None) -> None:
        self.products = {p.sku: p for p in products}
        self.down = False
        self.calls: list[list[str]] = []
        self.log = log if log is not None else []

    def get_products(self, skus: Sequence[str]) -> Mapping[str, ProductInfo]:
        self.log.append("catalog")
        self.calls.append(list(skus))
        if self.down:
            raise UpstreamUnavailable("product-service")
        return {sku: self.products[sku] for sku in skus if sku in self.products}


class FakeStock:
    """Stock levels by SKU; an SKU not listed is unknown to inventory."""

    def __init__(
        self, levels: Mapping[str, int] | None = None, *, log: list[str] | None = None
    ) -> None:
        self.levels = dict(levels or {})
        self.down = False
        self.calls = 0
        self.log = log if log is not None else []

    def check(self, lines: Sequence[OrderLine]) -> StockReport:
        self.log.append("stock")
        self.calls += 1
        if self.down:
            raise UpstreamUnavailable("inventory-service")
        results = []
        for line in lines:
            if line.sku not in self.levels:
                results.append(StockLine(line.sku, line.quantity, 0, False, "UNKNOWN_SKU"))
            elif self.levels[line.sku] < line.quantity:
                results.append(
                    StockLine(line.sku, line.quantity, self.levels[line.sku], False, "OUT_OF_STOCK")
                )
            else:
                results.append(
                    StockLine(line.sku, line.quantity, self.levels[line.sku], True, None)
                )
        return StockReport(all(r.sufficient for r in results), tuple(results))


def product(
    sku: str = "SKU-1", price: str = "19.99", *, currency: str = "USD", active: bool = True
) -> ProductInfo:
    return ProductInfo(sku=sku, price=Decimal(price), currency=currency, active=active)


class Ids:
    """Deterministic, valid ULIDs for order ids."""

    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> str:
        self.n += 1
        return f"01J9Z6Q4W8K3M2N1P0R7S5T{self.n:03d}"[:26]


def make_service(
    repository: FakeRepository | None = None,
    catalog: FakeCatalog | None = None,
    stock: FakeStock | None = None,
) -> tuple[OrderService, FakeRepository, FakeCatalog, FakeStock]:
    repository = repository or FakeRepository()
    catalog = catalog or FakeCatalog(product("SKU-1", "19.99"), product("SKU-2", "8.99"))
    stock = stock or FakeStock({"SKU-1": 10, "SKU-2": 10})
    service = OrderService(
        repository,
        catalog,
        stock,
        new_order_id=Ids(),
        make_event=order_created_event,
        now=lambda: NOW,
    )
    return service, repository, catalog, stock


# --- relay fakes ------------------------------------------------------------------------------


class FakeBatch:
    def __init__(self, rows: Sequence[OutboxRow]) -> None:
        self.rows = rows
        self.published: list[int] = []
        self.failed: dict[int, str] = {}

    def mark_published(self, ids: Sequence[int]) -> None:
        self.published.extend(ids)

    def mark_failed(self, failures: Mapping[int, str]) -> None:
        self.failed.update(failures)


class FakeOutboxStore:
    """Applies a batch's marks only if the ``claim`` context exits normally (commit vs rollback)."""

    def __init__(self, rows: Sequence[OutboxRow] = ()) -> None:
        self.rows = list(rows)
        self.published_ids: set[int] = set()
        self.errors: dict[int, str] = {}
        self.attempts: dict[int, int] = {}
        self.claim_limits: list[int] = []
        self.rollbacks = 0
        self.deleted_calls: list[tuple[datetime, int]] = []
        self.delete_results: list[int] = []

    @contextmanager
    def claim(self, limit: int) -> Iterator[OutboxBatch]:
        self.claim_limits.append(limit)
        unpublished = [r for r in self.rows if r.id not in self.published_ids][:limit]
        batch = FakeBatch(unpublished)
        try:
            yield batch
        except BaseException:
            self.rollbacks += 1
            raise
        self.published_ids.update(batch.published)
        for row_id, error in batch.failed.items():
            self.errors[row_id] = error
            self.attempts[row_id] = self.attempts.get(row_id, 0) + 1

    def delete_published_before(self, cutoff: datetime, limit: int) -> int:
        self.deleted_calls.append((cutoff, limit))
        return self.delete_results.pop(0) if self.delete_results else 0
