"""Outbound HTTP client with timeouts, bounded retries and header propagation (section 8).

Rules, all from DESIGN.md:

* connect/read timeouts come from settings (defaults 1 s / 2 s);
* only ``GET`` is retried, plus a POST the caller explicitly marks ``retry_safe=True`` (the
  read-only availability check). Every other POST gets exactly one attempt;
* at most 2 retries, exponential backoff with jitter;
* the current correlation id is forwarded as ``X-Correlation-ID``.

A transport failure or a 5xx that survives the retries becomes ``UpstreamUnavailableError``
(HTTP 503 with ``Retry-After``). Other responses, including 4xx, are returned to the caller.
"""

from types import TracebackType
from typing import Any, Self

import httpx2
import structlog
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)
from tenacity.wait import wait_base

from retail_common.errors import UpstreamUnavailableError
from retail_common.logging import CORRELATION_HEADER, get_correlation_id

_log = structlog.get_logger("retail_common.http_client")

MAX_RETRIES = 2
RETRYABLE_STATUS = frozenset({502, 503, 504})


class _TransientUpstreamError(Exception):
    """Internal signal that one attempt failed in a way worth retrying."""


class ServiceHttpClient:
    def __init__(
        self,
        base_url: str,
        *,
        upstream: str,
        connect_timeout_s: float = 1.0,
        read_timeout_s: float = 2.0,
        max_retries: int = MAX_RETRIES,
        retry_wait: wait_base | None = None,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._upstream = upstream
        self._max_retries = max_retries
        self._retry_wait = retry_wait or wait_exponential_jitter(initial=0.1, max=1.0)
        self._client = httpx2.Client(
            base_url=base_url,
            timeout=httpx2.Timeout(
                connect=connect_timeout_s,
                read=read_timeout_s,
                write=read_timeout_s,
                pool=connect_timeout_s,
            ),
            transport=transport,
        )

    def request(
        self, method: str, url: str, *, retry_safe: bool = False, **kwargs: Any
    ) -> httpx2.Response:
        method = method.upper()
        retries = self._max_retries if method == "GET" or retry_safe else 0

        headers = dict(kwargs.pop("headers", None) or {})
        correlation_id = get_correlation_id()
        if correlation_id is not None:
            headers[CORRELATION_HEADER] = correlation_id

        def attempt() -> httpx2.Response:
            try:
                response = self._client.request(method, url, headers=headers, **kwargs)
            except httpx2.TransportError as exc:
                raise _TransientUpstreamError(type(exc).__name__) from exc
            if response.status_code in RETRYABLE_STATUS:
                raise _TransientUpstreamError(f"HTTP {response.status_code}")
            if response.status_code >= 500:
                # Not worth retrying (a 500 is rarely transient) but still an upstream failure.
                raise UpstreamUnavailableError(f"{self._upstream} is unavailable")
            return response

        def log_retry(state: RetryCallState) -> None:
            _log.warning(
                "upstream_retry",
                upstream=self._upstream,
                attempt=state.attempt_number,
                reason=str(state.outcome.exception()) if state.outcome else None,
            )

        retrying = Retrying(
            stop=stop_after_attempt(retries + 1),
            wait=self._retry_wait,
            retry=retry_if_exception_type(_TransientUpstreamError),
            before_sleep=log_retry,
            reraise=True,
        )
        try:
            return retrying(attempt)
        except _TransientUpstreamError as exc:
            _log.warning("upstream_unavailable", upstream=self._upstream, reason=str(exc))
            raise UpstreamUnavailableError(f"{self._upstream} is unavailable") from exc

    def get(self, url: str, **kwargs: Any) -> httpx2.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, *, retry_safe: bool = False, **kwargs: Any) -> httpx2.Response:
        return self.request("POST", url, retry_safe=retry_safe, **kwargs)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
