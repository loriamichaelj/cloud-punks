"""In-memory stand-in for the inventory repository, plus settings."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from app.config import Settings
from app.domain.errors import StoreUnavailable
from app.domain.models import StockItem

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


def make_item(sku: str = "SKU-1", available: int = 10, reserved: int = 0) -> StockItem:
    return StockItem(sku=sku, available=available, reserved=reserved, updated_at=NOW)


def make_settings() -> Settings:
    return Settings(aws_region="us-east-1")


class FakeRepository:
    def __init__(self, *items: StockItem) -> None:
        self.items = {item.sku: item for item in items}
        self.down = False
        self.calls: list[str] = []

    def _check(self) -> None:
        if self.down:
            raise StoreUnavailable

    def get(self, sku: str) -> StockItem | None:
        self.calls.append(f"get:{sku}")
        self._check()
        return self.items.get(sku)

    def get_many(self, skus: Sequence[str]) -> Mapping[str, StockItem]:
        self.calls.append(f"get_many:{','.join(skus)}")
        self._check()
        return {sku: self.items[sku] for sku in skus if sku in self.items}

    def set_available(self, sku: str, available: int) -> StockItem:
        self.calls.append(f"set:{sku}:{available}")
        self._check()
        existing = self.items.get(sku)
        item = StockItem(sku, available, existing.reserved if existing else 0, NOW)
        self.items[sku] = item
        return item
