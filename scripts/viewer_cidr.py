"""Check the address allowed to reach the public dev storefront, and print it normalised.

    VIEWER_CIDR=203.0.113.7/32 python3 scripts/viewer_cidr.py

Used by the "App: expose" workflow on the in-VPC runner, which has only the system Python, so
this sticks to the standard library and syntax that Python 3.9 reads. The value comes from the
environment, never an argument (an argument shows in the process list), and no message below
repeats it: it is a masked secret.

An internet-facing load balancer with a wide allow-list is a public service with no login, so the
rule is strict: one IPv4 network, a public one, no wider than a /24. A bare address means a /32.
"""

import ipaddress
import os
import sys

MIN_PREFIX = 24  # a /24 is 256 addresses: the most we will open to


def check(value):
    """The normalised CIDR, or raise ValueError saying what is wrong (never the value)."""
    text = (value or "").strip()
    if not text:
        raise ValueError("the viewer address is empty")
    try:
        network = ipaddress.ip_network(text, strict=True)
    except ValueError as exc:
        # The library's message can quote the input, so say our own.
        if "host bits" in str(exc):
            raise ValueError("the address has host bits set (use a /32 for one address)") from None
        raise ValueError("the viewer address is not an IPv4 CIDR like 203.0.113.7/32") from None
    if network.version != 4:
        raise ValueError("only IPv4 is supported")
    if network.prefixlen < MIN_PREFIX:
        raise ValueError(f"the range is wider than a /{MIN_PREFIX}: refusing to open it")
    if not network.is_global:
        raise ValueError("the address is private, loopback or reserved: use your public address")
    return str(network)


def main():
    try:
        print(check(os.environ.get("VIEWER_CIDR", "")))
    except ValueError as exc:
        sys.stderr.write(f"DEV_VIEWER_CIDR: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
