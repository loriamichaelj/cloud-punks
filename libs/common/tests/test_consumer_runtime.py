import threading
import time
from typing import Any

import httpx2
import pytest
from helpers import FakeSqs, make_envelope, sqs_body

from retail_common.config import BaseServiceSettings
from retail_common.consumer_runtime import ConsumerRuntime, build_consumer_runtime
from retail_common.events.consumer import HandlerOutcome
from retail_common.health import ReadinessCheck


def start(runtime: ConsumerRuntime) -> tuple[threading.Thread, dict[str, int]]:
    """Run the runtime on a thread (signal handlers can only be installed on the main one)."""
    seen: dict[str, int] = {}
    ready = threading.Event()

    def on_started(port: int) -> None:
        seen["port"] = port
        ready.set()

    thread = threading.Thread(
        target=runtime.run,
        kwargs={
            "host": "127.0.0.1",
            "port": 0,
            "install_signal_handlers": False,
            "on_started": on_started,
        },
    )
    thread.start()
    assert ready.wait(timeout=10), "the runtime never started"
    return thread, seen


def test_a_running_consumer_serves_health_and_metrics_and_stops_cleanly(
    settings: BaseServiceSettings,
) -> None:
    sqs = FakeSqs([sqs_body(make_envelope())])
    sqs.long_poll_s = (
        0.05  # like real long polling, an idle consumer must not spin and starve the HTTP thread
    )
    runtime = build_consumer_runtime(settings, sqs, "inventory-order-events")
    handled: list[str] = []

    def handler(envelope: Any, _data: Any) -> HandlerOutcome:
        handled.append(envelope.event_id)
        return HandlerOutcome.PROCESSED

    runtime.consumer.register("OrderCreated", handler)
    thread, seen = start(runtime)
    try:
        deadline = time.monotonic() + 10
        while not handled and time.monotonic() < deadline:
            time.sleep(0.05)
        base = f"http://127.0.0.1:{seen['port']}"
        assert httpx2.get(f"{base}/health/live").status_code == 200
        assert httpx2.get(f"{base}/health/ready").status_code == 200
        metrics = httpx2.get(f"{base}/metrics").text
    finally:
        runtime.consumer.stop()
        thread.join(timeout=10)

    assert len(handled) == 1
    assert not thread.is_alive()
    # The consumer's counters and the app's share one registry: the handled event is visible.
    assert 'events_consumed_total{event_type="OrderCreated",outcome="processed"} 1.0' in metrics


def test_readiness_reflects_the_consumers_required_stores(settings: BaseServiceSettings) -> None:
    def down() -> None:
        raise ConnectionError("store down")

    idle = FakeSqs([])
    idle.long_poll_s = 0.05
    runtime = build_consumer_runtime(
        settings, idle, "q", readiness_checks=[ReadinessCheck("postgres", down)]
    )
    thread, seen = start(runtime)
    try:
        base = f"http://127.0.0.1:{seen['port']}"
        assert httpx2.get(f"{base}/health/ready").status_code == 503
        assert httpx2.get(f"{base}/health/live").status_code == 200  # liveness checks nothing
    finally:
        runtime.consumer.stop()
        thread.join(timeout=10)


def test_the_side_server_is_stopped_even_if_the_consumer_crashes(
    settings: BaseServiceSettings,
) -> None:
    class Exploding(FakeSqs):
        def get_queue_url(self, *, QueueName: str) -> dict[str, str]:
            raise RuntimeError("queue does not exist")

    runtime = build_consumer_runtime(settings, Exploding([]), "missing")
    ports: list[int] = []

    with pytest.raises(RuntimeError, match="queue does not exist"):
        runtime.run(
            host="127.0.0.1", port=0, install_signal_handlers=False, on_started=ports.append
        )

    try:
        httpx2.get(f"http://127.0.0.1:{ports[0]}/health/live", timeout=1)
    except httpx2.TransportError:
        return
    raise AssertionError("the side server kept running after the consumer crashed")
