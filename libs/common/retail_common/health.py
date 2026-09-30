"""Liveness and readiness endpoints (DESIGN.md section 8).

* ``GET /health/live`` answers 200 if the event loop responds. It checks **nothing** external: a
  database outage must not make Kubernetes restart every pod.
* ``GET /health/ready`` answers 200 only if every *required* dependency responds within the
  timeout (500 ms). Optional dependencies (the cache) are reported but never fail readiness.
  Results are cached per check for 10 s so probes cannot stampede a struggling store.

Probes are plain synchronous callables that raise on failure (``SELECT 1``, ``DescribeTable``);
they run in a worker thread so a slow driver cannot block the event loop.
"""

import asyncio
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse

_log = structlog.get_logger("retail_common.health")

READY_TIMEOUT_S = 0.5
READY_CACHE_TTL_S = 10.0


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    probe: Callable[[], None]
    required: bool = True


@dataclass(frozen=True)
class _Result:
    ok: bool
    latency_ms: float
    error: str | None
    checked_at: float


class ReadinessEvaluator:
    def __init__(
        self,
        checks: Sequence[ReadinessCheck],
        *,
        timeout_s: float = READY_TIMEOUT_S,
        cache_ttl_s: float = READY_CACHE_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._checks = list(checks)
        self._timeout_s = timeout_s
        self._cache_ttl_s = cache_ttl_s
        self._clock = clock
        self._cache: dict[str, _Result] = {}

    async def _run(self, check: ReadinessCheck) -> _Result:
        cached = self._cache.get(check.name)
        if cached is not None and self._clock() - cached.checked_at < self._cache_ttl_s:
            return cached

        started = time.perf_counter()
        error: str | None = None
        try:
            async with asyncio.timeout(self._timeout_s):
                await asyncio.to_thread(check.probe)
        except TimeoutError:
            error = "TimeoutError"
        except Exception as exc:  # noqa: BLE001 - a probe may raise anything; we report the class
            error = type(exc).__name__
            _log.warning("readiness_probe_failed", check=check.name, error=str(exc))
        result = _Result(
            ok=error is None,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            error=error,
            checked_at=self._clock(),
        )
        self._cache[check.name] = result
        return result

    async def evaluate(self) -> tuple[bool, dict[str, dict[str, object]]]:
        """Return ``(ready, per-dependency report)``."""
        ready = True
        report: dict[str, dict[str, object]] = {}
        for check in self._checks:
            result = await self._run(check)
            entry: dict[str, object] = {
                "status": "ok" if result.ok else "error",
                "required": check.required,
                "latency_ms": result.latency_ms,
            }
            if result.error is not None:
                entry["error"] = result.error
                if check.required:
                    ready = False
            report[check.name] = entry
        return ready, report


def build_health_router(
    checks: Sequence[ReadinessCheck] = (),
    *,
    timeout_s: float = READY_TIMEOUT_S,
    cache_ttl_s: float = READY_CACHE_TTL_S,
    clock: Callable[[], float] = time.monotonic,
) -> APIRouter:
    evaluator = ReadinessEvaluator(
        checks, timeout_s=timeout_s, cache_ttl_s=cache_ttl_s, clock=clock
    )
    router = APIRouter()

    @router.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/health/ready")
    async def ready() -> JSONResponse:
        is_ready, report = await evaluator.evaluate()
        return JSONResponse(
            {"status": "ready" if is_ready else "unavailable", "dependencies": report},
            status_code=200 if is_ready else 503,
        )

    return router
