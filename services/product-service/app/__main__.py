"""Process entrypoint: `python -m app <command>`. Commands are added per milestone."""

import importlib
import sys

import uvicorn

PORT = 8001
SEED_DIR = "/srv/seed"  # copied into the image by the Dockerfile


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "api"
    if command == "api":
        from app.main import app  # imported here so `python -m app unknown` stays cheap

        # log_config/access_log off: retail_common owns logging (shared JSON format).
        uvicorn.run(app, host="0.0.0.0", port=PORT, log_config=None, access_log=False)  # noqa: S104
        return 0
    if command == "seed":
        sys.path.insert(0, SEED_DIR)
        return int(importlib.import_module("seed").main())
    sys.stderr.write(f"unknown command: {command!r} (available: api, seed)\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
