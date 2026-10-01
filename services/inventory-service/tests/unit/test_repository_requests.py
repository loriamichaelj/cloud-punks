"""The exact DynamoDB requests the adapter sends, pinned with botocore's Stubber.

A Stubber rejects any call whose parameters differ from what was expected. That makes
``ConsistentRead=True`` a tested property: LocalStack and moto are always strongly consistent and
would happily accept an eventually consistent read, hiding exactly the bug this guards against.
"""

from typing import Any

import boto3
import pytest
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)
from botocore.stub import Stubber

from app.domain.errors import StoreUnavailable
from app.repo import dynamodb
from app.repo.dynamodb import DynamoInventoryRepository, ping


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setattr(dynamodb.time, "sleep", lambda _s: None)


def item(sku: str, available: int = 10, reserved: int = 0) -> dict[str, Any]:
    return {
        "sku": {"S": sku},
        "available": {"N": str(available)},
        "reserved": {"N": str(reserved)},
        "updated_at": {"S": "2026-10-01T12:00:00.000+00:00"},
    }


@pytest.fixture
def stub() -> Any:
    client = boto3.client("dynamodb", region_name="us-east-1")
    with Stubber(client) as stubber:
        yield client, stubber
        stubber.assert_no_pending_responses()


def test_get_item_is_a_strongly_consistent_read(stub: Any) -> None:
    client, stubber = stub
    stubber.add_response(
        "get_item",
        {"Item": item("SKU-1", 7, 2)},
        expected_params={
            "TableName": "inventory",
            "Key": {"sku": {"S": "SKU-1"}},
            "ConsistentRead": True,  # remove this and the Stubber raises
        },
    )

    stock = DynamoInventoryRepository(client).get("SKU-1")

    assert stock is not None
    assert (stock.sku, stock.available, stock.reserved) == ("SKU-1", 7, 2)
    assert stock.updated_at.tzinfo is not None


def test_get_item_returns_none_when_there_is_no_record(stub: Any) -> None:
    client, stubber = stub
    stubber.add_response("get_item", {}, expected_params={
        "TableName": "inventory", "Key": {"sku": {"S": "NOPE"}}, "ConsistentRead": True,
    })  # fmt: skip
    assert DynamoInventoryRepository(client).get("NOPE") is None


def test_batch_get_is_strongly_consistent_and_deduplicates_keys(stub: Any) -> None:
    client, stubber = stub
    stubber.add_response(
        "batch_get_item",
        {"Responses": {"inventory": [item("A"), item("B", 3)]}},
        expected_params={
            "RequestItems": {
                "inventory": {
                    "Keys": [{"sku": {"S": "A"}}, {"sku": {"S": "B"}}],  # 'A' sent once
                    "ConsistentRead": True,
                }
            }
        },
    )

    found = DynamoInventoryRepository(client).get_many(["A", "B", "A"])

    assert set(found) == {"A", "B"}
    assert found["B"].available == 3


def test_unprocessed_keys_are_retried_and_stay_strongly_consistent(stub: Any) -> None:
    client, stubber = stub
    first = {
        "inventory": {
            "Keys": [{"sku": {"S": "A"}}, {"sku": {"S": "B"}}],
            "ConsistentRead": True,
        }
    }
    unprocessed = {"inventory": {"Keys": [{"sku": {"S": "B"}}], "ConsistentRead": True}}
    stubber.add_response(
        "batch_get_item",
        {"Responses": {"inventory": [item("A")]}, "UnprocessedKeys": unprocessed},
        expected_params={"RequestItems": first},
    )
    stubber.add_response(
        "batch_get_item",
        {"Responses": {"inventory": [item("B", 4)]}},
        expected_params={"RequestItems": unprocessed},  # the retry asks for B, consistently
    )

    found = DynamoInventoryRepository(client).get_many(["A", "B"])

    assert {sku: i.available for sku, i in found.items()} == {"A": 10, "B": 4}


