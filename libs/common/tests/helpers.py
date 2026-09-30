"""Test doubles and builders shared by the libs/common tests."""

import json
from typing import Any

from botocore.exceptions import ClientError
from ulid import ULID

from retail_common.events.envelope import Envelope


def order_created_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "order_id": str(ULID()),
        "customer_id": "cust-1001",
        "items": [{"sku": "SKU-TSHIRT-BLK-M", "quantity": 2}],
        "total_amount": "39.98",
        "currency": "USD",
    }
    return {**data, **overrides}


def make_envelope(
    event_type: str = "OrderCreated", data: dict[str, Any] | None = None, **overrides: Any
) -> Envelope:
    fields: dict[str, Any] = {
        "event_type": event_type,
        "producer": "order-service",
        "data": order_created_data() if data is None else data,
        "correlation_id": "corr-default",
    }
    return Envelope.create(**{**fields, **overrides})


def sqs_body(envelope: Envelope) -> str:
    """What EventBridge delivers to SQS: the whole event, with our envelope as ``detail``."""
    return json.dumps(
        {
            "version": "0",
            "id": "11111111-2222-3333-4444-555555555555",
            "detail-type": envelope.event_type,
            "source": "retail.order",
            "detail": json.loads(envelope.model_dump_json()),
        }
    )


def client_error(code: str = "InternalFailure", operation: str = "Op") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, operation)


class FakeEvents:
    """Stands in for the boto3 EventBridge client; ``responder`` decides each response."""

    def __init__(self, responder: Any = None) -> None:
        self.calls: list[list[dict[str, Any]]] = []
        self._responder = responder

    def put_events(self, *, Entries: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append(Entries)
        if self._responder is not None:
            return self._responder(len(self.calls), Entries)  # type: ignore[no-any-return]
        return {
            "FailedEntryCount": 0,
            "Entries": [{"EventId": f"eb-{i}"} for i, _ in enumerate(Entries)],
        }


class FakeSqs:
    """Stands in for the boto3 SQS client and records the order of calls in ``log``."""

    def __init__(self, bodies: list[str] | None = None, *, log: list[str] | None = None) -> None:
        self.messages = [
            {
                "MessageId": f"m-{i}",
                "ReceiptHandle": f"rh-{i}",
                "Body": body,
                "Attributes": {"ApproximateReceiveCount": "1"},
            }
            for i, body in enumerate(bodies or [])
        ]
        self.log = log if log is not None else []
        self.deleted: list[str] = []
        self.receive_calls: list[dict[str, Any]] = []
        self.receive_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.on_receive: Any = None

    def get_queue_url(self, *, QueueName: str) -> dict[str, str]:
        return {"QueueUrl": f"http://sqs.test/000000000000/{QueueName}"}

    def receive_message(self, **kwargs: Any) -> dict[str, Any]:
        self.receive_calls.append(kwargs)
        if self.on_receive is not None:
            self.on_receive(len(self.receive_calls))
        if self.receive_error is not None:
            raise self.receive_error
        batch = self.messages[: kwargs["MaxNumberOfMessages"]]
        self.messages = self.messages[len(batch) :]
        return {"Messages": batch} if batch else {}

    def delete_message(self, *, QueueUrl: str, ReceiptHandle: str) -> dict[str, Any]:
        self.log.append(f"delete:{ReceiptHandle}")
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append(ReceiptHandle)
        return {}
