"""The exact DynamoDB requests the store sends, pinned with botocore's Stubber."""

from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber

from app.domain.errors import StoreUnavailable
from app.domain.notifications import Notification
from app.repo.dynamodb import DynamoNotificationStore

WHEN = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
NOTE = Notification(
    "01J9Z6R0C4AAAAAAAAAAAAAAAA",
    "01J9Z6R0C4BBBBBBBBBBBBBBBB",
    "InventoryReserved",
    "email",
    "hi",
    WHEN,
)


@pytest.fixture
def dynamodb() -> Any:
    return boto3.client("dynamodb", region_name="us-east-1")


def test_add_is_a_conditional_put_on_the_event_id(dynamodb: Any) -> None:
    with Stubber(dynamodb) as stub:
        stub.add_response(
            "put_item",
            {},
            expected_params={
                "TableName": "notifications",
                "Item": {
                    "order_id": {"S": NOTE.order_id},
                    "event_id": {"S": NOTE.event_id},
                    "type": {"S": "InventoryReserved"},
                    "channel": {"S": "email"},
                    "message": {"S": "hi"},
                    "created_at": {"S": "2026-10-01T12:00:00.000Z"},
                    "ttl": {"N": str(int(NOTE.expires_at.timestamp()))},
                },
                "ConditionExpression": "attribute_not_exists(event_id)",
            },
        )
        assert DynamoNotificationStore(dynamodb).add(NOTE) is True


def test_a_failed_condition_means_duplicate(dynamodb: Any) -> None:
    with Stubber(dynamodb) as stub:
        stub.add_client_error("put_item", "ConditionalCheckFailedException")
        assert DynamoNotificationStore(dynamodb).add(NOTE) is False


def test_throttling_is_a_store_outage_but_access_denied_is_a_bug(dynamodb: Any) -> None:
    with Stubber(dynamodb) as stub:
        stub.add_client_error("put_item", "ThrottlingException")
        with pytest.raises(StoreUnavailable):
            DynamoNotificationStore(dynamodb).add(NOTE)
        stub.add_client_error("put_item", "AccessDeniedException")
        with pytest.raises(Exception, match="AccessDenied"):
            DynamoNotificationStore(dynamodb).add(NOTE)


def test_the_query_is_consistent_and_follows_pagination(dynamodb: Any) -> None:
    def item(event_id: str) -> dict[str, Any]:
        return {
            "order_id": {"S": NOTE.order_id},
            "event_id": {"S": event_id},
            "type": {"S": "X"},
            "channel": {"S": "email"},
            "message": {"S": "m"},
            "created_at": {"S": "2026-10-01T12:00:00.000Z"},
        }

    base = {
        "TableName": "notifications",
        "KeyConditionExpression": "order_id = :o",
        "ExpressionAttributeValues": {":o": {"S": NOTE.order_id}},
        "ConsistentRead": True,
    }
    last = {"order_id": {"S": NOTE.order_id}, "event_id": {"S": "E1"}}
    with Stubber(dynamodb) as stub:
        stub.add_response("query", {"Items": [item("E1")], "LastEvaluatedKey": last}, base)
        stub.add_response("query", {"Items": [item("E2")]}, {**base, "ExclusiveStartKey": last})
        found = DynamoNotificationStore(dynamodb).for_order(NOTE.order_id)
    assert [n.event_id for n in found] == ["E1", "E2"]
