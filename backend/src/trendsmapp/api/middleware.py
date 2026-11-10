"""Request context, body limits, and response hardening headers.

The middleware stack is ordered so that a request is identified before it is
inspected, an oversized body is rejected before it is parsed, and every
response carries the correlation identifier and the hardening headers.
"""

from __future__ import annotations

import json
import re
import time
from contextvars import ContextVar, Token
from typing import Any
from uuid import uuid4

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from trendsmapp.logging_config import bind_request_context, clear_context

__all__ = [
    "BodyLimitMiddleware",
    "RequestContextMiddleware",
    "SecurityHeadersMiddleware",
    "current_request_id",
    "request_id_context",
]

request_id_context: ContextVar[str | None] = ContextVar("trendsmapp_request_id", default=None)

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

#: ASGI message type that opens a response (referenced by every send wrapper).
HTTP_RESPONSE_START = "http.response.start"

SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-site",
}


def current_request_id() -> str | None:
    """Return the identifier of the request currently being handled."""
    return request_id_context.get()


def _error_body(code: str, message: str, details: dict[str, Any]) -> bytes:
    payload = {
        "error": {"code": code, "message": message, "details": details},
        "request_id": current_request_id(),
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


async def _send_error(
    send: Send,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    body = _error_body(code, message, details or {})
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    await send({"type": HTTP_RESPONSE_START, "status": status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class RequestContextMiddleware:
    """Assign a correlation identifier to every request and response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        supplied = headers.get("x-request-id", "").strip()
        request_id = supplied if _REQUEST_ID_PATTERN.fullmatch(supplied) else uuid4().hex
        token: Token[str | None] = request_id_context.set(request_id)
        bind_request_context(request_id)
        started_at = time.perf_counter()

        async def send_with_context(message: Message) -> None:
            if message["type"] == HTTP_RESPONSE_START:
                elapsed_ms = (time.perf_counter() - started_at) * 1000.0
                response_headers = [
                    (key.lower(), value) for key, value in message.get("headers", [])
                ]
                existing = {key for key, _ in response_headers}
                if b"x-request-id" not in existing:
                    response_headers.append((b"x-request-id", request_id.encode("ascii")))
                if b"x-response-time-ms" not in existing:
                    response_headers.append(
                        (b"x-response-time-ms", f"{elapsed_ms:.3f}".encode("ascii"))
                    )
                message = dict(message)
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        finally:
            request_id_context.reset(token)
            clear_context()


class BodyLimitMiddleware:
    """Reject request bodies larger than the configured ceiling.

    A declared ``Content-Length`` above the limit is rejected without reading
    the body. A streamed body is cut off as soon as the running total passes
    the limit, so an oversized upload never reaches a route handler.
    """

    def __init__(self, app: ASGIApp, *, maximum_bytes: int) -> None:
        self.app = app
        self.maximum_bytes = maximum_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = Headers(scope=scope).get("content-length")
        if declared is not None:
            try:
                declared_length = int(declared)
            except ValueError:
                declared_length = None
            if declared_length is not None and declared_length > self.maximum_bytes:
                await _send_error(
                    send,
                    status_code=413,
                    code="resource_limit_exceeded",
                    message=f"The request body exceeds the {self.maximum_bytes}-byte limit.",
                    details={"limit_bytes": self.maximum_bytes, "declared_bytes": declared_length},
                )
                return

        consumed = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.maximum_bytes:
                    raise _BodyTooLargeError(consumed)
            return message

        async def limited_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == HTTP_RESPONSE_START:
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except _BodyTooLargeError:
            if response_started:
                raise
            await _send_error(
                send,
                status_code=413,
                code="resource_limit_exceeded",
                message=f"The request body exceeds the {self.maximum_bytes}-byte limit.",
                details={"limit_bytes": self.maximum_bytes},
            )


class _BodyTooLargeError(Exception):
    """Internal signal that a streamed body exceeded the limit."""


class SecurityHeadersMiddleware:
    """Attach hardening headers to every response."""

    def __init__(self, app: ASGIApp, headers: dict[str, str] | None = None) -> None:
        self.app = app
        self.headers = tuple(
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in (headers or SECURITY_HEADERS).items()
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == HTTP_RESPONSE_START:
                response_headers = [
                    (key.lower(), value) for key, value in message.get("headers", [])
                ]
                existing = {key for key, _ in response_headers}
                for name, value in self.headers:
                    if name not in existing:
                        response_headers.append((name, value))
                message = dict(message)
                message["headers"] = response_headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
