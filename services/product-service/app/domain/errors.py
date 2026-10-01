"""Domain errors. The API layer maps these to HTTP responses; the domain knows nothing of HTTP."""


class ProductNotFound(Exception):
    def __init__(self, sku: str) -> None:
        super().__init__(f"product {sku!r} not found")
        self.sku = sku


class DuplicateSku(Exception):
    def __init__(self, sku: str) -> None:
        super().__init__(f"product {sku!r} already exists")
        self.sku = sku


class UnknownCategory(Exception):
    def __init__(self, slug: str) -> None:
        super().__init__(f"category {slug!r} does not exist")
        self.slug = slug


class StoreUnavailable(Exception):
    """The backing store cannot serve the request right now (down, timed out, pool exhausted)."""
