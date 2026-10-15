"""Pure ASGI middlewares (WP18): request id, security headers, body size limit, rate limit.

Pure ASGI (not BaseHTTPMiddleware) so streaming responses and request bodies are not
buffered. ``install(app, settings)`` registers them; order, outermost first:
request id -> security headers -> body limit -> rate limit.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from supervisor.ops.logging_setup import begin_request, end_request

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'self'; object-src 'none'"
)
HSTS = "max-age=31536000; includeSubDomains"
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Agent ingress is governed by the gateway (fail mode, budgets), not by a human rate limit:
# throttling it here would turn a busy agent into a gate outage.
RATE_LIMIT_EXEMPT = frozenset({"/gate/check", "/v1/traces"})


def _reject(scope: Scope, message: str, status: int, headers: dict[str, str] | None = None):
    """A 4xx answer: console HTML partial on /console paths, JSON elsewhere."""
    path = scope.get("path", "")
    response: Response
    if path.startswith("/console"):
        from supervisor.console.errors import console_error

        response = console_error(Request(scope), message, status_code=status)
    else:
        response = JSONResponse({"error": message}, status_code=status)
    for k, v in (headers or {}).items():
        response.headers[k] = v
    return response


class RequestIdMiddleware:
    def __init__(self, app: Any, header: str = "X-Request-ID") -> None:
        self.app = app
        self.header = header
        self._raw = header.lower().encode("latin-1")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        rid = ""
        for k, v in scope.get("headers", []):
            if k == self._raw:
                cand = v.decode("latin-1")
                if REQUEST_ID_RE.match(cand):
                    rid = cand
                break
        rid = rid or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid
        token = begin_request(rid)

        async def send_with_id(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k != self._raw]
                headers.append((self._raw, rid.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            end_request(token)


class SecurityHeadersMiddleware:
    def __init__(self, app: Any, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        console_page = path.startswith("/console") and not path.startswith("/console/static")

        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}

                def add(name: bytes, value: str) -> None:
                    if name not in present:
                        headers.append((name, value.encode("latin-1")))

                add(b"content-security-policy", CSP)
                add(b"x-frame-options", "DENY")
                add(b"x-content-type-options", "nosniff")
                add(b"referrer-policy", "no-referrer")
                if self.hsts:
                    add(b"strict-transport-security", HSTS)
                if console_page:
                    add(b"cache-control", "no-store")
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class _TooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """413 above ``limit`` bytes: by Content-Length, and by counting streamed bytes."""

    def __init__(self, app: Any, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.limit <= 0:
            await self.app(scope, receive, send)
            return
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                if v.isdigit() and int(v) > self.limit:
                    await self._too_large(scope, receive, send)
                    return
                break
        seen = 0
        started = False

        async def counting_receive() -> MutableMapping[str, Any]:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.limit:
                    raise _TooLarge
            return message

        async def tracking_send(message: MutableMapping[str, Any]) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _TooLarge:
            if started:
                raise
            await self._too_large(scope, receive, send)

    async def _too_large(self, scope: Scope, receive: Receive, send: Send) -> None:
        mb = self.limit / 1_000_000
        msg = f"request body is too large (limit {mb:g} MB)"
        await _reject(scope, msg, 413)(scope, receive, send)


class TokenBuckets:
    """Thread-safe token buckets with bounded memory (oldest keys evicted)."""

    def __init__(
        self,
        per_minute: int,
        burst: int,
        *,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rate = per_minute / 60.0
        self.burst = float(burst)
        self.max_keys = max_keys
        self.clock = clock
        self._lock = threading.Lock()
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def take(self, key: str) -> float:
        """0.0 when allowed, else seconds until a token is available."""
        now = self.clock()
        with self._lock:
            tokens, last = self._buckets.pop(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens >= 1.0:
                tokens -= 1.0
                wait = 0.0
            else:
                wait = (1.0 - tokens) / self.rate
            self._buckets[key] = (tokens, now)  # most recently used goes last
            while len(self._buckets) > self.max_keys:
                self._buckets.popitem(last=False)
            return wait

    def __len__(self) -> int:
        return len(self._buckets)


def _principal_key(scope: Scope) -> str:
    headers = {k: v for k, v in scope.get("headers", [])}
    email = headers.get(b"x-forwarded-email", b"").decode("latin-1").strip()
    if email:
        return "u:" + email.lower()
    dev = headers.get(b"x-dev-user", b"").decode("latin-1").strip()
    if not dev:
        for part in headers.get(b"cookie", b"").decode("latin-1").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "sv_dev_user" and value:
                dev = value
                break
    if dev:
        return "u:" + dev.lower()
    client = scope.get("client")
    return "ip:" + (client[0] if client else "unknown")


class RateLimitMiddleware:
    def __init__(self, app: Any, per_minute: int, burst: int) -> None:
        self.app = app
        self.buckets = TokenBuckets(per_minute, burst)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") not in MUTATING
            or scope.get("path", "") in RATE_LIMIT_EXEMPT
        ):
            await self.app(scope, receive, send)
            return
        wait = self.buckets.take(_principal_key(scope))
        if wait > 0:
            retry = str(max(1, int(wait) + 1))
            response = _reject(
                scope,
                f"too many requests; try again in {retry} seconds",
                429,
                {"Retry-After": retry},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def install(app: Any, settings: Any) -> None:
    """Register the middlewares on a FastAPI/Starlette app (last added = outermost)."""
    if settings.rate_limit_enabled:
        app.add_middleware(
            RateLimitMiddleware,
            per_minute=settings.rate_limit_per_minute,
            burst=settings.rate_limit_burst,
        )
    if settings.max_request_bytes > 0:
        app.add_middleware(BodyLimitMiddleware, limit=settings.max_request_bytes)
    if settings.security_headers_enabled:
        app.add_middleware(SecurityHeadersMiddleware, hsts=settings.hsts_enabled)
    app.add_middleware(RequestIdMiddleware, header=settings.request_id_header)


__all__ = [
    "CSP",
    "BodyLimitMiddleware",
    "RateLimitMiddleware",
    "RequestIdMiddleware",
    "SecurityHeadersMiddleware",
    "TokenBuckets",
    "install",
]
