import httpx2
from fastapi import FastAPI

from retail_common.config import BaseServiceSettings
from retail_common.health import ReadinessCheck
from retail_common.service import create_service_app
from retail_common.side_server import SideServer


def build(settings: BaseServiceSettings, *checks: ReadinessCheck) -> FastAPI:
    return create_service_app(settings, readiness_checks=checks)


def test_serves_health_and_metrics_over_real_http(settings: BaseServiceSettings) -> None:
    server = SideServer(build(settings), host="127.0.0.1", port=0)
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        assert httpx2.get(f"{base}/health/live").json() == {"status": "ok"}
        assert httpx2.get(f"{base}/health/ready").status_code == 200
        assert "http_requests_total" in httpx2.get(f"{base}/metrics").text
    finally:
        server.stop()


def test_readiness_reflects_a_failing_dependency(settings: BaseServiceSettings) -> None:
    def down() -> None:
        raise ConnectionError("db down")

    server = SideServer(build(settings, ReadinessCheck("postgres", down)), host="127.0.0.1", port=0)
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        assert httpx2.get(f"{base}/health/ready").status_code == 503
        assert httpx2.get(f"{base}/health/live").status_code == 200  # liveness checks nothing
    finally:
        server.stop()


def test_stop_releases_the_port_and_is_safe_to_repeat(settings: BaseServiceSettings) -> None:
    server = SideServer(build(settings), host="127.0.0.1", port=0)
    server.start()
    port = server.port

    server.stop()
    server.stop()

    try:
        httpx2.get(f"http://127.0.0.1:{port}/health/live", timeout=1)
    except httpx2.TransportError:
        return
    raise AssertionError("the port is still serving after stop()")
