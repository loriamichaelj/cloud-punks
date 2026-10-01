"""Unit tests must be hermetic: they may never reach real AWS or a local emulator.

botocore honours ``AWS_ENDPOINT_URL`` and the default credential chain, so a shell that exports
them (or an integration conftest in the same process) would make moto-based tests talk to
LocalStack, or worse. Strip everything and give them dummy credentials.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _hermetic_aws_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("AWS_ENDPOINT_URL") or name in {"AWS_PROFILE", "AWS_SESSION_TOKEN"}:
            monkeypatch.delenv(name)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
