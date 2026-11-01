"""htmx answer helpers shared by the console routes (audit D6)."""

from __future__ import annotations

from markupsafe import escape
from starlette.responses import Response


def message_html(message: str, *, ok: bool = False, oob: bool = False) -> str:
    """The #flash partial (also used by the app-level 400 handler)."""
    cls = "msg-ok" if ok else "msg-error"
    role = "status" if ok else "alert"
    inner = f'<div class="msg {cls}" role="{role}">{escape(message)}</div>'
    if oob:
        return f'<div id="flash" hx-swap-oob="true">{inner}</div>'
    return inner


def append_message(resp: Response, message: str, *, ok: bool = True) -> Response:
    """Add the #flash partial to the end of an htmx fragment (out-of-band swap) and fix the
    content-length. Returns ``resp``."""
    resp.body = bytes(resp.body) + message_html(message, ok=ok, oob=True).encode()
    resp.headers["content-length"] = str(len(resp.body))
    return resp
