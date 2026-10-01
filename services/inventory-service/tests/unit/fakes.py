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


# --- reservations ----------------------------------------------------------------------------

from dataclasses import replace  # noqa: E402

from app.domain.reservations import (  # noqa: E402
    FailedLine,
    Reservation,
    ReservedLine,
    ReserveResult,
)


class FakeStock:
    """One stock table shared by the reservation store and the inventory reader."""

    def __init__(self, levels: dict[str, int]) -> None:
        self.levels = dict(levels)

    def get_many(self, skus: Sequence[str]) -> Mapping[str, StockItem]:
        return {sku: make_item(sku, self.levels[sku]) for sku in skus if sku in self.levels}


class FakeReservationStore:
    """Behaves like the DynamoDB store: one record per order, all-or-nothing stock changes."""

    def __init__(self, stock: FakeStock) -> None:
        self.stock = stock
        self.records: dict[str, Reservation] = {}
        self.reserve_calls = 0
        self.crash_before_remaining = False

    def reserve(
        self, order_id: str, items: Sequence[ReservedLine], event_id: str, created_at: datetime
    ) -> ReserveResult:
        self.reserve_calls += 1
        existing = self.records.get(order_id)
        if existing is not None:
            return ReserveResult(existing, created=False)
        failed = [
            FailedLine(i.sku, i.quantity, self.stock.levels.get(i.sku, 0))
            for i in items
            if self.stock.levels.get(i.sku, -1) < i.quantity
        ]
        if failed:
            unknown = any(
                i.sku not in self.stock.levels for i in items if i.sku in {f.sku for f in failed}
            )
            record = Reservation(
                order_id, "FAILED", tuple(items), event_id, created_at,
                reason="UNKNOWN_SKU" if unknown else "OUT_OF_STOCK", failed_items=tuple(failed),
            )  # fmt: skip
        else:
            for item in items:
                self.stock.levels[item.sku] -= item.quantity
            record = Reservation(order_id, "RESERVED", tuple(items), event_id, created_at)
        self.records[order_id] = record
        return ReserveResult(record, created=True)

    def get(self, order_id: str) -> Reservation | None:
        return self.records.get(order_id)

    def store_remaining(self, order_id: str, remaining: Mapping[str, int]) -> Reservation:
        if self.crash_before_remaining:
            raise RuntimeError("process died after the stock was reserved")
        record = self.records[order_id]
        if record.remaining is None:
            record = replace(record, remaining=dict(remaining))
            self.records[order_id] = record
        return record
