"""PostgreSQL adapter for ``ProductRepository`` (SQLAlchemy Core, sync, psycopg 3)."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import structlog
from sqlalchemy import ColumnElement, Engine, Row, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.domain.errors import DuplicateSku, ProductNotFound, StoreUnavailable, UnknownCategory
from app.domain.models import (
    Category,
    NewProduct,
    Product,
    ProductChanges,
    ProductPage,
)
from app.repo.tables import categories, products

_log = structlog.get_logger("product_repository")


@contextmanager
def _store_errors() -> Iterator[None]:
    """Turn "PostgreSQL cannot serve this" into a domain error the API reports as a 503.

    Covers a refused or dropped connection, a statement cancelled by the role's 5 s
    ``statement_timeout`` (all ``OperationalError``) and an exhausted connection pool.
    Anything else (a bug, a constraint) still surfaces as a real error.
    """
    try:
        yield
    except (OperationalError, InterfaceError, PoolTimeoutError) as exc:
        _log.warning("store_unavailable", error=type(exc).__name__)
        raise StoreUnavailable from exc


_PRODUCT_COLUMNS = (
    products.c.sku,
    products.c.name,
    products.c.description,
    categories.c.slug.label("category"),
    products.c.price,
    products.c.currency,
    products.c.active,
    products.c.created_at,
    products.c.updated_at,
)


def _to_product(row: Row[Any]) -> Product:
    return Product(
        sku=row.sku,
        name=row.name,
        description=row.description,
        category=row.category,
        price=row.price,
        currency=row.currency,
        active=row.active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _select_products() -> Any:
    return select(*_PRODUCT_COLUMNS).select_from(
        products.join(categories, products.c.category_id == categories.c.id)
    )


def _category_id(connection: Connection, slug: str) -> int:
    category_id = connection.execute(
        select(categories.c.id).where(categories.c.slug == slug)
    ).scalar_one_or_none()
    if category_id is None:
        raise UnknownCategory(slug)
    return int(category_id)


class PostgresProductRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list_categories(self) -> Sequence[Category]:
        with _store_errors(), self._engine.connect() as connection:
            rows = connection.execute(select(categories.c.slug, categories.c.name).order_by("slug"))
            return [Category(slug=row.slug, name=row.name) for row in rows]

    def get_product(self, sku: str) -> Product | None:
        with _store_errors():
            with self._engine.connect() as connection:
                row = connection.execute(
                    _select_products().where(products.c.sku == sku)
                ).one_or_none()
            return _to_product(row) if row is not None else None

    def list_products(self, category: str | None, page: int, size: int) -> ProductPage:
        with _store_errors():
            condition: ColumnElement[bool] = products.c.active.is_(True)
            if category is not None:
                condition = condition & (categories.c.slug == category)
            with self._engine.connect() as connection:
                rows = connection.execute(
                    _select_products()
                    .where(condition)
                    .order_by(products.c.sku)
                    .limit(size)
                    .offset((page - 1) * size)
                ).all()
                total = connection.execute(
                    select(func.count())
                    .select_from(
                        products.join(categories, products.c.category_id == categories.c.id)
                    )
                    .where(condition)
                ).scalar_one()
            return ProductPage(
                items=tuple(_to_product(row) for row in rows),
                page=page,
                size=size,
                total=int(total),
            )

    def create_product(self, new: NewProduct) -> Product:
        with _store_errors():
            with self._engine.begin() as connection:
                category_id = _category_id(connection, new.category)
                inserted = connection.execute(
                    pg_insert(products)
                    .values(
                        sku=new.sku,
                        name=new.name,
                        description=new.description,
                        category_id=category_id,
                        price=new.price,
                        currency=new.currency,
                    )
                    .on_conflict_do_nothing(index_elements=[products.c.sku])
                    .returning(products.c.sku)
                ).scalar_one_or_none()
                if inserted is None:
                    raise DuplicateSku(new.sku)
                row = connection.execute(_select_products().where(products.c.sku == new.sku)).one()
            return _to_product(row)

    def update_product(self, sku: str, changes: ProductChanges) -> Product:
        with _store_errors():
            with self._engine.begin() as connection:
                category_id = _category_id(connection, changes.category)
                updated = connection.execute(
                    update(products)
                    .where(products.c.sku == sku)
                    .values(
                        name=changes.name,
                        description=changes.description,
                        category_id=category_id,
                        price=changes.price,
                        currency=changes.currency,
                        active=changes.active,
                    )
                    .returning(products.c.sku)
                ).scalar_one_or_none()
                if updated is None:
                    raise ProductNotFound(sku)
                row = connection.execute(_select_products().where(products.c.sku == sku)).one()
            return _to_product(row)
