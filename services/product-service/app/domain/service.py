"""Product use-cases: cache-aside reads, and writes that invalidate after the commit.

Reads try the cache first and fall back to PostgreSQL, so a cache outage is invisible to callers.
Writes commit to PostgreSQL first and only then drop the cached copies; the remaining staleness
window (a reader that loaded the old row just before the write) is bounded by the TTL, which
DESIGN.md accepts (catalog tolerates 5 minutes).
"""

from collections.abc import Sequence

from app.domain.errors import ProductNotFound
from app.domain.keys import MAX_CACHED_PAGE
from app.domain.models import (
    Category,
    NewProduct,
    Product,
    ProductChanges,
    ProductPage,
)
from app.domain.ports import ProductCache, ProductRepository


class ProductService:
    def __init__(self, repository: ProductRepository, cache: ProductCache) -> None:
        self._repository = repository
        self._cache = cache

    def get_product(self, sku: str) -> Product:
        cached = self._cache.get_product(sku)
        if cached is not None:
            return cached
        product = self._repository.get_product(sku)
        if product is None:
            raise ProductNotFound(sku)  # not-found is never cached
        self._cache.set_product(product)
        return product

    def list_products(self, category: str | None, page: int, size: int) -> ProductPage:
        cacheable = page <= MAX_CACHED_PAGE
        if cacheable:
            cached = self._cache.get_page(category, page, size)
            if cached is not None:
                return cached
        result = self._repository.list_products(category, page, size)
        if cacheable:
            self._cache.set_page(category, result)
        return result

    def list_categories(self) -> Sequence[Category]:
        cached = self._cache.get_categories()
        if cached is not None:
            return cached
        categories = self._repository.list_categories()
        self._cache.set_categories(categories)
        return categories

    def create_product(self, new: NewProduct) -> Product:
        product = self._repository.create_product(new)
        self._cache.invalidate_listings()
        return product

    def update_product(self, sku: str, changes: ProductChanges) -> Product:
        product = self._repository.update_product(sku, changes)
        self._cache.invalidate_product(sku)
        self._cache.invalidate_listings()
        return product
