"""Process entrypoint: `python -m app <command>`.

One image, two processes (DESIGN.md section 10): ``api`` serves the read API, ``consumer`` turns
events into notifications.
"""

import sys

import uvicorn

from retail_common.side_server import HTTP_KEEP_ALIVE_S

PORT = 8004


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "api"
    if command == "api":
        from app.main import create_app  # imported here so other commands stay cheap

        # log_config/access_log off: retail_common owns logging (shared JSON format).
        uvicorn.run(
            create_app(),
            host="0.0.0.0",  # noqa: S104
            port=PORT,
            log_config=None,
            access_log=False,
            timeout_keep_alive=HTTP_KEEP_ALIVE_S,
        )
        return 0
    if command == "consumer":
        from app.consumer.main import main as consumer_main

        return consumer_main()
    sys.stderr.write(f"unknown command: {command!r} (available: api, consumer)\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
