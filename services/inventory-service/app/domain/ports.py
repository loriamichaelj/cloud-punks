"""What the use-cases need from the outside world."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from app.domain.models import StockItem


class InventoryRepository(Protocol):
    """Every read must be strongly consistent: stale stock means overselling."""

    def get(self, sku: str) -> StockItem | None: ...

    def get_many(self, skus: Sequence[str]) -> Mapping[str, StockItem]:
        """Only SKUs that exist appear in the result."""
        ...

    def set_available(self, sku: str, available: int) -> StockItem:
        """Set ``available`` (creating the record if needed); ``reserved`` is left untouched."""
        ...
