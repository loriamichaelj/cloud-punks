"""Plain domain objects. Money is ``Decimal``, never ``float``."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Category:
    slug: str
    name: str


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    description: str | None
    category: str  # category slug
    price: Decimal
    currency: str
    active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class NewProduct:
    sku: str
    name: str
    description: str | None
    category: str
    price: Decimal
    currency: str


@dataclass(frozen=True)
class ProductChanges:
    """Everything a PUT may change; ``sku`` is immutable."""

    name: str
    description: str | None
    category: str
    price: Decimal
    currency: str
    active: bool


@dataclass(frozen=True)
class ProductPage:
    items: tuple[Product, ...]
    page: int
    size: int
    total: int
