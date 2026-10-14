"""Console error responses. htmx drops 5xx responses (bank guide 0, rule 10), so a user error
on a console path is HTTP 400 with a small HTML message that ``static/console.js`` swaps
into ``#flash``; a full-page GET gets a minimal page with the same message."""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import HTMLResponse
from markupsafe import escape

from supervisor.console.routes import message_html

log = logging.getLogger("supervisor.console")


def is_console(request: Request) -> bool:
    return request.url.path.startswith("/console")


def console_error(request: Request, message: str, status_code: int = 400) -> HTMLResponse:
    partial = message_html(message)
    if request.headers.get("hx-request") == "true":
        return HTMLResponse(partial, status_code=status_code)
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        "<title>Supervisor console - error</title>"
        '<link rel="stylesheet" href="/console/static/console.css"></head><body><main>'
        f'<div id="flash">{partial}</div>'
        f'<p><a href="/console/">{escape("Back to the queue")}</a></p></main></body></html>'
    )
    return HTMLResponse(page, status_code=status_code)
