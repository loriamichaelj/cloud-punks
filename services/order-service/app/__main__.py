"""Process entrypoint: `python -m app <command>`.

One image, several processes (DESIGN.md section 10): ``api`` serves HTTP, ``relay`` publishes the
outbox, ``migrate`` applies Alembic migrations as the schema owner. ``consumer`` arrives in M6.
"""

import sys

import uvicorn

PORT = 8003


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "api"
    if command == "api":
        from app.main import create_app  # imported here so other commands stay cheap

        # log_config/access_log off: retail_common owns logging (shared JSON format).
        uvicorn.run(create_app(), host="0.0.0.0", port=PORT, log_config=None, access_log=False)  # noqa: S104
        return 0
    if command == "relay":
        from app.relay.main import main as relay_main

        return relay_main()
    if command == "migrate":
        from app.migrate import main as migrate_main

        return migrate_main()
    sys.stderr.write(f"unknown command: {command!r} (available: api, relay, migrate)\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
