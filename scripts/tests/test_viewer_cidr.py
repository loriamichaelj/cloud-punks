"""scripts/viewer_cidr.py: the rule that keeps the public dev storefront from opening to everyone."""

import subprocess
import sys
from pathlib import Path

import pytest
import viewer_cidr

SCRIPT = Path(viewer_cidr.__file__)
SECRET = "8.8.8.8/32"  # any public address will do: this is test data


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("8.8.8.8/32", "8.8.8.8/32"),
        ("  8.8.8.8/32\n", "8.8.8.8/32"),  # a pasted secret often carries whitespace
        ("8.8.8.8", "8.8.8.8/32"),  # what an IP-lookup page prints: one address
        ("8.8.8.0/24", "8.8.8.0/24"),  # the widest allowed
        ("8.8.8.128/25", "8.8.8.128/25"),
    ],
)
def test_a_single_public_address_or_a_small_public_network_is_allowed(
    value: str, expected: str
) -> None:
    assert viewer_cidr.check(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "0.0.0.0/0",  # the whole internet
        "0.0.0.0/1",
        "8.8.0.0/16",
        "8.8.8.0/23",  # one bit too wide
        "128.0.0.0/8",
    ],
)
def test_a_range_wider_than_a_24_is_refused(value: str) -> None:
    with pytest.raises(ValueError, match="wider than"):
        viewer_cidr.check(value)


@pytest.mark.parametrize(
    "value", ["10.1.2.3/32", "192.168.1.10/32", "172.16.0.1/32", "127.0.0.1/32", "169.254.1.1/32"]
)
def test_private_and_loopback_addresses_are_refused(value: str) -> None:
    with pytest.raises(ValueError, match="private"):
        viewer_cidr.check(value)


@pytest.mark.parametrize("value", ["", "   ", "not-an-address", "8.8.8.8/33", "8.8.8/32"])
def test_anything_that_is_not_an_ipv4_cidr_is_refused(value: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - the message differs per case
        viewer_cidr.check(value)


def test_an_address_with_host_bits_set_is_refused_with_a_hint() -> None:
    with pytest.raises(ValueError, match="host bits"):
        viewer_cidr.check("8.8.8.8/24")


def test_ipv6_is_refused() -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        viewer_cidr.check("2001:db8::1/128")


def run_script(value: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT)],
        env={"VIEWER_CIDR": value},
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_script_prints_the_normalised_value_and_exits_zero() -> None:
    done = run_script(SECRET)

    assert (done.returncode, done.stdout.strip(), done.stderr) == (0, SECRET, "")


@pytest.mark.parametrize("value", ["0.0.0.0/0", "8.8.0.0/16", "10.0.0.1/32", "garbage"])
def test_the_script_exits_nonzero_and_never_repeats_the_value(value: str) -> None:
    done = run_script(value)

    assert done.returncode == 1
    assert done.stdout == ""
    assert value not in done.stderr
    assert "DEV_VIEWER_CIDR" in done.stderr


def test_a_missing_variable_is_refused() -> None:
    done = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT)], env={}, capture_output=True, text=True, check=False
    )

    assert done.returncode == 1
