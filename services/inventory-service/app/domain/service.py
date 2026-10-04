"""Inventory use-cases. Stock is never cached: every read goes to DynamoDB.

The availability check is *advisory* (ADR-08). Between this answer and the asynchronous
reservation, other orders can take the stock, so the transactional reservation in the inventory
consumer remains the only authority.
"""

from collections.abc import Mapping, Sequence

from app.domain.errors import StockNotFound
from app.domain.models import (
    AvailabilityReport,
    LineAvailability,
    RequestedLine,
    StockItem,
)
from app.domain.ports import InventoryRepository


def evaluate_availability(
    lines: Sequence[RequestedLine], stock: Mapping[str, StockItem]
) -> AvailabilityReport:
    """Pure decision logic: which lines can be satisfied from the given stock levels."""
    results: list[LineAvailability] = []
    for line in lines:
        item = stock.get(line.sku)
        if item is None:
            results.append(LineAvailability(line.sku, line.quantity, 0, False, "UNKNOWN_SKU"))
        elif item.available < line.quantity:
            results.append(
                LineAvailability(
                    line.sku, line.quantity, item.available, False, "OUT_OF_STOCK", item.owner
                )
            )
        else:
            results.append(
                LineAvailability(line.sku, line.quantity, item.available, True, None, item.owner)
            )
    return AvailabilityReport(available=all(r.sufficient for r in results), lines=tuple(results))


class InventoryService:
    def __init__(self, repository: InventoryRepository) -> None:
        self._repository = repository

    def get_stock(self, sku: str) -> StockItem:
        item = self._repository.get(sku)
        if item is None:
            raise StockNotFound(sku)
        return item

    def check_availability(self, lines: Sequence[RequestedLine]) -> AvailabilityReport:
        stock = self._repository.get_many([line.sku for line in lines])
        return evaluate_availability(lines, stock)

    def set_stock(self, sku: str, available: int, *, reset_owner: bool = False) -> StockItem:
        return self._repository.set_available(sku, available, reset_owner=reset_owner)
