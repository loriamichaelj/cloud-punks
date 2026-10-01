import json
import os
from collections.abc import Callable
from typing import Any

import pytest

from retail_common.config import BaseServiceSettings
from retail_common.logging import configure_logging

ENV_VARS = (
    "SERVICE_NAME",
    "ENVIRONMENT",
    "LOG_LEVEL",
    "AWS_REGION",
    "HTTP_TIMEOUT_CONNECT_S",
    "HTTP_TIMEOUT_READ_S",
)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings must come from the test, never from the developer's shell."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    # moto-based tests must never reach LocalStack or a real account (see the service conftests).
    for name in list(os.environ):
        if name.startswith("AWS_ENDPOINT_URL") or name in {"AWS_PROFILE", "AWS_SESSION_TOKEN"}:
            monkeypatch.delenv(name)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def settings() -> BaseServiceSettings:
    return BaseServiceSettings(service_name="test-service", environment="test", log_level="INFO")


@pytest.fixture
def read_logs(capsys: pytest.CaptureFixture[str]) -> Callable[[], list[dict[str, Any]]]:
    """Configure JSON logging onto the captured stdout and return a parser for what was logged."""
    configure_logging("test-service", "test", "DEBUG")

    def read() -> list[dict[str, Any]]:
        lines = capsys.readouterr().out.splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    return read
