from typing import Any

import boto3
from botocore.exceptions import EndpointConnectionError
from moto import mock_aws
from prometheus_client import CollectorRegistry

from retail_common.queue_metrics import register_queue_depth


def _value(registry: CollectorRegistry, queue: str, state: str) -> float | None:
    return registry.get_sample_value("queue_messages", {"queue": queue, "state": state})


@mock_aws
def test_reports_depth_of_the_queue_and_its_dlq_without_receiving() -> None:
    sqs = boto3.client("sqs", region_name="us-east-1")
    sqs.create_queue(QueueName="work-dlq")
    url = sqs.create_queue(QueueName="work")["QueueUrl"]
    for i in range(3):
        sqs.send_message(QueueUrl=url, MessageBody=str(i))
    registry = CollectorRegistry()
    register_queue_depth(registry, sqs, "work")

    assert _value(registry, "work", "visible") == 3
    assert _value(registry, "work", "in_flight") == 0
    assert _value(registry, "work-dlq", "visible") == 0
    # reading the depth is not a receive: the messages are still there, untouched
    assert _value(registry, "work", "visible") == 3


@mock_aws
def test_a_missing_queue_is_left_out_not_an_error() -> None:
    sqs = boto3.client("sqs", region_name="us-east-1")
    registry = CollectorRegistry()
    register_queue_depth(registry, sqs, "nope")

    assert _value(registry, "nope", "visible") is None


def test_an_unreachable_sqs_omits_the_series_instead_of_failing_the_scrape() -> None:
    class Down:
        def get_queue_url(self, **_: Any) -> Any:
            raise EndpointConnectionError(endpoint_url="http://dead")

    registry = CollectorRegistry()
    register_queue_depth(registry, Down(), "work")

    assert _value(registry, "work", "visible") is None
