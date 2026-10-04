"""Stock seeding against a DynamoDB emulator (moto). The catalog half is checked against a real
PostgreSQL when the stack is up; here we pin the idempotency rule that protects live stock."""

import importlib
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

SEED_DIR = Path(__file__).resolve().parents[4] / "local" / "seed"


@pytest.fixture
def seed_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(SEED_DIR))
    sys.modules.pop("seed", None)
    sys.modules.pop("catalog", None)
    return importlib.import_module("seed")


@pytest.fixture
def inventory_table():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="inventory",
            AttributeDefinitions=[{"AttributeName": "sku", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "sku", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield client


def available(client, sku: str) -> int:
    item = client.get_item(TableName="inventory", Key={"sku": {"S": sku}}, ConsistentRead=True)
    return int(item["Item"]["available"]["N"])


def test_first_run_inserts_every_cloudpunk(seed_module, inventory_table) -> None:
    result = seed_module.seed_stock(inventory_table)

    assert result == {"stock_inserted": 100, "stock_already_present": 0}
    assert inventory_table.scan(TableName="inventory", Select="COUNT")["Count"] == 100


def test_second_run_changes_nothing(seed_module, inventory_table) -> None:
    seed_module.seed_stock(inventory_table)

    result = seed_module.seed_stock(inventory_table)

    assert result == {"stock_inserted": 0, "stock_already_present": 100}
    assert inventory_table.scan(TableName="inventory", Select="COUNT")["Count"] == 100


def test_reseeding_never_resets_a_cloudpunk_that_has_been_sold(
    seed_module,
    inventory_table,
) -> None:
    seed_module.seed_stock(inventory_table)
    inventory_table.update_item(
        TableName="inventory",
        Key={"sku": {"S": "CP-0001"}},
        UpdateExpression="SET available = :n",
        ExpressionAttributeValues={":n": {"N": "0"}},
    )

    seed_module.seed_stock(inventory_table)

    assert available(inventory_table, "CP-0001") == 0


def test_items_have_the_documented_attributes(seed_module, inventory_table) -> None:
    seed_module.seed_stock(inventory_table)

    item = inventory_table.get_item(
        TableName="inventory", Key={"sku": {"S": "CP-0001"}}, ConsistentRead=True
    )["Item"]

    assert set(item) == {"sku", "available", "reserved", "updated_at"}
    assert item["reserved"] == {"N": "0"}
    assert item["available"] == {"N": "1"}  # one of each


def test_stock_goes_to_the_configured_table_and_not_to_the_default(seed_module) -> None:
    """In the cloud the table is loria-inventory (INVENTORY_TABLE); seeding "inventory" would
    either fail or fill a table nothing reads."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="loria-inventory",
            AttributeDefinitions=[{"AttributeName": "sku", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "sku", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )

        result = seed_module.seed_stock(client, "loria-inventory")

        assert result == {"stock_inserted": 100, "stock_already_present": 0}
        assert client.scan(TableName="loria-inventory", Select="COUNT")["Count"] == 100
        assert client.list_tables()["TableNames"] == ["loria-inventory"]
