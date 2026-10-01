"""In-memory stand-ins for the repository and cache ports."""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from app.config import Settings
from app.domain.errors import DuplicateSku, ProductNotFound, UnknownCategory
from app.domain.models import (
    Category,
    NewProduct,
    Product,
    ProductChanges,
    ProductPage,
)

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


def make_product(sku: str = "SKU-1", **overrides: object) -> Product:
    fields: dict[str, object] = {
        "sku": sku,
        "name": "Black T-Shirt",
        "description": "Soft cotton tee.",
        "category": "apparel",
        "price": Decimal("19.99"),
        "currency": "USD",
        "active": True,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return Product(**{**fields, **overrides})  # type: ignore[arg-type]


def make_settings() -> Settings:
    return Settings(
        db_host="postgres",
        db_name="product_db",
        db_user="product_app",
        db_password="not-a-real-password",  # type: ignore[arg-type]
        cache_url="redis://valkey:6379/0",
    )


class FakeRepository:
    def __init__(self, *, log: list[str] | None = None) -> None:
        self.log = log if log is not None else []
        self.products: dict[str, Product] = {}
        self.categories = [Category("apparel", "Apparel"), Category("home", "Home")]
        self.calls: list[str] = []

    def _known(self, slug: str) -> bool:
        return any(c.slug == slug for c in self.categories)

    def list_categories(self) -> Sequence[Category]:
        self.calls.append("list_categories")
        return list(self.categories)

    def get_product(self, sku: str) -> Product | None:
        self.calls.append(f"get_product:{sku}")
        return self.products.get(sku)

    def list_products(self, category: str | None, page: int, size: int) -> ProductPage:
        self.calls.append(f"list_products:{category}:{page}:{size}")
        matching = sorted(
            (p for p in self.products.values() if p.active and category in (None, p.category)),
            key=lambda p: p.sku,
        )
        start = (page - 1) * size
        return ProductPage(
            items=tuple(matching[start : start + size]), page=page, size=size, total=len(matching)
        )

    def create_product(self, new: NewProduct) -> Product:
        self.log.append("repo.create")
        if not self._known(new.category):
            raise UnknownCategory(new.category)
        if new.sku in self.products:
            raise DuplicateSku(new.sku)
        product = make_product(
            new.sku,
            name=new.name,
            description=new.description,
            category=new.category,
            price=new.price,
            currency=new.currency,
        )
        self.products[new.sku] = product
        return product

    def update_product(self, sku: str, changes: ProductChanges) -> Product:
        self.log.append("repo.update")
        if not self._known(changes.category):
            raise UnknownCategory(changes.category)
        if sku not in self.products:
            raise ProductNotFound(sku)
        product = make_product(
            sku,
            name=changes.name,
            description=changes.description,
            category=changes.category,
            price=changes.price,
            currency=changes.currency,
            active=changes.active,
        )
        self.products[sku] = product
        return product


class FakeCache:
    """A dict-backed cache. ``down=True`` behaves like an unreachable Valkey: every read is a
    miss and every write is silently dropped, exactly as the real adapter degrades."""

    def __init__(self, *, log: list[str] | None = None) -> None:
        self.log = log if log is not None else []
        self.down = False
        self.products: dict[str, Product] = {}
        self.pages: dict[tuple[str | None, int, int], ProductPage] = {}
        self.categories: Sequence[Category] | None = None

    def get_product(self, sku: str) -> Product | None:
        return None if self.down else self.products.get(sku)

    def set_product(self, product: Product) -> None:
        self.log.append(f"cache.set_product:{product.sku}")
        if not self.down:
            self.products[product.sku] = product

    def get_page(self, category: str | None, page: int, size: int) -> ProductPage | None:
        self.log.append(f"cache.get_page:{page}")
        return None if self.down else self.pages.get((category, page, size))

    def set_page(self, category: str | None, page: ProductPage) -> None:
        self.log.append(f"cache.set_page:{page.page}")
        if not self.down:
            self.pages[(category, page.page, page.size)] = page

    def get_categories(self) -> Sequence[Category] | None:
        return None if self.down else self.categories

    def set_categories(self, categories: Sequence[Category]) -> None:
        if not self.down:
            self.categories = list(categories)

    def invalidate_product(self, sku: str) -> None:
        self.log.append(f"cache.invalidate_product:{sku}")
        self.products.pop(sku, None)

    def invalidate_listings(self) -> None:
        self.log.append("cache.invalidate_listings")
        self.pages.clear()
