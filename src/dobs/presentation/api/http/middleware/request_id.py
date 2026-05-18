from __future__ import annotations

import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dobs.main.logging_setup import request_id_ctx

HEADER = "X-Request-ID"
HEADER_BYTES = HEADER.lower().encode("latin-1")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = next(
            (v.decode("latin-1") for k, v in scope.get("headers", []) if k == HEADER_BYTES),
            None,
        )
        rid = incoming or uuid.uuid4().hex
        token = request_id_ctx.set(rid)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((HEADER_BYTES, rid.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            request_id_ctx.reset(token)
