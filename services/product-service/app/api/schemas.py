"""Request/response models. Money is a decimal *string* on the wire, never a JSON number."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.domain.models import Category, NewProduct, Product, ProductChanges, ProductPage

Sku = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Price = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
CENT = Decimal("0.01")


def _require_decimal_string(value: Any) -> Any:
    """Reject JSON numbers so ``19.99`` can never arrive as a float (DESIGN.md: never floats)."""
    if isinstance(value, str | Decimal):
        return value
    raise ValueError('price must be a decimal string such as "19.99"')


class ProductWrite(BaseModel):
    """Fields shared by create and update. Unknown fields are rejected, so typos surface."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    category: Slug
    price: Price
    currency: Currency = "USD"

    _price_is_string = field_validator("price", mode="before")(_require_decimal_string)

    @field_validator("price")
    @classmethod
    def _two_decimal_places(cls, value: Decimal) -> Decimal:
        return value.quantize(CENT)  # "5.5" is stored and returned as "5.50"


class ProductCreate(ProductWrite):
    sku: Sku

    def to_domain(self) -> NewProduct:
        return NewProduct(
            sku=self.sku,
            name=self.name,
            description=self.description,
            category=self.category,
            price=self.price,
            currency=self.currency,
        )


class ProductUpdate(ProductWrite):
    """PUT replaces every mutable field; ``sku`` is immutable and may not appear in the body."""

    active: bool = True

    def to_domain(self) -> ProductChanges:
        return ProductChanges(
            name=self.name,
            description=self.description,
            category=self.category,
            price=self.price,
            currency=self.currency,
            active=self.active,
        )


class ProductOut(BaseModel):
    sku: str
    name: str
    description: str | None
    category: str
    price: Decimal  # serialized as a string with exactly two decimals, e.g. "19.99"
    currency: str
    active: bool
    created_at: datetime
    updated_at: datetime

    @field_serializer("price")
    def _serialize_price(self, value: Decimal) -> str:
        # The wire format must not depend on which adapter (PostgreSQL, cache) produced the value.
        return format(value.quantize(CENT), "f")

    @classmethod
    def from_domain(cls, product: Product) -> "ProductOut":
        return cls(**product.__dict__)


class ProductPageOut(BaseModel):
    items: list[ProductOut]
    page: int
    size: int
    total: int

    @classmethod
    def from_domain(cls, page: ProductPage) -> "ProductPageOut":
        return cls(
            items=[ProductOut.from_domain(item) for item in page.items],
            page=page.page,
            size=page.size,
            total=page.total,
        )


class CategoryOut(BaseModel):
    slug: str
    name: str

    @classmethod
    def from_domain(cls, category: Category) -> "CategoryOut":
        return cls(slug=category.slug, name=category.name)


class CategoryListOut(BaseModel):
    items: list[CategoryOut]
