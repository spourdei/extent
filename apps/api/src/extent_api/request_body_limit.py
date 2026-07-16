"""Bound mutation request bodies before FastAPI allocates or validates JSON."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_MUTATION_BODY_BYTES = 16_384
_BODY_METHODS = {"PATCH", "POST", "PUT"}


class _InvalidContentLength(Exception):
    pass


class _LimitedReceive:
    def __init__(self, receive: Receive, *, maximum_bytes: int) -> None:
        self._maximum_bytes = maximum_bytes
        self._receive = receive
        self._received_bytes = 0
        self.exceeded = False

    async def __call__(self) -> Message:
        message = await self._receive()
        if message["type"] == "http.request":
            self._received_bytes += len(message.get("body", b""))
            if self._received_bytes > self._maximum_bytes:
                self.exceeded = True
                return {"type": "http.request", "body": b"", "more_body": False}
        return message


class MutationBodyLimitMiddleware:
    """Reject oversized declared or streamed mutation bodies with HTTP 413."""

    def __init__(self, app: ASGIApp, *, maximum_bytes: int) -> None:
        if maximum_bytes < 1:
            raise ValueError("maximum_bytes must be positive")
        self._app = app
        self._maximum_bytes = maximum_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _BODY_METHODS:
            await self._app(scope, receive, send)
            return
        try:
            declared_length = _content_length(scope)
        except _InvalidContentLength:
            await _invalid_content_length_response(scope, receive, send)
            return
        if declared_length is not None and declared_length > self._maximum_bytes:
            await _oversized_response(scope, receive, send)
            return
        limited_receive = _LimitedReceive(receive, maximum_bytes=self._maximum_bytes)

        async def send_unless_exceeded(message: Message) -> None:
            if not limited_receive.exceeded:
                await send(message)

        await self._app(scope, limited_receive, send_unless_exceeded)
        if limited_receive.exceeded:
            await _oversized_response(scope, receive, send)


def _content_length(scope: Scope) -> int | None:
    values = [value for name, value in scope["headers"] if name == b"content-length"]
    if not values:
        return None
    if len(values) != 1:
        raise _InvalidContentLength
    try:
        value = int(values[0].decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        raise _InvalidContentLength from None
    if value < 0:
        raise _InvalidContentLength
    return value


async def _invalid_content_length_response(scope: Scope, receive: Receive, send: Send) -> None:
    response = JSONResponse({"detail": "Invalid Content-Length header."}, status_code=400)
    await response(scope, receive, send)


async def _oversized_response(scope: Scope, receive: Receive, send: Send) -> None:
    response = JSONResponse(
        {"detail": "Request body exceeds the 16 KiB mutation limit."},
        status_code=413,
    )
    await response(scope, receive, send)
