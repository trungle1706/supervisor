"""In-process fake streamable-HTTP MCP server (MOCK, WP26 test fixture).

Standard library only. It speaks enough of MCP streamable HTTP for the proxy tests and the
harness: ``initialize`` (answers with a session id), ``notifications/*`` (202), ``ping``,
``tools/list`` (optional pagination), ``tools/call`` (echo), HTTP DELETE of a session.
The tool list can be changed at any time (``set_tools``), which is how a rug pull is played.

Modes: ``sse=True`` answers every request as ``text/event-stream`` and sends one server
notification before the response. ``require_session=True`` refuses calls without the session
id (404, like a real server whose session expired). ``page_size`` splits ``tools/list``.
Everything labelled ``mock``: this is not an MCP server of any vendor.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

PROTOCOL = "2025-06-18"


class FakeMcpServer:
    is_mock = True

    def __init__(
        self,
        tools: list[dict[str, Any]] | None = None,
        *,
        sse: bool = False,
        require_session: bool = False,
        page_size: int | None = None,
        path: str = "/mcp",
        bearer: str | None = None,
    ) -> None:
        self.tools: list[dict[str, Any]] = list(tools or [])
        self.sse = sse
        self.require_session = require_session
        self.page_size = page_size
        self.path = path
        self.bearer = bearer
        self.calls: list[dict[str, Any]] = []  # tools/call params the server really executed
        self.requests: list[dict[str, Any]] = []  # every JSON-RPC message with its headers
        self.sessions: set[str] = set()
        self.connections = 0  # TCP connections accepted (keep-alive evidence)
        self._n = 0
        self._lock = threading.Lock()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self))
        self._httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ life cycle
    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}{self.path}"

    def start(self) -> FakeMcpServer:
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(2)

    def __enter__(self) -> FakeMcpServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def set_tools(self, tools: list[dict[str, Any]]) -> None:
        with self._lock:
            self.tools = list(tools)

    # ------------------------------------------------------------------ protocol
    def answer(self, msg: dict[str, Any], session: str | None) -> tuple[int, dict[str, Any] | None]:
        method = msg.get("method")
        id_ = msg.get("id")
        if "id" not in msg or method is None:
            return 202, None
        if method == "initialize":
            return 200, _ok(
                id_,
                {
                    "protocolVersion": PROTOCOL,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "fake-mcp (mock)", "version": "0"},
                },
            )
        if self.require_session and session not in self.sessions:
            return 404, _err(id_, -32001, "session not found")
        if method == "ping":
            return 200, _ok(id_, {})
        if method == "tools/list":
            with self._lock:
                tools = list(self.tools)
            cursor = (msg.get("params") or {}).get("cursor")
            start = int(cursor) if cursor else 0
            size = self.page_size or len(tools) or 1
            page = tools[start : start + size]
            result: dict[str, Any] = {"tools": page}
            if start + size < len(tools):
                result["nextCursor"] = str(start + size)
            return 200, _ok(id_, result)
        if method == "tools/call":
            params = msg.get("params") or {}
            with self._lock:
                self.calls.append(params)
            args = params.get("arguments") or {}
            return 200, _ok(
                id_,
                {
                    "content": [{"type": "text", "text": f"ok:{params.get('name')}"}],
                    "structuredContent": {"echo": args},
                    "isError": False,
                },
            )
        return 200, _err(id_, -32601, "method not found")

    def new_session(self) -> str:
        with self._lock:
            self._n += 1
            sid = f"fake-session-{self._n}"
            self.sessions.add(sid)
        return sid


def _ok(id_: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _err(id_: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _handler(srv: FakeMcpServer) -> type[BaseHTTPRequestHandler]:
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self) -> None:
            super().setup()
            with srv._lock:
                srv.connections += 1

        def log_message(self, fmt: str, *args: Any) -> None:
            pass

        def _auth_ok(self) -> bool:
            if srv.bearer is None:
                return True
            return self.headers.get("Authorization") == f"Bearer {srv.bearer}"

        def do_DELETE(self) -> None:  # noqa: N802
            sid = self.headers.get("Mcp-Session-Id", "")
            srv.sessions.discard(sid)
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            self.send_response(405)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            n = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(n)
            if not self._auth_ok():
                self.send_response(401)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            msg = json.loads(raw)
            session = self.headers.get("Mcp-Session-Id")
            with srv._lock:
                srv.requests.append({"message": msg, "headers": dict(self.headers.items())})
            status, body = srv.answer(msg, session)
            extra: dict[str, str] = {}
            if msg.get("method") == "initialize" and body and "result" in body:
                extra["Mcp-Session-Id"] = srv.new_session()
            if body is None:
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if srv.sse:
                note = {
                    "jsonrpc": "2.0",
                    "method": "notifications/message",
                    "params": {"data": "n"},
                }
                data = "".join(
                    f"event: message\ndata: {json.dumps(m, separators=(',', ':'))}\n\n"
                    for m in (note, body)
                ).encode()
                ctype = "text/event-stream"
            else:
                data = json.dumps(body, separators=(",", ":")).encode()
                ctype = "application/json"
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

    return H


# --------------------------------------------------------------------------- tool builders
def tool(
    name: str,
    description: str = "",
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
    annotations: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """A tool object as ``tools/list`` returns it."""
    schema: dict[str, Any] = {"type": "object", "properties": properties or {}}
    if required:
        schema["required"] = list(required)
    out: dict[str, Any] = {"name": name, "description": description, "inputSchema": schema}
    if annotations is not None:
        out["annotations"] = annotations
    out.update(extra)
    return out
