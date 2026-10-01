"""Integration fixtures: the service in-process against LocalStack's real DynamoDB.

Run with ``make itest`` (the stack must be up). Every notification created here belongs to an
order whose id starts with ``01TEST`` (a valid ULID prefix) and is removed afterwards.

Safety: the AWS environment is forced to LocalStack with dummy credentials *before* any client is
built, so a shell with real AWS credentials or a profile cannot make these tests touch an account.
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
os.environ.update(
    AWS_ENDPOINT_URL=LOCALSTACK,
    AWS_ACCESS_KEY_ID="test",
    AWS_SECRET_ACCESS_KEY="test",
    AWS_REGION="us-east-1",
    AWS_DEFAULT_REGION="us-east-1",
)
for _name in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_ENDPOINT_URL_DYNAMODB"):
    os.environ.pop(_name, None)

ORDER_PREFIX = "01TEST"


def new_id() -> str:
    """A valid ULID the cleanup recognises by its prefix."""
    return ORDER_PREFIX + uuid.uuid4().hex[:20].upper()


@pytest.fixture(scope="session")
def dynamodb() -> Any:
    client = boto3.client("dynamodb", region_name="us-east-1")
    try:
        client.describe_table(TableName="notifications")
    except EndpointConnectionError:
        pytest.exit(f"LocalStack is not reachable on {LOCALSTACK}: run `make up`", returncode=2)
    except client.exceptions.ResourceNotFoundException:
        pytest.exit("the `notifications` table does not exist: run `make up`")
    return client


def _wipe(dynamodb: Any) -> None:
    pages = dynamodb.get_paginator("scan").paginate(
        TableName="notifications",
        FilterExpression="begins_with(order_id, :p)",
        ExpressionAttributeValues={":p": {"S": ORDER_PREFIX}},
        ProjectionExpression="order_id, event_id",
        ConsistentRead=True,
    )
    for page in pages:
        for item in page["Items"]:
            dynamodb.delete_item(TableName="notifications", Key=item)


@pytest.fixture(autouse=True)
def _clean(dynamodb: Any) -> Iterator[None]:
    _wipe(dynamodb)
    yield
    _wipe(dynamodb)


@pytest.fixture
def client(dynamodb: Any) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(aws_region="us-east-1"))) as client:  # type: ignore[call-arg]
        yield client


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(pytest.mark.integration)
