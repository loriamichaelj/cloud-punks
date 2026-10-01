"""What the use-cases need from the outside world, as Protocols the adapters implement."""

from collections.abc import Sequence
from typing import Protocol

from app.domain.models import (
    Category,
    NewProduct,
    Product,
    ProductChanges,
    ProductPage,
)


class ProductRepository(Protocol):
    def list_categories(self) -> Sequence[Category]: ...

    def get_product(self, sku: str) -> Product | None: ...

    def list_products(self, category: str | None, page: int, size: int) -> ProductPage:
        """Active products only, ordered by SKU."""
        ...

    def create_product(self, new: NewProduct) -> Product:
        """Raises ``UnknownCategory`` or ``DuplicateSku``."""
        ...

    def update_product(self, sku: str, changes: ProductChanges) -> Product:
        """Raises ``ProductNotFound`` or ``UnknownCategory``."""
        ...


class ProductCache(Protocol):
    """Best-effort cache. Implementations must never raise: a cache failure is a miss."""

    def get_product(self, sku: str) -> Product | None: ...

    def set_product(self, product: Product) -> None: ...

    def get_page(self, category: str | None, page: int, size: int) -> ProductPage | None: ...

    def set_page(self, category: str | None, page: ProductPage) -> None: ...

    def get_categories(self) -> Sequence[Category] | None: ...

    def set_categories(self, categories: Sequence[Category]) -> None: ...

    def invalidate_product(self, sku: str) -> None: ...

    def invalidate_listings(self) -> None: ...