def test_keys_that_stay_unprocessed_become_a_store_outage(stub: Any) -> None:
    client, stubber = stub
    pending = {"inventory": {"Keys": [{"sku": {"S": "A"}}], "ConsistentRead": True}}
    for _ in range(3):
        stubber.add_response(
            "batch_get_item",
            {"Responses": {"inventory": []}, "UnprocessedKeys": pending},
            expected_params={"RequestItems": pending},
        )

    with pytest.raises(StoreUnavailable):
        DynamoInventoryRepository(client).get_many(["A"])


def test_large_lists_are_split_at_the_batch_limit(stub: Any) -> None:
    client, stubber = stub
    skus = [f"S{i:03d}" for i in range(150)]
    for chunk in (skus[:100], skus[100:]):
        stubber.add_response(
            "batch_get_item",
            {"Responses": {"inventory": [item(s) for s in chunk]}},
            expected_params={
                "RequestItems": {
                    "inventory": {
                        "Keys": [{"sku": {"S": s}} for s in chunk],
                        "ConsistentRead": True,
                    }
                }
            },
        )
    assert len(DynamoInventoryRepository(client).get_many(skus)) == 150


def test_set_available_is_an_upsert_that_preserves_reserved(stub: Any) -> None:
    client, stubber = stub
    stubber.add_response(
        "update_item",
        {"Attributes": item("SKU-1", 40, 3)},
        expected_params={
            "TableName": "inventory",
            "Key": {"sku": {"S": "SKU-1"}},
            "UpdateExpression": (
                "SET available = :available, updated_at = :now, "
                "reserved = if_not_exists(reserved, :zero)"
            ),
            "ExpressionAttributeValues": {
                ":available": {"N": "40"},
                ":now": stub_any_string(),
                ":zero": {"N": "0"},
            },
            "ReturnValues": "ALL_NEW",
        },
    )

    stock = DynamoInventoryRepository(client).set_available("SKU-1", 40)

    assert (stock.available, stock.reserved) == (40, 3)


def stub_any_string() -> Any:
    from botocore.stub import ANY

    return {"S": ANY}


def test_ping_describes_the_inventory_table(stub: Any) -> None:
    client, stubber = stub
    stubber.add_response(
        "describe_table",
        {"Table": {"TableName": "inventory"}},
        expected_params={"TableName": "inventory"},
    )
    ping(client)


# --- failures: an outage is a StoreUnavailable, a bug is not ---------------------------------


class RaisingClient:
    """Raises the same exception from every call, like a client whose network is gone."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def get_item(self, **_kwargs: Any) -> Any:
        raise self.error

    batch_get_item = update_item = get_item


@pytest.mark.parametrize(
    "error",
    [
        EndpointConnectionError(endpoint_url="http://dynamodb.test"),
        ConnectTimeoutError(endpoint_url="http://dynamodb.test"),
        ReadTimeoutError(endpoint_url="http://dynamodb.test"),
        *[
            ClientError({"Error": {"Code": code, "Message": "x"}}, "GetItem")
            for code in (
                "ProvisionedThroughputExceededException",
                "ThrottlingException",
                "RequestLimitExceeded",
                "InternalServerError",
                "ServiceUnavailable",
                "ResourceNotFoundException",
            )
        ],
    ],
)
def test_connection_throttling_and_missing_table_errors_are_store_unavailable(
    error: Exception,
) -> None:
    repository = DynamoInventoryRepository(RaisingClient(error))
    with pytest.raises(StoreUnavailable):
        repository.get("A")
    with pytest.raises(StoreUnavailable):
        repository.get_many(["A"])
    with pytest.raises(StoreUnavailable):
        repository.set_available("A", 1)


@pytest.mark.parametrize(
    "code", ["AccessDeniedException", "ValidationException", "SerializationException"]
)
def test_a_bug_or_misconfiguration_is_not_disguised_as_a_retryable_outage(code: str) -> None:
    error = ClientError({"Error": {"Code": code, "Message": "x"}}, "GetItem")
    with pytest.raises(ClientError):
        DynamoInventoryRepository(RaisingClient(error)).get("A")
