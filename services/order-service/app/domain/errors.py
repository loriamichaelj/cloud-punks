"""Domain errors. The API layer maps these to HTTP responses."""

from app.domain.models import StockLine


class OrderNotFound(Exception):
    def __init__(self, order_id: str) -> None:
        super().__init__(f"order {order_id!r} not found")
        self.order_id = order_id


class IdempotencyKeyReused(Exception):
    def __init__(self) -> None:
        super().__init__("this Idempotency-Key was already used with a different request body")


class UnknownProduct(Exception):
    def __init__(self, skus: list[str]) -> None:
        super().__init__("unknown product(s): " + ", ".join(skus))
        self.skus = skus


class ProductInactive(Exception):
    def __init__(self, skus: list[str]) -> None:
        super().__init__("product(s) no longer available for sale: " + ", ".join(skus))
        self.skus = skus


class MixedCurrency(Exception):
    def __init__(self, currencies: list[str]) -> None:
        super().__init__("all items must share one currency, got: " + ", ".join(currencies))
        self.currencies = currencies


class OutOfStock(Exception):
    """The advisory pre-check says the order cannot be filled. No order row is written."""

    def __init__(self, lines: list[StockLine]) -> None:
        super().__init__(
            "; ".join(
                f"{line.sku}: requested {line.requested}, available {line.available}"
                for line in lines
            )
        )
        self.lines = lines


class UpstreamUnavailable(Exception):
    """A synchronous dependency (product or inventory service) cannot answer right now."""

    def __init__(self, dependency: str) -> None:
        super().__init__(f"{dependency} is unavailable")
        self.dependency = dependency


class UnexpectedUpstreamResponse(Exception):
    """A dependency answered in a way our contract says it cannot: a bug, so it surfaces as 500."""


class StoreUnavailable(Exception):
    """PostgreSQL cannot serve the request right now (down, timed out, pool exhausted)."""


# -- the CloudPunks market (DESIGN.md section 16.4) ------------------------------------------------


class NotOwner(Exception):
    """Only the owner may put a CloudPunk up for bid, take it off, or accept a bid on it."""

    def __init__(self, sku: str) -> None:
        super().__init__(f"{sku} is not yours to sell")
        self.sku = sku


class NotListed(Exception):
    """There is no open listing for this CloudPunk (it is not up for bid)."""

    def __init__(self, sku: str) -> None:
        super().__init__(f"{sku} is not up for bid")
        self.sku = sku


class SalePending(Exception):
    """An accepted bid's order is being confirmed; the listing cannot change until it settles."""

    def __init__(self, sku: str) -> None:
        super().__init__(f"{sku} has an accepted bid being confirmed")
        self.sku = sku


class OwnItem(Exception):
    """The owner cannot bid on their own CloudPunk."""

    def __init__(self, sku: str) -> None:
        super().__init__(f"{sku} is already yours")
        self.sku = sku


class BidNotFound(Exception):
    def __init__(self, bid_id: str) -> None:
        super().__init__(f"bid {bid_id!r} not found")
        self.bid_id = bid_id


class BidNotOpen(Exception):
    """The bid was withdrawn, closed, or already accepted."""

    def __init__(self, bid_id: str, status: str) -> None:
        super().__init__(f"bid {bid_id} is {status}, not OPEN")
        self.bid_id = bid_id
        self.status = status


class NotBidder(Exception):
    """Only the bidder may withdraw a bid."""

    def __init__(self, bid_id: str) -> None:
        super().__init__(f"bid {bid_id} is not yours")
        self.bid_id = bid_id


class UnknownItem(Exception):
    """Inventory has no such SKU, so it has no owner and cannot be listed."""

    def __init__(self, sku: str) -> None:
        super().__init__(f"{sku} is not a known item")
        self.sku = sku
