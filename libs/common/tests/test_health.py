import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from retail_common.health import ReadinessCheck, build_health_router


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Probe:
    """A probe that counts calls and fails on demand."""

    def __init__(self, *, fail: Exception | None = None, delay_s: float = 0.0) -> None:
        self.calls = 0
        self.fail = fail
        self.delay_s = delay_s

    def __call__(self) -> None:
        self.calls += 1
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.fail is not None:
            raise self.fail


def client_for(*checks: ReadinessCheck, clock: Clock | None = None, **kwargs: float) -> TestClient:
    app = FastAPI()
    app.include_router(build_health_router(checks, clock=clock or Clock(), **kwargs))
    return TestClient(app)


def test_live_is_ok_and_never_touches_a_dependency() -> None:
    probe = Probe(fail=ConnectionError("db down"))
    client = client_for(ReadinessCheck("postgres", probe))

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert probe.calls == 0


def test_ready_reports_each_dependency() -> None:
    client = client_for(ReadinessCheck("postgres", Probe()))

    response = client.get("/health/ready")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ready"
    assert body["dependencies"]["postgres"]["status"] == "ok"
    assert body["dependencies"]["postgres"]["required"] is True
    assert "latency_ms" in body["dependencies"]["postgres"]


def test_ready_with_no_dependencies_is_ready() -> None:
    assert client_for().get("/health/ready").status_code == 200


def test_failing_required_dependency_makes_the_service_unready() -> None:
    client = client_for(ReadinessCheck("postgres", Probe(fail=ConnectionError("refused"))))

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["dependencies"]["postgres"]["status"] == "error"


def test_error_detail_is_the_exception_class_only() -> None:
    probe = Probe(fail=RuntimeError("password=hunter2 host=10.0.0.5"))
    response = client_for(ReadinessCheck("postgres", probe)).get("/health/ready")

    assert response.json()["dependencies"]["postgres"]["error"] == "RuntimeError"
    assert "hunter2" not in response.text
    assert "10.0.0.5" not in response.text


def test_optional_dependency_failure_does_not_fail_readiness() -> None:
    """The cache is not required: Valkey down must leave the service ready (DESIGN.md section 8)."""
    client = client_for(
        ReadinessCheck("postgres", Probe()),
        ReadinessCheck("valkey", Probe(fail=ConnectionError("down")), required=False),
    )

    response = client.get("/health/ready")

    body = response.json()
    assert response.status_code == 200
    assert body["dependencies"]["valkey"]["status"] == "error"
    assert body["dependencies"]["valkey"]["required"] is False


def test_slow_dependency_times_out() -> None:
    client = client_for(ReadinessCheck("postgres", Probe(delay_s=0.3)), timeout_s=0.05)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["dependencies"]["postgres"]["error"] == "TimeoutError"


def test_results_are_cached_for_ten_seconds() -> None:
    clock = Clock()
    probe = Probe()
    client = client_for(ReadinessCheck("postgres", probe), clock=clock)

    client.get("/health/ready")
    clock.now += 9.9
    client.get("/health/ready")
    assert probe.calls == 1

    clock.now += 0.2
    client.get("/health/ready")
    assert probe.calls == 2


def test_service_recovers_without_restart_once_the_dependency_is_back() -> None:
    """Drill: PostgreSQL down -> ready 503, liveness 200 -> PostgreSQL back -> ready again."""
    clock = Clock()
    probe = Probe(fail=ConnectionError("down"))
    client = client_for(ReadinessCheck("postgres", probe), clock=clock)

    assert client.get("/health/ready").status_code == 503
    assert client.get("/health/live").status_code == 200

    probe.fail = None
    clock.now += 10.1
    assert client.get("/health/ready").status_code == 200
