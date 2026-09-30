"""Process entrypoint: `python -m app <command>`. Commands are added per milestone."""

import sys

import uvicorn

PORT = 8003


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "api"
    if command == "api":
        uvicorn.run("app.main:app", host="0.0.0.0", port=PORT)  # noqa: S104 - container bind
        return 0
    sys.stderr.write(f"unknown command: {command!r} (available: api)\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
