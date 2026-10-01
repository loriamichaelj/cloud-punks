"""A small HTTP server in a background thread, for processes that are not web services.

Consumers and the outbox relay have no API, but Kubernetes probes them the same way as the APIs:
``/health/live``, ``/health/ready`` and ``/metrics`` on port 9000 (DESIGN.md section 8). Build the
app with ``create_service_app`` and run it here while the main thread does the real work.
"""

import threading
import time

import uvicorn
from fastapi import FastAPI

DEFAULT_PORT = 9000

# How long an idle HTTP connection stays open. uvicorn's default is 5 s, which loses a race with
# any proxy that reuses connections: the proxy sends a request on a connection the server has just
# closed and the caller gets a 502 or a hung request although nothing was wrong (seen with Traefik
# on the local cluster). It must exceed the proxy's idle timeout; the ALB's is 60 s.
HTTP_KEEP_ALIVE_S = 75


class SideServer:
    def __init__(self, app: FastAPI, *, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:  # noqa: S104
        # log_config/access_log off: retail_common owns logging (shared JSON format).
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_config=None,
            access_log=False,
            timeout_keep_alive=HTTP_KEEP_ALIVE_S,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="side-server", daemon=True)

    def start(self, timeout_s: float = 10.0) -> None:
        self._thread.start()
        deadline = time.monotonic() + timeout_s
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("side server failed to start")
            time.sleep(0.01)

    @property
    def port(self) -> int:
        """The bound port (useful when started with port 0)."""
        port: int = self._server.servers[0].sockets[0].getsockname()[1]
        return port

    def stop(self, timeout_s: float = 10.0) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=timeout_s)
