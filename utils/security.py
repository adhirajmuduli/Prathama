from __future__ import annotations

import asyncio
import base64
import binascii
import json
import secrets

from fastapi import HTTPException, Request
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from config import settings

CHALLENGE_HEADER_VALUE = 'Basic realm="trendsmapp", Bearer'

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' blob:; "
        "worker-src 'self' blob:; "
        "child-src blob:; "
        "style-src 'self'; "
        "img-src 'self' data: blob:; "
        "media-src 'self' blob:; "
        "connect-src 'self' data: blob:; "
        "font-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

class SecurityHeadersMiddleware:
    """Attach hardening headers to every HTTP response, including static mounts and errors."""

    def __init__(self, app: ASGIApp, headers: dict[str, str] | None = None) -> None:
        self.app = app
        self.headers = tuple(
            (name.lower().encode("ascii"), value.encode("latin-1"))
            for name, value in (headers or SECURITY_HEADERS).items()
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = [(key.lower(), value) for key, value in message.get("headers", [])]
                existing = {key for key, _ in response_headers}
                for name, value in self.headers:
                    if name not in existing:
                        response_headers.append((name, value))
                message = dict(message)
                message["headers"] = response_headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestBodyTooLarge(Exception):
    """Raised when a request body surpasses the middleware limit."""


def _constant_time_match(candidate: str) -> bool:
    try:
        return secrets.compare_digest(candidate.encode("utf-8"), settings.auth_token.encode("utf-8"))
    except Exception:
        return False


def _is_authorized(headers: Headers) -> bool:
    if not settings.auth_token:
        return True
    presented: list[str] = []
    authorization = headers.get("authorization")
    if authorization:
        scheme, separator, value = authorization.partition(" ")
        scheme = scheme.lower()
        value = value.strip()
        if separator and value:
            if scheme == "bearer":
                presented.append(value)
            elif scheme == "basic":
                try:
                    decoded = base64.b64decode(value, validate=True).decode("utf-8")
                except (binascii.Error, UnicodeDecodeError, ValueError):
                    return False
                username, credential_separator, password = decoded.partition(":")
                if not credential_separator:
                    return False
                del username  # any username is accepted; the password carries the shared secret
                presented.append(password)
    alternate = headers.get("x-trendsmapp-token", "").strip()
    if alternate:
        presented.append(alternate)
    expected = settings.auth_token.encode("utf-8")
    return any(secrets.compare_digest(candidate.encode("utf-8"), expected) for candidate in presented)


async def require_auth(request: Request) -> None:
    """FastAPI dependency enforcing the shared-secret contract when a token is configured."""
    if _is_authorized(request.headers):
        return
    raise HTTPException(status_code=401, detail="Authentication required.")


def _path_is_protected(path: str, protected_prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in protected_prefixes)


async def _send_json_error(send: Send, status_code: int, message: str, challenge: bool = False) -> None:
    body = json.dumps({"error": message}).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    if challenge:
        headers.append((b"www-authenticate", CHALLENGE_HEADER_VALUE.encode("ascii")))
    await send({"type": "http.response.start", "status": status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class AuthPathMiddleware:
    """Enforce the token contract on raw ASGI paths that bypass routing, e.g. static mounts."""

    def __init__(self, app: ASGIApp, protected_prefixes: tuple[str, ...] = ()) -> None:
        self.app = app
        self.protected_prefixes = protected_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            if _path_is_protected(path, self.protected_prefixes) and not _is_authorized(Headers(scope=scope)):
                await _send_json_error(send, 401, "Authentication required.", challenge=True)
                return
        await self.app(scope, receive, send)


class BodyLimitMiddleware:
    """Reject request bodies larger than ``maximum_bytes`` before they are buffered.

    Declared Content-Length headers are rejected immediately; streamed or
    chunked bodies are cut off as soon as the running total exceeds the limit.
    """

    def __init__(self, app: ASGIApp, maximum_bytes: int) -> None:
        self.app = app
        self.maximum_bytes = maximum_bytes
        self._message = f"The request body exceeds the {maximum_bytes}-byte limit."

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        content_length = Headers(scope=scope).get("content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = None
            if declared is not None and declared > self.maximum_bytes:
                await _send_json_error(send, 413, self._message)
                return

        consumed = 0
        response_started = False
        # 30-second idle timeout for receiving request body
        RECEIVE_TIMEOUT = 30.0

        async def limited_receive() -> Message:
            nonlocal consumed
            try:
                message = await asyncio.wait_for(receive(), timeout=RECEIVE_TIMEOUT)
            except asyncio.TimeoutError:
                raise RequestBodyTooLarge("Request body timed out during upload.") from None
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.maximum_bytes:
                    raise RequestBodyTooLarge(self._message)
            return message

        async def limited_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except RequestBodyTooLarge:
            if response_started:
                raise
            await _send_json_error(send, 413, self._message)
