import contextvars
from collections.abc import Callable

import httpx
import pytest
from tenacity import wait_none

from retail_common.errors import UpstreamUnavailableError
from retail_common.http_client import ServiceHttpClient
from retail_common.logging import CORRELATION_HEADER, set_correlation_id


class Upstream:
    """A MockTransport handler that replays scripted responses and records the requests."""

    def __init__(self, *script: httpx.Response | Exception) -> None:
        self.script = list(script)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        return step


def client_for(upstream: Upstream, **kwargs: object) -> ServiceHttpClient:
    return ServiceHttpClient(
        "http://product-service:8001",
        upstream="product-service",
        retry_wait=wait_none(),
        transport=httpx.MockTransport(upstream),
        **kwargs,  # type: ignore[arg-type]
    )


def ok(status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"ok": True})


def test_get_is_retried_until_it_succeeds() -> None:
    upstream = Upstream(ok(503), ok(503), ok(200))
    response = client_for(upstream).get("/api/v1/products/SKU-1")

    assert response.status_code == 200
    assert len(upstream.requests) == 3  # the first try plus the 2 allowed retries


def test_get_gives_up_after_two_retries_with_a_503() -> None:
    upstream = Upstream(ok(503))

    with pytest.raises(UpstreamUnavailableError) as raised:
        client_for(upstream).get("/api/v1/products/SKU-1")

    assert len(upstream.requests) == 3
    assert raised.value.status_code == 503
    assert raised.value.headers["Retry-After"] == "1"
    assert "product-service" in raised.value.message


@pytest.mark.parametrize("status", [502, 503, 504])
def test_gateway_style_errors_are_retried(status: int) -> None:
    upstream = Upstream(ok(status), ok(200))
    assert client_for(upstream).get("/x").status_code == 200
    assert len(upstream.requests) == 2


def test_transport_errors_are_retried() -> None:
    upstream = Upstream(httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), ok(200))
    assert client_for(upstream).get("/x").status_code == 200
    assert len(upstream.requests) == 3


def test_persistent_transport_error_becomes_upstream_unavailable() -> None:
    upstream = Upstream(httpx.ConnectError("refused"))
    with pytest.raises(UpstreamUnavailableError):
        client_for(upstream).get("/x")
    assert len(upstream.requests) == 3


def test_a_plain_post_is_never_retried() -> None:
    upstream = Upstream(ok(503), ok(200))

    with pytest.raises(UpstreamUnavailableError):
        client_for(upstream).post("/api/v1/orders", json={"a": 1})

    assert len(upstream.requests) == 1


def test_a_post_marked_retry_safe_is_retried() -> None:
    """The read-only availability pre-check is the one POST allowed to retry."""
    upstream = Upstream(ok(503), ok(200))

    response = client_for(upstream).post("/api/v1/inventory/availability", json=[], retry_safe=True)

    assert response.status_code == 200
    assert len(upstream.requests) == 2


def test_client_errors_are_returned_not_raised_and_not_retried() -> None:
    upstream = Upstream(httpx.Response(404, json={"error": {"code": "NOT_FOUND"}}))

    response = client_for(upstream).get("/api/v1/products/NOPE")

    assert response.status_code == 404
    assert len(upstream.requests) == 1


def test_a_500_is_not_retried_but_is_still_an_upstream_failure() -> None:
    upstream = Upstream(ok(500), ok(200))

    with pytest.raises(UpstreamUnavailableError):
        client_for(upstream).get("/x")

    assert len(upstream.requests) == 1


def in_fresh_context(fn: Callable[[], None]) -> None:
    """Run ``fn`` in a copy of the context so a correlation id never leaks between tests."""
    contextvars.copy_context().run(fn)


def test_the_correlation_id_is_forwarded() -> None:
    upstream = Upstream(ok())

    def call() -> None:
        set_correlation_id("corr-77")
        client_for(upstream).get("/x")

    in_fresh_context(call)

    assert upstream.requests[0].headers[CORRELATION_HEADER] == "corr-77"


def test_no_correlation_header_is_invented_when_there_is_no_context() -> None:
    upstream = Upstream(ok())
    in_fresh_context(lambda: client_for(upstream).get("/x"))
    assert CORRELATION_HEADER not in upstream.requests[0].headers


def test_caller_headers_are_kept_alongside_the_correlation_id() -> None:
    upstream = Upstream(ok())

    def call() -> None:
        set_correlation_id("corr-1")
        client_for(upstream).get("/x", headers={"X-Other": "yes"})

    in_fresh_context(call)

    sent = upstream.requests[0].headers
    assert sent["X-Other"] == "yes"
    assert sent[CORRELATION_HEADER] == "corr-1"


def test_timeouts_default_to_one_second_connect_and_two_seconds_read() -> None:
    upstream = Upstream(ok())
    client_for(upstream).get("/x")

    timeout = upstream.requests[0].extensions["timeout"]
    assert timeout["connect"] == 1.0
    assert timeout["read"] == 2.0


def test_timeouts_come_from_the_arguments() -> None:
    upstream = Upstream(ok())
    client_for(upstream, connect_timeout_s=0.25, read_timeout_s=4.0).get("/x")

    timeout = upstream.requests[0].extensions["timeout"]
    assert timeout["connect"] == 0.25
    assert timeout["read"] == 4.0


def test_requests_resolve_against_the_base_url_and_the_client_closes() -> None:
    upstream = Upstream(ok())
    with client_for(upstream) as client:
        client.get("/api/v1/products/SKU-1")

    assert str(upstream.requests[0].url) == "http://product-service:8001/api/v1/products/SKU-1"
    with pytest.raises(RuntimeError, match="closed"):
        client.get("/x")
