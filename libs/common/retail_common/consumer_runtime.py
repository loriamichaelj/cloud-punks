"""The process shell shared by every SQS consumer (DESIGN.md sections 6 and 8).

A consumer process is a poll loop on the main thread plus a small HTTP server on port 9000 for
Kubernetes probes and Prometheus. On SIGTERM it stops polling, finishes the batch in flight and
exits; the poll long-wait (20 s) plus a batch fits in ``terminationGracePeriodSeconds: 30``.
"""

import signal
import types
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import structlog
from fastapi import FastAPI

from retail_common.config import BaseServiceSettings
from retail_common.events.consumer import SqsConsumer
from retail_common.health import ReadinessCheck
from retail_common.queue_metrics import register_queue_depth
from retail_common.service import create_service_app
from retail_common.side_server import DEFAULT_PORT, SideServer

_log = structlog.get_logger("consumer_runtime")


@dataclass
class ConsumerRuntime:
    consumer: SqsConsumer
    side_app: FastAPI

    def run(
        self,
        *,
        host: str = "0.0.0.0",  # noqa: S104 - container bind
        port: int = DEFAULT_PORT,
        install_signal_handlers: bool = True,
        on_started: Callable[[int], None] | None = None,
    ) -> None:
        """Serve health and metrics, then poll until stopped. Always stops the side server."""
        side_server = SideServer(self.side_app, host=host, port=port)
        if install_signal_handlers:
            self._install_signal_handlers()
        side_server.start()
        try:
            if on_started is not None:
                on_started(side_server.port)
            self.consumer.run()
        finally:
            side_server.stop()

    def _install_signal_handlers(self) -> None:
        def shutdown(signum: int, _frame: types.FrameType | None) -> None:
            _log.info("consumer_shutdown_requested", signal=signal.Signals(signum).name)
            self.consumer.stop()

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)


def build_consumer_runtime(
    settings: BaseServiceSettings,
    sqs_client: object,
    queue_name: str,
    *,
    readiness_checks: Sequence[ReadinessCheck] = (),
) -> ConsumerRuntime:
    """Wire the side app first, then a consumer that shares its event metrics.

    Order matters: ``create_service_app`` registers ``EventMetrics`` on its registry, and
    registering them a second time (for the consumer) raises ``DuplicateTimeseries``. Callers add
    handlers, and any extra metrics via ``runtime.side_app.state.registry``, afterwards.
    """
    side_app = create_service_app(settings, readiness_checks=readiness_checks)
    register_queue_depth(side_app.state.registry, sqs_client, queue_name)
    consumer = SqsConsumer(sqs_client, queue_name, metrics=side_app.state.event_metrics)
    return ConsumerRuntime(consumer=consumer, side_app=side_app)
