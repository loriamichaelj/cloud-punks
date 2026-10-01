"""Integration fixtures: the service in-process against LocalStack's real DynamoDB.

Run with ``make itest`` (the stack must be up). Everything created here is prefixed ``ITEST-`` and
removed afterwards.

Safety: the AWS environment is forced to LocalStack with dummy credentials *before* any client is
built, so even a shell with real AWS credentials or a profile cannot make these tests touch an
actual account.
"""

import os
import uuid
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

LOCALSTACK = "http://localhost:4566"
DEAD_ENDPOINT = "http://127.0.0.1:1"  # nothing listens on port 1: connection refused

os.environ.update(
    AWS_ENDPOINT_URL=LOCALSTACK,
    AWS_ACCESS_KEY_ID="test",
    AWS_SECRET_ACCESS_KEY="test",
    AWS_REGION="us-east-1",
    AWS_DEFAULT_REGION="us-east-1",
)
for name in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_ENDPOINT_URL_DYNAMODB"):
    os.environ.pop(name, None)

READS = ("GetItem", "BatchGetItem")


class ReadRecorder:
    """Records whether each DynamoDB read asked for a strongly consistent read, as sent."""

    def __init__(self) -> None:
        self.reads: list[tuple[str, bool]] = []

    def record(self, params: dict[str, Any], model: Any, **_kwargs: Any) -> None:
        operation = model.name
        if operation == "GetItem":
            self.reads.append((operation, params.get("ConsistentRead") is True))
        elif operation == "BatchGetItem":
            tables = params["RequestItems"].values()
            self.reads.append((operation, all(t.get("ConsistentRead") is True for t in tables)))


@pytest.fixture(scope="session")
def recorder() -> ReadRecorder:
    recorder = ReadRecorder()
    boto3.setup_default_session()
    for operation in READS:
        boto3.DEFAULT_SESSION.events.register(
            f"provide-client-params.dynamodb.{operation}", recorder.record
        )
    return recorder


@pytest.fixture(scope="session")
def dynamodb(recorder: ReadRecorder) -> Any:
    client = boto3.client("dynamodb", region_name="us-east-1")
    try:
        client.describe_table(TableName="inventory")
    except EndpointConnectionError:
        pytest.exit(f"LocalStack is not reachable on {LOCALSTACK}: run `make up`", returncode=2)
    except client.exceptions.ResourceNotFoundException:
        pytest.exit("the `inventory` table does not exist: run `make up` (LocalStack bootstrap)")
    return client


def _wipe(dynamodb: Any) -> None:
    pages = dynamodb.get_paginator("scan").paginate(
        TableName="inventory",
        FilterExpression="begins_with(sku, :p)",
        ExpressionAttributeValues={":p": {"S": "ITEST-"}},
        ProjectionExpression="sku",
        ConsistentRead=True,
    )
    for page in pages:
        for item in page["Items"]:
            dynamodb.delete_item(TableName="inventory", Key={"sku": item["sku"]})


ORDER_PREFIX = "01TEST"  # a valid ULID prefix (Crockford has no 'I'), so test orders are findable


def _wipe_reservations(dynamodb: Any) -> None:
    pages = dynamodb.get_paginator("scan").paginate(
        TableName="inventory_reservations",
        FilterExpression="begins_with(order_id, :p)",
        ExpressionAttributeValues={":p": {"S": ORDER_PREFIX}},
        ProjectionExpression="order_id",
        ConsistentRead=True,
    )
    for page in pages:
        for item in page["Items"]:
            dynamodb.delete_item(
                TableName="inventory_reservations", Key={"order_id": item["order_id"]}
            )


def new_order_id() -> str:
    return ORDER_PREFIX + uuid.uuid4().hex[:20].upper()


@pytest.fixture(autouse=True)
def _clean(dynamodb: Any, recorder: ReadRecorder) -> Iterator[None]:
    _wipe(dynamodb)
    _wipe_reservations(dynamodb)
    recorder.reads.clear()
    yield
    _wipe(dynamodb)
    _wipe_reservations(dynamodb)


@pytest.fixture
def sku() -> str:
    return f"ITEST-{uuid.uuid4().hex[:10]}"


@pytest.fixture
def client(dynamodb: Any) -> Iterator[TestClient]:
    """The real app wiring: it builds its own DynamoDB client from the environment."""
    with TestClient(create_app(Settings(aws_region="us-east-1"))) as client:  # type: ignore[call-arg]
        yield client


def put_raw(dynamodb: Any, sku: str, available: int, reserved: int = 0) -> None:
    """Write a record directly, the way the seed script and (later) reservations do."""
    dynamodb.put_item(
        TableName="inventory",
        Item={
            "sku": {"S": sku},
            "available": {"N": str(available)},
            "reserved": {"N": str(reserved)},
            "updated_at": {"S": "2026-10-01T12:00:00+00:00"},
        },
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(pytest.mark.integration)
