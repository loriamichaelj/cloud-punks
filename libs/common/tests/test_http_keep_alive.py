"""Every API process must keep idle connections longer than a proxy's idle timeout."""

from pathlib import Path

import pytest

from retail_common.side_server import HTTP_KEEP_ALIVE_S

ALB_IDLE_TIMEOUT_S = 60
ROOT = Path(__file__).resolve().parents[3]


def test_keep_alive_outlasts_the_load_balancer_idle_timeout() -> None:
    assert HTTP_KEEP_ALIVE_S > ALB_IDLE_TIMEOUT_S


@pytest.mark.parametrize("service", sorted(p.name for p in (ROOT / "services").iterdir()))
def test_each_api_passes_it_to_uvicorn(service: str) -> None:
    source = (ROOT / "services" / service / "app" / "__main__.py").read_text()
    assert "timeout_keep_alive=HTTP_KEEP_ALIVE_S" in source
