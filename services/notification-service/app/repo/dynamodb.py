"""DynamoDB adapter for ``NotificationStore`` (table ``notifications``, PK ``order_id``, SK
``event_id``). The conditional put on the sort key is the dedupe (DESIGN.md section 5)."""

from collections.abc import Iterator, Sequence
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
from app.domain.notifications import Notification

NOTIFICATIONS_TABLE = "notifications"

# Errors that mean "DynamoDB cannot serve this right now", as opposed to a bug or bad config.
_TRANSIENT_CODES = frozenset(
    {
        "ProvisionedThroughputExceededException",
        "ThrottlingException",
        "RequestLimitExceeded",
        "InternalServerError",
        "ServiceUnavailable",
        "ResourceNotFoundException",  # table missing: infrastructure not ready
    }
)

_log = structlog.get_logger("notification_repository")


def build_dynamodb_client(settings: Settings) -> Any:
    """The endpoint and credentials come from the environment (AWS_ENDPOINT_URL, default chain)."""
    return boto3.client(
        "dynamodb",
        region_name=settings.aws_region,
        config=Config(
            connect_timeout=settings.http_timeout_connect_s,
            read_timeout=settings.http_timeout_read_s,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


def ping(client: Any, table: str = NOTIFICATIONS_TABLE) -> None:
    """Readiness probe: raises if the table cannot be described."""
    client.describe_table(TableName=table)


@contextmanager
def store_errors() -> Iterator[None]:
    try:
        yield
    except (BotoConnectionError, HTTPClientError) as exc:
        _log.warning("store_unavailable", error=type(exc).__name__)
        raise StoreUnavailable from exc
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code not in _TRANSIENT_CODES:
            raise
        _log.warning("store_unavailable", error=code)
        raise StoreUnavailable from exc


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _to_notification(raw: dict[str, Any]) -> Notification:
    return Notification(
        order_id=raw["order_id"]["S"],
        event_id=raw["event_id"]["S"],
        type=raw["type"]["S"],
        channel=raw["channel"]["S"],
        message=raw["message"]["S"],
        created_at=datetime.fromisoformat(raw["created_at"]["S"]),
    )


class DynamoNotificationStore:
    def __init__(self, client: Any, table: str = NOTIFICATIONS_TABLE) -> None:
        self._client = client
        self._table = table

    def add(self, notification: Notification) -> bool:
        with store_errors():
            try:
                self._client.put_item(
                    TableName=self._table,
                    Item={
                        "order_id": {"S": notification.order_id},
                        "event_id": {"S": notification.event_id},
                        "type": {"S": notification.type},
                        "channel": {"S": notification.channel},
                        "message": {"S": notification.message},
                        "created_at": {"S": _timestamp(notification.created_at)},
                        "ttl": {"N": str(int(notification.expires_at.timestamp()))},
                    },
                    ConditionExpression="attribute_not_exists(event_id)",
                )
            except self._client.exceptions.ConditionalCheckFailedException:
                return False
        return True

    def for_order(self, order_id: str) -> Sequence[Notification]:
        found: list[Notification] = []
        start: dict[str, Any] = {}
        with store_errors():
            while True:
                page = self._client.query(
                    TableName=self._table,
                    KeyConditionExpression="order_id = :o",
                    ExpressionAttributeValues={":o": {"S": order_id}},
                    ConsistentRead=True,
                    **start,
                )
                found.extend(_to_notification(item) for item in page["Items"])
                if "LastEvaluatedKey" not in page:
                    return found
                start = {"ExclusiveStartKey": page["LastEvaluatedKey"]}
