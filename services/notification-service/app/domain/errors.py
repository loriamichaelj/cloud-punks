"""Domain errors. The API layer maps these to HTTP responses."""


class StoreUnavailable(Exception):
    """DynamoDB cannot serve the request right now (down, throttled, timed out)."""
