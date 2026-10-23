"""WP-P5 (sandbox-only): while the console runs degraded (SQL_USER_TOKEN_FORWARD on and the
App service principal could not build the runtime), every write request answers HTTP 400 and
writes nothing. A write would otherwise change state with no evidence-chain entry."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from supervisor.console.errors import console_error, is_console

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
EXEMPT_PREFIXES = ("/healthz", "/readyz", "/static")
MESSAGE = (
    "gateway unavailable: the App service principal has no SQL grant yet; "
    "writes are disabled until then"
)


class DegradedWriteGuard:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] in READ_METHODS
            or scope["path"].startswith(EXEMPT_PREFIXES)
        ):
            await self.app(scope, receive, send)
            return
        from supervisor.console.context import get_context

        try:
            ctx = await run_in_threadpool(get_context)
            degraded = bool(ctx.degraded_until)
        except Exception:  # noqa: BLE001 - the route reports its own error
            degraded = False
        if not degraded:
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        if is_console(request):
            response: Any = console_error(request, MESSAGE)
        else:
            response = JSONResponse(status_code=400, content={"error": MESSAGE})
        await response(scope, receive, send)
