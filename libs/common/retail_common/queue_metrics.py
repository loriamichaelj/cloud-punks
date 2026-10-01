"""Queue depth for the dashboard: ``queue_messages{queue, state}`` (DESIGN.md section 12, M9).

A consumer reports its own queue and that queue's dead-letter queue, read with
``GetQueueAttributes`` at scrape time (it is not a receive, so it never moves a message towards
the DLQ). If SQS cannot answer, the scrape simply omits the series instead of failing: a gap in
the graph is the honest signal.

``state`` is ``visible`` (waiting), ``in_flight`` (received, not yet deleted) or, for the DLQ,
the same two states under the DLQ's own ``queue`` label.
"""

from collections.abc import Iterable
from typing import Any

import structlog
from prometheus_client import CollectorRegistry
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

_log = structlog.get_logger("retail_common.queue_metrics")

DLQ_SUFFIX = "-dlq"
_ATTRIBUTES = ["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"]


class QueueDepthCollector(Collector):
    def __init__(self, client: Any, queue_names: Iterable[str]) -> None:
        self._client = client
        self._queue_names = tuple(queue_names)
        self._urls: dict[str, str] = {}

    def collect(self) -> Iterable[GaugeMetricFamily]:
        family = GaugeMetricFamily(
            "queue_messages",
            "Approximate SQS messages by queue and state (visible or in_flight).",
            labels=["queue", "state"],
        )
        for name in self._queue_names:
            try:
                if name not in self._urls:
                    self._urls[name] = self._client.get_queue_url(QueueName=name)["QueueUrl"]
                attributes = self._client.get_queue_attributes(
                    QueueUrl=self._urls[name], AttributeNames=_ATTRIBUTES
                )["Attributes"]
            except Exception as exc:  # noqa: BLE001 - a scrape must never fail because SQS does
                _log.warning("queue_depth_unavailable", queue=name, error=type(exc).__name__)
                continue
            family.add_metric([name, "visible"], float(attributes["ApproximateNumberOfMessages"]))
            family.add_metric(
                [name, "in_flight"], float(attributes["ApproximateNumberOfMessagesNotVisible"])
            )
        yield family


def register_queue_depth(registry: CollectorRegistry, client: Any, queue_name: str) -> None:
    """Report ``queue_name`` and its DLQ on ``registry``."""
    registry.register(QueueDepthCollector(client, [queue_name, queue_name + DLQ_SUFFIX]))
