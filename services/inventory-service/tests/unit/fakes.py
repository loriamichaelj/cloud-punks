"""In-memory stand-in for the inventory repository, plus settings."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from app.config import Settings
from app.domain.errors import StoreUnavailable
from app.domain.models import StockItem

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


def make_item(
    sku: str = "SKU-1", available: int = 10, reserved: int = 0, owner: str | None = None
) -> StockItem:
    return StockItem(sku=sku, available=available, reserved=reserved, updated_at=NOW, owner=owner)


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

    def set_available(self, sku: str, available: int, *, reset_owner: bool = False) -> StockItem:
        self.calls.append(f"set:{sku}:{available}" + (":reset_owner" if reset_owner else ""))
        self._check()
        existing = self.items.get(sku)
        owner = None if reset_owner or existing is None else existing.owner
        item = StockItem(sku, available, existing.reserved if existing else 0, NOW, owner)
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

    def __init__(self, levels: dict[str, int], owners: dict[str, str] | None = None) -> None:
        self.levels = dict(levels)
        self.owners = dict(owners or {})

    def get_many(self, skus: Sequence[str]) -> Mapping[str, StockItem]:
        return {
            sku: make_item(sku, self.levels[sku], owner=self.owners.get(sku))
            for sku in skus
            if sku in self.levels
        }


class FakeReservationStore:
    """Behaves like the DynamoDB store: one record per order, all-or-nothing stock changes."""

    def __init__(self, stock: FakeStock) -> None:
        self.stock = stock
        self.records: dict[str, Reservation] = {}
        self.reserve_calls = 0
        self.crash_before_remaining = False

    def _fails(self, item: ReservedLine, seller: str | None) -> bool:
        if item.sku not in self.stock.levels:
            return True
        if seller is None:
            return self.stock.levels[item.sku] < item.quantity
        return self.stock.owners.get(item.sku) != seller

    def reserve(
        self,
        order_id: str,
        items: Sequence[ReservedLine],
        event_id: str,
        created_at: datetime,
        *,
        buyer: str,
        seller: str | None = None,
    ) -> ReserveResult:
        self.reserve_calls += 1
        existing = self.records.get(order_id)
        if existing is not None:
            return ReserveResult(existing, created=False)
        failing = [i for i in items if self._fails(i, seller)]
        if failing:
            failed = tuple(
                FailedLine(i.sku, i.quantity, self.stock.levels.get(i.sku, 0)) for i in failing
            )
            unknown = any(i.sku not in self.stock.levels for i in failing)
            owned = any(i.sku in self.stock.owners for i in failing)
            detail = None if unknown else "OWNER_CHANGED" if seller else "SOLD" if owned else None
            record = Reservation(
                order_id, "FAILED", tuple(items), event_id, created_at,
                reason="UNKNOWN_SKU" if unknown else "OUT_OF_STOCK", failed_items=failed,
                buyer=buyer, seller=seller, detail=detail,
            )  # fmt: skip
        else:
            for item in items:
                if seller is None:
                    self.stock.levels[item.sku] -= item.quantity
                self.stock.owners[item.sku] = buyer
            record = Reservation(
                order_id, "RESERVED", tuple(items), event_id, created_at, buyer=buyer, seller=seller
            )
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
