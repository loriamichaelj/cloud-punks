"""Mark every inventory response ``Cache-Control: no-store``, errors included.

A header set inside a route does not reach responses built by exception handlers, and a cached
404 ("no such SKU") would outlive the SKU being created. Doing it in middleware covers all of them.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

NO_STORE = (b"cache-control", b"no-store")


class NoStoreMiddleware:
    def __init__(self, app: ASGIApp, prefix: str) -> None:
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(self.prefix):
            await self.app(scope, receive, send)
            return

        async def send_no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [h for h in message.get("headers", []) if h[0].lower() != NO_STORE[0]]
                message = {**message, "headers": [*headers, NO_STORE]}
            await send(message)

        await self.app(scope, receive, send_no_store)
