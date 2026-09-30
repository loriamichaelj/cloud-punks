import logging
import re
from collections.abc import Callable
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

from retail_common.logging import (
    CORRELATION_HEADER,
    CorrelationMiddleware,
    configure_logging,
    is_valid_correlation_id,
)

ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
Logs = Callable[[], list[dict[str, Any]]]


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)

    @app.get("/orders/{order_id}")
    def get_order(order_id: str) -> dict[str, str]:
        structlog.get_logger("test").info("looking_up_order", order_id=order_id)
        return {"order_id": order_id}

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("kaboom")

    return app


def test_request_log_line_has_the_documented_fields(read_logs: Logs) -> None:
    response = TestClient(build_app()).get("/orders/O1")

    line = next(entry for entry in read_logs() if entry["message"] == "request_completed")
    assert line["service"] == "test-service"
    assert line["environment"] == "test"
    assert line["level"] == "info"
    assert line["correlation_id"] == response.headers[CORRELATION_HEADER]
    assert line["method"] == "GET"
    assert line["status"] == 200
    assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", line["timestamp"])


def test_request_log_uses_the_route_template_not_the_raw_path(read_logs: Logs) -> None:
    TestClient(build_app()).get("/orders/01J9Z6Q4W8K3M2N1P0R7S5T4V3")

    line = next(entry for entry in read_logs() if entry["message"] == "request_completed")
    assert line["route"] == "/orders/{order_id}"


def test_generates_a_correlation_id_when_none_is_supplied() -> None:
    response = TestClient(build_app()).get("/orders/O1")
    assert ULID_RE.match(response.headers[CORRELATION_HEADER])


def test_keeps_a_valid_inbound_correlation_id() -> None:
    response = TestClient(build_app()).get(
        "/orders/O1", headers={CORRELATION_HEADER: "abc-123.X_y"}
    )
    assert response.headers[CORRELATION_HEADER] == "abc-123.X_y"


def test_replaces_an_unsafe_inbound_correlation_id() -> None:
    client = TestClient(build_app())
    for unsafe in ("has space", "semi;colon", "x" * 129, 'quote"'):
        response = client.get("/orders/O1", headers={CORRELATION_HEADER: unsafe})
        assert response.headers[CORRELATION_HEADER] != unsafe
        assert ULID_RE.match(response.headers[CORRELATION_HEADER])


def test_application_log_lines_carry_the_request_correlation_id(read_logs: Logs) -> None:
    response = TestClient(build_app()).get("/orders/O7", headers={CORRELATION_HEADER: "corr-42"})

    lines = read_logs()
    app_line = next(entry for entry in lines if entry["message"] == "looking_up_order")
    assert response.headers[CORRELATION_HEADER] == "corr-42"
    assert app_line["correlation_id"] == "corr-42"
    assert app_line["order_id"] == "O7"


def test_health_probes_do_not_log_at_info(read_logs: Logs) -> None:
    configure_logging("test-service", "test", "INFO")
    TestClient(build_app()).get("/health/live")
    assert [entry for entry in read_logs() if entry["message"] == "request_completed"] == []


def test_failed_request_is_logged_with_status_500(read_logs: Logs) -> None:
    client = TestClient(build_app(), raise_server_exceptions=False)
    response = client.get("/boom")

    line = next(entry for entry in read_logs() if entry["message"] == "request_completed")
    assert response.status_code == 500
    assert line["status"] == 500


def test_standard_library_loggers_are_rendered_as_json(read_logs: Logs) -> None:
    logging.getLogger("uvicorn.error").warning("connection reset")

    line = read_logs()[0]
    assert line["message"] == "connection reset"
    assert line["level"] == "warning"
    assert line["service"] == "test-service"


def test_exceptions_are_rendered_into_the_exception_field(read_logs: Logs) -> None:
    try:
        raise ValueError("bad thing")
    except ValueError:
        structlog.get_logger("test").exception("it_failed")

    line = read_logs()[0]
    assert line["message"] == "it_failed"
    assert "ValueError: bad thing" in line["exception"]


def test_configure_logging_twice_does_not_duplicate_lines(read_logs: Logs) -> None:
    configure_logging("test-service", "test", "INFO")
    configure_logging("test-service", "test", "INFO")
    structlog.get_logger("test").info("once")
    assert len(read_logs()) == 1


def test_correlation_id_validation() -> None:
    assert is_valid_correlation_id("01J9Z6Q4W8K3M2N1P0R7S5T4V3")
    assert is_valid_correlation_id("a.b_c-d")
    assert not is_valid_correlation_id("")
    assert not is_valid_correlation_id("a b")
