"""scripts/dev_domain.py: what the deploy workflows will accept as the dev domain."""

import os
import subprocess
import sys
from pathlib import Path

import dev_domain
import pytest

SCRIPT = Path(dev_domain.__file__)


def run(kind: str, domain: str | None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "DEV_DOMAIN"}
    if domain is not None:
        env["DEV_DOMAIN"] = domain
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), kind], env=env, capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("public", "dev.example.com"),
        ("internal", "internal.dev.example.com"),
        ("domain", "example.com"),
    ],
)
def test_the_host_names_are_built_from_the_domain(kind: str, expected: str) -> None:
    result = run(kind, "example.com")
    assert (result.returncode, result.stdout.strip()) == (0, expected)


def test_a_pasted_value_is_normalised() -> None:
    assert dev_domain.check("  Example.COM.\n") == "example.com"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_no_domain_means_plain_http_not_an_error(value: str | None) -> None:
    result = run("public", value)
    assert (result.returncode, result.stdout) == (0, "")


@pytest.mark.parametrize(
    "value",
    [
        "localhost",  # no suffix
        "example..com",  # empty label
        "-example.com",
        "example-.com",
        "exa mple.com",
        "example.com;rm -rf /",  # it ends up in a shell variable and a Helm argument
        "$(id).example.com",
        "example.c0m",  # the suffix is letters only
        "a" * 64 + ".com",  # a label is at most 63
        "a." * 130 + "com",  # too long once the host prefix is added
    ],
)
def test_a_malformed_domain_fails_without_repeating_it(value: str) -> None:
    result = run("public", value)
    assert result.returncode == 1
    assert result.stdout == ""
    assert value.strip() not in result.stderr


def test_an_unknown_kind_is_a_usage_error() -> None:
    assert run("other", "example.com").returncode == 2
