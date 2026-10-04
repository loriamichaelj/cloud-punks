"""PostgreSQL adapter for ``OrderRepository`` (SQLAlchemy Core, sync, psycopg 3)."""

from collections import defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import structlog
from sqlalchemy import Engine, Row, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from app.domain.errors import StoreUnavailable
from app.domain.models import (
    CreateOutcome,
    Order,
    OrderItem,
    OrderPage,
    OutboxEvent,
    StoredOrder,
)
from app.repo.tables import order_items, orders, outbox
from retail_common.database import STORE_ERRORS

_log = structlog.get_logger("order_repository")


@contextmanager
def store_errors() -> Iterator[None]:
    """Turn "PostgreSQL cannot serve this" into a domain error the API reports as a 503.

    Covers a refused or dropped connection, a statement cancelled by the role's 5 s
    ``statement_timeout`` and an exhausted pool. Constraint violations and bugs stay real errors.
    """
    try:
        yield
    except STORE_ERRORS as exc:
        _log.warning("store_unavailable", error=type(exc).__name__)
        raise StoreUnavailable from exc


def _items_by_order(connection: Connection, order_ids: Sequence[str]) -> dict[str, list[OrderItem]]:
    grouped: dict[str, list[OrderItem]] = defaultdict(list)
    rows = connection.execute(
        select(
            order_items.c.order_id,
            order_items.c.sku,
            order_items.c.quantity,
            order_items.c.unit_price,
            order_items.c.seller,
        )
        .where(order_items.c.order_id.in_(order_ids))
        .order_by(order_items.c.order_id, order_items.c.sku)
    )
    for row in rows:
        grouped[row.order_id].append(OrderItem(row.sku, row.quantity, row.unit_price, row.seller))
    return grouped


def insert_order(
    connection: Connection,
    order: Order,
    *,
    idempotency_key: str,
    request_hash: str,
    event: OutboxEvent,
) -> bool:
    """Write the order, its items and its outbox row on the caller's transaction (ADR-04).

    Returns False, writing nothing, if ``(customer_id, idempotency_key)`` already holds an order.
    Used by a purchase from the platform and by an accepted bid alike."""
    inserted = connection.execute(
        pg_insert(orders)
        .values(
            order_id=order.order_id,
            customer_id=order.customer_id,
            status=order.status,
            status_reason=order.status_reason,
            total_amount=order.total_amount,
            currency=order.currency,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        # Only the idempotency constraint is a "replay"; any other conflict is a real error.
        .on_conflict_do_nothing(index_elements=[orders.c.customer_id, orders.c.idempotency_key])
        .returning(orders.c.order_id)
    ).scalar_one_or_none()
    if inserted is None:
        return False
    connection.execute(
        insert(order_items),
        [
            {
                "order_id": order.order_id,
                "sku": item.sku,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "seller": item.seller,
            }
            for item in order.items
        ],
    )
    # The outbox row shares this transaction: the order and its event commit together or not at
    # all. This is what makes "202 Accepted" safe to say (ADR-04).
    connection.execute(
        insert(outbox).values(
            event_id=event.event_id, detail_type=event.detail_type, payload=event.payload
        )
    )
    return True


def _to_order(row: Row[Any], items: Sequence[OrderItem]) -> Order:
    return Order(
        order_id=row.order_id,
        customer_id=row.customer_id,
        status=row.status,
        status_reason=row.status_reason,
        total_amount=row.total_amount,
        currency=row.currency,
        items=tuple(items),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PostgresOrderRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def find_by_idempotency_key(self, customer_id: str, key: str) -> StoredOrder | None:
        with store_errors(), self._engine.connect() as connection:
            return self._find(connection, customer_id, key)

    def create_order(
        self, order: Order, *, idempotency_key: str, request_hash: str, event: OutboxEvent
    ) -> CreateOutcome:
        with store_errors(), self._engine.begin() as connection:
            if not insert_order(
                connection,
                order,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                event=event,
            ):
                # A concurrent request holding the same key committed first. Write nothing.
                existing = self._find(connection, order.customer_id, idempotency_key)
                if existing is None:  # pragma: no cover - a committed row cannot vanish
                    raise RuntimeError("idempotency conflict without a stored order")
                return CreateOutcome(stored=existing, created=False)
            stored = self._fetch(connection, order.order_id)
        if stored is None:  # pragma: no cover - the row was inserted in this very transaction
            raise RuntimeError("order vanished inside its own transaction")
        return CreateOutcome(stored=stored, created=True)

    def get_order(self, order_id: str) -> Order | None:
        with store_errors(), self._engine.connect() as connection:
            stored = self._fetch(connection, order_id)
        return stored.order if stored else None

    def list_orders(self, customer_id: str, page: int, size: int) -> OrderPage:
        with store_errors(), self._engine.connect() as connection:
            rows = connection.execute(
                select(orders)
                .where(orders.c.customer_id == customer_id)
                .order_by(orders.c.created_at.desc(), orders.c.order_id.desc())
                .limit(size)
                .offset((page - 1) * size)
            ).all()
            total = connection.execute(
                select(func.count()).select_from(orders).where(orders.c.customer_id == customer_id)
            ).scalar_one()
            items = _items_by_order(connection, [row.order_id for row in rows]) if rows else {}
        return OrderPage(
            items=tuple(_to_order(row, items.get(row.order_id, [])) for row in rows),
            page=page,
            size=size,
            total=int(total),
        )

    # -- helpers (callers hold the connection and the error translation) ---------------------

    def _find(self, connection: Connection, customer_id: str, key: str) -> StoredOrder | None:
        order_id = connection.execute(
            select(orders.c.order_id).where(
                orders.c.customer_id == customer_id, orders.c.idempotency_key == key
            )
        ).scalar_one_or_none()
        return self._fetch(connection, order_id) if order_id else None

    @staticmethod
    def _fetch(connection: Connection, order_id: str) -> StoredOrder | None:
        return fetch_order(connection, order_id)


def fetch_order(connection: Connection, order_id: str) -> StoredOrder | None:
    row = connection.execute(select(orders).where(orders.c.order_id == order_id)).one_or_none()
    if row is None:
        return None
    items = _items_by_order(connection, [order_id]).get(order_id, [])
    return StoredOrder(order=_to_order(row, items), request_hash=row.request_hash.strip())
