"""Write one service's OpenAPI spec to docs/openapi/<service>.json (DESIGN.md section 15.7).

Run once per service with that service on PYTHONPATH (every service's package is named ``app``):
``make openapi`` does this. The app is built with dummy settings and never connects to anything
(engines, pools and boto3 clients are lazy), so the spec comes from the code and cannot be
hand-edited out of sync. Output is stable (sorted keys, trailing newline). With
``--check`` nothing is written and the exit status is 1 when the committed snapshot differs
from what the code produces, which is how a stale snapshot fails ``make lint``.
"""

import json
import os
import sys
from pathlib import Path

DUMMY_ENV = {
    "ENVIRONMENT": "local",
    "AWS_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "test",
    "AWS_SECRET_ACCESS_KEY": "test",
    "DB_HOST": "127.0.0.1",
    "DB_PORT": "1",
    "DB_NAME": "spec",
    "DB_USER": "spec",
    "DB_PASSWORD": "not-a-real-password",
    "DB_SSLMODE": "disable",
    "CACHE_URL": "redis://127.0.0.1:1/0",
    "PRODUCT_SERVICE_URL": "http://product.invalid",
    "INVENTORY_SERVICE_URL": "http://inventory.invalid",
}


def main(service: str, out_dir: str, check: bool = False) -> int:
    for name, value in DUMMY_ENV.items():
        os.environ.setdefault(name, value)
    for name in list(os.environ):
        if name.startswith("AWS_ENDPOINT_URL"):
            del os.environ[name]

    from app.main import create_app  # the service's own package, found via PYTHONPATH

    spec = create_app().openapi()
    target = Path(out_dir) / f"{service}.json"
    text = json.dumps(spec, indent=2, sort_keys=True) + "\n"
    if check:
        if not target.exists() or target.read_text() != text:
            sys.stderr.write(f"stale: {target} (run `make openapi`)\n")
            return 1
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2], check="--check" in sys.argv[3:]))
