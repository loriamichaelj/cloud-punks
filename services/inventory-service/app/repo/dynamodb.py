"""DynamoDB adapter for ``InventoryRepository`` (table ``inventory``, PK ``sku``).

**Every read is strongly consistent** (``ConsistentRead=True``). An eventually consistent read
could return stock from before a reservation committed, and the order service would accept an
order the inventory can no longer fill. Stock is also never cached anywhere (CLAUDE.md).
"""

import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import boto3
import structlog
from botocore.config import Config
from botocore.exceptions import ClientError, HTTPClientError
from botocore.exceptions import ConnectionError as BotoConnectionError

from app.config import Settings
from app.domain.errors import StoreUnavailable
from app.domain.models import StockItem

INVENTORY_TABLE = "inventory"  # same name locally and in AWS (DESIGN.md section 5)
BATCH_GET_LIMIT = 100  # DynamoDB BatchGetItem limit
MAX_UNPROCESSED_ROUNDS = 3

# Errors that mean "DynamoDB cannot serve this right now", as opposed to a bug or bad config.
_TRANSIENT_CODES = frozenset(
    {
        "ProvisionedThroughputExceededException",
        "ThrottlingException",
        "RequestLimitExceeded",
        "InternalServerError",
        "ServiceUnavailable",
        "ResourceNotFoundException",  # table missing: infrastructure not ready (e.g. no bootstrap)
    }
)

_log = structlog.get_logger("inventory_repository")


def build_dynamodb_client(settings: Settings) -> Any:
    """The endpoint and credentials come from the environment (AWS_ENDPOINT_URL, default chain)."""
    return boto3.client(
        "dynamodb",
        region_name=settings.aws_region,
        config=Config(
            connect_timeout=settings.http_timeout_connect_s,
            read_timeout=settings.http_timeout_read_s,
            retries={"max_attempts": 2, "mode": "standard"},  # at most 2 retries
        ),
    )


def ping(client: Any, table: str = INVENTORY_TABLE) -> None:
    """Readiness probe: raises if the table cannot be described."""
    client.describe_table(TableName=table)


@contextmanager
def _store_errors() -> Iterator[None]:
    try:
        yield
    except (BotoConnectionError, HTTPClientError) as exc:
        _log.warning("store_unavailable", error=type(exc).__name__)
        raise StoreUnavailable from exc
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code not in _TRANSIENT_CODES:
            raise  # AccessDenied, ValidationException...: a bug or misconfiguration, not an outage
        _log.warning("store_unavailable", error=code)
        raise StoreUnavailable from exc


def _to_item(raw: Mapping[str, Any]) -> StockItem:
    return StockItem(
        sku=raw["sku"]["S"],
        available=int(raw["available"]["N"]),
        reserved=int(raw["reserved"]["N"]),
        updated_at=datetime.fromisoformat(raw["updated_at"]["S"]),
    )


class DynamoInventoryRepository:
    def __init__(self, client: Any, table: str = INVENTORY_TABLE) -> None:
        self._client = client
        self._table = table

    def get(self, sku: str) -> StockItem | None:
        with _store_errors():
            response = self._client.get_item(
                TableName=self._table, Key={"sku": {"S": sku}}, ConsistentRead=True
            )
        raw = response.get("Item")
        return _to_item(raw) if raw else None

    def get_many(self, skus: Sequence[str]) -> dict[str, StockItem]:
        unique = list(dict.fromkeys(skus))  # BatchGetItem rejects duplicate keys
        found: dict[str, StockItem] = {}
        for start in range(0, len(unique), BATCH_GET_LIMIT):
            request: dict[str, Any] = {
                self._table: {
                    "Keys": [
                        {"sku": {"S": sku}} for sku in unique[start : start + BATCH_GET_LIMIT]
                    ],
                    "ConsistentRead": True,
                }
            }
            for attempt in range(MAX_UNPROCESSED_ROUNDS):
                with _store_errors():
                    response = self._client.batch_get_item(RequestItems=request)
                for raw in response.get("Responses", {}).get(self._table, []):
                    item = _to_item(raw)
                    found[item.sku] = item
                request = response.get("UnprocessedKeys") or {}
                if not request:
                    break
                time.sleep(0.05 * 2**attempt)  # DynamoDB asks callers to back off and retry
            else:
                _log.warning("batch_get_unprocessed_keys", remaining=len(request))
                raise StoreUnavailable
        return found

    def set_available(self, sku: str, available: int) -> StockItem:
        now = datetime.now(UTC).isoformat(timespec="milliseconds")
        with _store_errors():
            response = self._client.update_item(
                TableName=self._table,
                Key={"sku": {"S": sku}},
                # An upsert. `reserved` is preserved if the record exists and starts at 0 if not,
                # so setting stock never erases the count of units already promised to orders.
                UpdateExpression=(
                    "SET available = :available, updated_at = :now, "
                    "reserved = if_not_exists(reserved, :zero)"
                ),
                ExpressionAttributeValues={
                    ":available": {"N": str(available)},
                    ":now": {"S": now},
                    ":zero": {"N": "0"},
                },
                ReturnValues="ALL_NEW",
            )
        return _to_item(response["Attributes"])
