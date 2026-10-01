"""Domain errors. The API layer maps these to HTTP responses."""


class StockNotFound(Exception):
    def __init__(self, sku: str) -> None:
        super().__init__(f"no inventory record for {sku!r}")
        self.sku = sku


class StoreUnavailable(Exception):
    """DynamoDB cannot serve the request right now (down, throttled, timed out)."""
