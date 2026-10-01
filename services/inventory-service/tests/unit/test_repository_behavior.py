"""Adapter behavior against a DynamoDB emulator (moto): upserts, `reserved`, duplicates."""

from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

from app.repo.dynamodb import DynamoInventoryRepository


@pytest.fixture
def client() -> Iterator[Any]:
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="inventory",
            AttributeDefinitions=[{"AttributeName": "sku", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "sku", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield client


def put(client: Any, sku: str, available: int, reserved: int = 0) -> None:
    client.put_item(
        TableName="inventory",
        Item={
            "sku": {"S": sku},
            "available": {"N": str(available)},
            "reserved": {"N": str(reserved)},
            "updated_at": {"S": "2026-10-01T12:00:00+00:00"},  # the seed script's format
        },
    )


def test_a_record_written_by_the_seed_script_is_readable(client: Any) -> None:
    put(client, "SKU-1", 25)
    stock = DynamoInventoryRepository(client).get("SKU-1")
    assert stock is not None
    assert (stock.available, stock.reserved) == (25, 0)


def test_set_available_creates_a_missing_record_with_zero_reserved(client: Any) -> None:
    stock = DynamoInventoryRepository(client).set_available("NEW", 12)

    assert (stock.sku, stock.available, stock.reserved) == ("NEW", 12, 0)
    assert DynamoInventoryRepository(client).get("NEW") == stock


def test_set_available_never_erases_what_is_already_reserved(client: Any) -> None:
    put(client, "SKU-1", available=10, reserved=4)

    stock = DynamoInventoryRepository(client).set_available("SKU-1", 99)

    assert (stock.available, stock.reserved) == (99, 4)


def test_set_available_moves_updated_at_forward(client: Any) -> None:
    put(client, "SKU-1", 10)
    before = DynamoInventoryRepository(client).get("SKU-1")
    after = DynamoInventoryRepository(client).set_available("SKU-1", 11)
    assert before is not None
    assert after.updated_at > before.updated_at


def test_get_many_returns_only_the_records_that_exist(client: Any) -> None:
    put(client, "A", 1)
    put(client, "C", 3)

    found = DynamoInventoryRepository(client).get_many(["A", "B", "C", "A"])  # B missing, A twice

    assert {sku: item.available for sku, item in found.items()} == {"A": 1, "C": 3}


def test_get_many_with_nothing_to_fetch_makes_no_request(client: Any) -> None:
    assert DynamoInventoryRepository(client).get_many([]) == {}
