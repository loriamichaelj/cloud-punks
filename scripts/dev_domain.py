"""Check the dev domain and print the host names built from it.

    DEV_DOMAIN=example.com python3 scripts/dev_domain.py public     # dev.example.com
    DEV_DOMAIN=example.com python3 scripts/dev_domain.py internal   # internal.dev.example.com
    DEV_DOMAIN=example.com python3 scripts/dev_domain.py domain     # example.com

Used by the deploy and expose workflows on the in-VPC runner, which has only the system Python, so
this sticks to the standard library and syntax that Python 3.9 reads. The domain comes from the
environment (the `dev` environment variable DEV_DOMAIN), never an argument.

An empty or unset DEV_DOMAIN is not an error: it prints nothing and the workflows keep serving plain
HTTP, which is how dev ran before it had a domain. A set but malformed value fails, because it ends
up in a Helm argument and in DNS names.
"""

import os
import re
import sys

PREFIX = {"public": "dev.", "internal": "internal.dev.", "domain": ""}
LONGEST = 253  # a DNS name
LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
TLD = re.compile(r"^[a-z]{2,63}$")


def check(value):
    """The domain, lower-cased, or "" when unset; ValueError says what is wrong, never the value."""
    text = (value or "").strip().lower().rstrip(".")
    if not text:
        return ""
    labels = text.split(".")
    if len(labels) < 2:
        raise ValueError("the domain needs a name and a suffix, like example.com")
    if not all(LABEL.match(label) for label in labels):
        raise ValueError(
            "the domain has an empty label, an invalid character or a hyphen at an edge of a label"
        )
    if not TLD.match(labels[-1]):
        raise ValueError("the domain suffix must be letters only, like com")
    if len(PREFIX["internal"]) + len(text) > LONGEST:
        raise ValueError("the domain is too long to carry the host names built from it")
    return text


def host(kind, value):
    """The host name of one kind for this domain, or "" when no domain is set."""
    domain = check(value)
    return PREFIX[kind] + domain if domain else ""


def main(argv):
    if len(argv) != 2 or argv[1] not in PREFIX:
        sys.stderr.write("usage: dev_domain.py public|internal|domain\n")
        return 2
    try:
        out = host(argv[1], os.environ.get("DEV_DOMAIN", ""))
    except ValueError as exc:
        sys.stderr.write(f"DEV_DOMAIN: {exc}\n")
        return 1
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
