"""WP-P4: request-scoped carrier for the signed-in user's forwarded token (sandbox-only).

A ``ContextVar`` set by ``UserTokenMiddleware`` from ``X-Forwarded-Access-Token`` for one
HTTP request and reset when the request ends. It is read by the judge client only when
``LLM_USER_TOKEN_FORWARD=1``. Never stored, never logged, never in the evidence chain.

Trust: the header is trusted only behind the Apps proxy; a spoofed header only lets a caller
run the judge under its own token.

Reach: the value follows the request into ``async`` code, into sync endpoints (run by the
framework in a worker thread with a copied context) and into ``asyncio.to_thread``. It does
NOT follow a plain ``ThreadPoolExecutor.submit`` or a task that outlives the response: those
see ``None`` and the judge falls back to the App service principal.
"""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from supervisor.adapters.auth.base import UserToken

TOKEN_HEADER_BYTES = b"x-forwarded-access-token"  # noqa: S105 - a header name, not a secret

_current: ContextVar[UserToken | None] = ContextVar("supervisor_forwarded_user_token", default=None)


def current_forwarded_token() -> UserToken | None:
    """The forwarded user token of the request being served, or None."""
    return _current.get()


@contextmanager
def forwarded_token(token: UserToken | None) -> Iterator[None]:
    marker = _current.set(token)
    try:
        yield
    finally:
        _current.reset(marker)


@contextmanager
def without_forwarded_token() -> Iterator[None]:
    """WP-P5: run a block as the App service principal even inside a request that carries a
    user token (runtime build: policy deploy, chain-writer init). Restored in finally."""
    with forwarded_token(None):
        yield


class UserTokenMiddleware:
    """Pure ASGI middleware: expose the forwarded token to code running inside the request."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        raw = ""
        for name, value in scope.get("headers", []):
            if name == TOKEN_HEADER_BYTES:
                raw = value.decode("latin-1").strip()
                break
        with forwarded_token(UserToken(raw) if raw else None):
            await self.app(scope, receive, send)
