"""HTTP MCP gateway with tool locking (WP26, ADR D24, docs/mcp-gateway.md).

A streamable-HTTP MCP proxy for REMOTE MCP servers. One listener per application: the agent
points its MCP client at ``http://127.0.0.1:<port>/mcp``; the proxy forwards to the upstream
server and puts the same deterministic gate in front of it as the stdio proxy
(``mcp_proxy.McpGateProxy``): same decision path, same evidence, same ingress signing, same
transformed arguments. On top of that it LOCKS the tool list::

    initialize / tools/list --> hash every tool, compare with the locked manifest
                                new or changed tool: hidden from the agent, and a tools/call
                                on it is refused with rule MCP-TOOL-UNREVIEWED until two
                                different people approve it (case type mcp_tool_review)
    tools/call -------------> lock check, then the gate (rule engine), then the upstream server

Run (needs MCP_HTTP_ENABLED=1; the process refuses to start otherwise)::

    python -m supervisor.gateway.mcp_http --upstream https://mcp.bank.example/mcp \\
        --agent credit-agent --listen 127.0.0.1:9701 --gate-url http://127.0.0.1:8000 \\
        --key-file agent.key [--trust-on-first-use --by alice]

Review (the app must be stopped, or pass --supervisor-url to use the routes)::

    python -m supervisor.gateway.mcp_http tools list [SERVER]
    python -m supervisor.gateway.mcp_http tools diff SERVER TOOL
    python -m supervisor.gateway.mcp_http tools propose|approve SERVER TOOL --by USER --hash H

CLI output is ASCII. Standard library only here; httpx lives in ``adapters/mcp_upstream.py``.
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import random
import re
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol
from urllib.parse import urlsplit

from supervisor.core.ports import GateHook
from supervisor.gateway import mcp_lock
from supervisor.gateway.mcp_proxy import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    PARSE_ERROR,
    McpGateProxy,
    deny_response,
    make_credential,
)

log = logging.getLogger("supervisor.mcp_http")

RULE_UNREVIEWED = "MCP-TOOL-UNREVIEWED"
RULE_LOCK_UNAVAILABLE = "MCP-LOCK-UNAVAILABLE"
MAX_BODY = 4 * 1024 * 1024
MAX_PAGES = 50
FREE_PORTS = (20000, 29999)
DEFAULT_PATH = "/mcp"
DEFAULT_AGENT_VERSION = "mcp-http-1"
TOFU_WARNING = (
    "[WARN] --trust-on-first-use: every tool the upstream server lists NOW is locked as "
    "approved without a second reviewer. Run it once, on a server you trust at this moment, "
    "and record the review elsewhere. It is ignored when the server is already known."
)
_SLUG = re.compile(r"[^A-Za-z0-9_.:@-]+")


def server_id_for_url(url: str) -> str:
    """Stable id of an upstream server from its URL: ``host[:port]_path`` with no scheme,
    credentials, query or fragment (safe to store and to show)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port else ""
    path = parts.path.strip("/").replace("/", "_")
    sid = _SLUG.sub("-", f"{host}{port}" + (f"_{path}" if path else ""))
    return sid[:128] or "mcp-server"


# ---------------------------------------------------------------------------------- lock clients
class LockClient(Protocol):
    def observe(
        self,
        server_id: str,
        agent_id: str,
        tools: list[dict[str, Any]],
        tofu_by: str | None = None,
    ) -> dict[str, Any]: ...

    def report_block(self, server_id: str, tool: str, agent_id: str, rule_id: str) -> None: ...


class LocalLockClient:
    """The lock service in the same process (tests, harness, a proxy next to the database)."""

    def __init__(self, service: Any) -> None:
        self.service = service

    def observe(
        self,
        server_id: str,
        agent_id: str,
        tools: list[dict[str, Any]],
        tofu_by: str | None = None,
    ) -> dict[str, Any]:
        return self.service.observe(server_id, agent_id, tools, tofu_by=tofu_by)  # type: ignore[no-any-return]

    def report_block(self, server_id: str, tool: str, agent_id: str, rule_id: str) -> None:
        self.service.report_block(server_id, tool, agent_id, rule_id)


class HttpLockClient:
    """The lock service behind ``/v1/mcp/tools/observe`` and ``/blocked`` of the Supervisor app,
    signed like a gate call (WP20) when a credential is given."""

    def __init__(
        self, base_url: str, credential: Any = None, timeout_s: float = 10.0, transport: Any = None
    ) -> None:
        base = base_url.rstrip("/")
        self.base = base[:-3] if base.endswith("/v1") else base
        self.credential = credential
        self.timeout_s = timeout_s
        self._transport = transport

    def _post(self, path: str, payload: dict[str, Any]) -> Mapping[str, Any]:
        url = f"{self.base}{path}"
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode()
        headers = {"Content-Type": "application/json"}
        if self.credential is not None:
            headers.update(self.credential.headers_for("POST", urlsplit(url).path, body))
        if self._transport is not None:
            return self._transport(url, body, headers, self.timeout_s)  # type: ignore[no-any-return]
        from supervisor.gateway.sdk import _default_signed_transport

        return _default_signed_transport(url, body, headers, self.timeout_s)

    def observe(
        self,
        server_id: str,
        agent_id: str,
        tools: list[dict[str, Any]],
        tofu_by: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"agent_id": agent_id, "server_id": server_id, "tools": tools}
        if tofu_by:
            payload["trust_on_first_use_by"] = tofu_by
        return dict(self._post("/v1/mcp/tools/observe", payload))

    def report_block(self, server_id: str, tool: str, agent_id: str, rule_id: str) -> None:
        self._post(
            "/v1/mcp/tools/blocked",
            {"agent_id": agent_id, "server_id": server_id, "tool": tool, "rule_id": rule_id},
        )


# ---------------------------------------------------------------------------------- the proxy
class LockUnavailable(Exception):
    """The lock view cannot be built (upstream or lock service down): fail closed."""


def _err(id_: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


class McpHttpGateProxy(McpGateProxy):
    """``McpGateProxy`` plus the tool lock. The gate path of a ``tools/call`` is inherited
    unchanged; the lock runs before it."""

    def __init__(
        self,
        gate: GateHook,
        agent_id: str,
        agent_version: str,
        upstream: Any,
        *,
        server_id: str,
        lock: LockClient | None = None,
        refresh_s: float = 60.0,
        tofu_by: str | None = None,
        inline_redaction: bool | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(gate, agent_id, agent_version, upstream, inline_redaction=inline_redaction)
        self.server_id = server_id
        self._lock_client = lock
        self._refresh_s = refresh_s
        self._tofu_by = tofu_by
        self._mono = monotonic
        self._view: dict[str, Any] | None = None
        self._view_at = 0.0
        self._refresh_lock = threading.Lock()
        self._seq = 0

    # ------------------------------------------------------------------ helpers
    @property
    def lock_on(self) -> bool:
        return self._lock_client is not None

    def _next_id(self) -> str:
        self._seq += 1
        return f"sup-lock-{self._seq}"

    def _own_session(self) -> Any:
        fn = getattr(self._upstream, "own_session", None)
        return fn() if fn is not None else nullcontext()

    def _list_all(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Every page of the upstream ``tools/list`` on the current session."""
        tools: list[dict[str, Any]] = []
        first: dict[str, Any] = {}
        cursor: str | None = None
        for page in range(MAX_PAGES):
            params = {"cursor": cursor} if cursor else {}
            msg = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/list",
                "params": params,
            }
            reply = self._upstream.request(msg)
            if not isinstance(reply, dict) or "result" not in reply:
                raise LockUnavailable("upstream tools/list failed")
            result = reply["result"]
            try:
                tools.extend(mcp_lock.parse_tools(result))
            except mcp_lock.ToolListError as exc:
                raise LockUnavailable(str(exc)) from None
            if page == 0:
                first = {k: v for k, v in result.items() if k not in ("tools", "nextCursor")}
            cursor = result.get("nextCursor") if isinstance(result, dict) else None
            if not cursor:
                return tools, first
        raise LockUnavailable("tools/list has too many pages")

    def _observe(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        assert self._lock_client is not None
        tofu, self._tofu_by = self._tofu_by, None  # first sight only
        try:
            view = self._lock_client.observe(self.server_id, self._agent_id, tools, tofu)
        except Exception as exc:  # noqa: BLE001 - fail closed
            self._tofu_by = tofu
            raise LockUnavailable(f"lock service failed: {type(exc).__name__}") from None
        self._view, self._view_at = view, self._mono()
        return view

    def _refresh(self) -> dict[str, Any]:
        """List the upstream server on the proxy's own session and update the lock view."""
        with self._refresh_lock:
            if self._view is not None and self._mono() - self._view_at < self._refresh_s:
                return self._view
            try:
                with self._own_session():
                    tools, _first = self._list_all()
            except LockUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001
                reset = getattr(self._upstream, "reset_own_session", None)
                if reset is not None:
                    reset()
                raise LockUnavailable(f"upstream failed: {type(exc).__name__}") from None
            return self._observe(tools)

    def view_now(self) -> dict[str, Any]:
        if self._view is not None and self._mono() - self._view_at < self._refresh_s:
            return self._view
        return self._refresh()

    # ------------------------------------------------------------------ tools/call
    def _lock_verdict(self, name: str) -> dict[str, Any] | None:
        try:
            view = self.view_now()
        except LockUnavailable:
            return {
                "allow": False,
                "action": "block",
                "rule_id": RULE_LOCK_UNAVAILABLE,
                "reason": "tool lock unavailable: fail closed",
            }
        if name in view.get("visible", ()):
            return None
        status = (view.get("hidden") or {}).get(name)
        reason = {
            "new": "the tool is new and waits for two-person review",
            "changed": "the tool changed after it was approved and waits for two-person review",
        }.get(status or "", "the tool is not in the locked manifest of this server")
        return {"allow": False, "action": "block", "rule_id": RULE_UNREVIEWED, "reason": reason}

    def handle(self, message: Any) -> dict[str, Any] | None:
        if self.lock_on and isinstance(message, dict) and message.get("method") == "tools/call":
            params = message.get("params")
            name = params.get("name") if isinstance(params, dict) else None
            if isinstance(name, str):
                verdict = self._lock_verdict(name)
                if verdict is not None:
                    self._report(name, verdict)
                    if "id" not in message or message.get("id") is None:
                        return None
                    return deny_response(message["id"], verdict)
        return super().handle(message)

    def _report(self, name: str, verdict: Mapping[str, Any]) -> None:
        assert self._lock_client is not None
        try:
            self._lock_client.report_block(
                self.server_id, name, self._agent_id, str(verdict.get("rule_id"))
            )
        except Exception as exc:  # noqa: BLE001 - the refusal stands without the record
            log.error("mcp_tool_blocked record failed: %s", type(exc).__name__)

    # ------------------------------------------------------------------ list and initialize
    def _forward(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        if self.lock_on and method == "tools/list" and message.get("id") is not None:
            return self._filtered_list(message)
        reply = super()._forward(message)
        if self.lock_on and method == "initialize" and reply is not None and "result" in reply:
            try:  # lock the manifest at initialize; a failure shows at tools/list and tools/call
                self._refresh_force()
            except LockUnavailable as exc:
                log.warning("tool lock refresh at initialize failed: %s", exc)
        return reply

    def _refresh_force(self) -> dict[str, Any]:
        self._view_at = float("-inf")
        return self._refresh()

    def _filtered_list(self, message: dict[str, Any]) -> dict[str, Any]:
        id_ = message["id"]
        try:
            tools, first = self._list_all()
            view = self._observe(tools)
        except LockUnavailable:
            return _err(id_, INTERNAL_ERROR, "tool lock unavailable: fail closed")
        except Exception as exc:  # noqa: BLE001
            return _err(id_, INTERNAL_ERROR, f"upstream failure: {type(exc).__name__}")
        visible = set(view.get("visible", ()))
        shown = [t for t in tools if t["name"] in visible]
        return {"jsonrpc": "2.0", "id": id_, "result": {**first, "tools": shown}}


# ---------------------------------------------------------------------------------- HTTP server
def bind_httpd(cls: Any, host: str, port: int, handler: Any) -> Any:
    """``cls((host, port), handler)``. Port 0 means "a free port in 20000-29999": the host
    runs other services on 3000-3002, 5432, 6379, 8000-8080 and 55000-59999, which the
    system's own port 0 (the whole ephemeral range) could land on."""
    if port != 0:
        return cls((host, port), handler)
    rnd = random.SystemRandom()
    for _ in range(300):
        try:
            return cls((host, rnd.randint(*FREE_PORTS)), handler)
        except OSError:
            continue
    raise OSError("no free port in 20000-29999")


def _loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1", "[::1]")


class McpHttpServer:
    """The listener: one MCP endpoint (POST), validated Host and Origin, optional bearer."""

    def __init__(
        self,
        proxy: McpHttpGateProxy,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        path: str = DEFAULT_PATH,
        listen_token: str | None = None,
        allow_origins: tuple[str, ...] = (),
        allow_non_loopback: bool = False,
    ) -> None:
        if not _loopback(host) and not allow_non_loopback:
            raise ValueError(
                "the proxy has no inbound login: bind to 127.0.0.1, or pass "
                "--allow-non-loopback with --listen-token-env"
            )
        self.proxy = proxy
        self.path = path
        self.listen_token = listen_token
        self.allow_origins = allow_origins
        self._httpd = bind_httpd(ThreadingHTTPServer, host, port, _make_handler(self))
        self._httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._httpd.server_address[:2]
        return str(host), int(port)

    @property
    def url(self) -> str:
        host, port = self.address
        return f"http://{host}:{port}{self.path}"

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._thread.start()

    def serve_forever(self) -> None:
        self._httpd.serve_forever()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(2)

    # allowed Host and Origin values for this listener
    def host_ok(self, host: str | None) -> bool:
        if not host:
            return False
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        return _loopback(name) or name == self.address[0]

    def origin_ok(self, origin: str | None) -> bool:
        if origin is None:
            return True
        if origin in self.allow_origins:
            return True
        parts = urlsplit(origin)
        return _loopback(parts.hostname or "") and parts.scheme in ("http", "https")


def _make_handler(server: McpHttpServer) -> type[BaseHTTPRequestHandler]:
    proxy = server.proxy

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # keep-alive towards the agent
        server_version = "SupervisorMcp/1"

        def setup(self) -> None:
            super().setup()
            # headers and body leave in two writes; without NODELAY a kept-alive connection
            # waits for the delayed ACK (about 40 ms per call)
            self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        def log_message(self, fmt: str, *args: Any) -> None:  # no access log (no payloads)
            pass

        # -- helpers
        def _send(
            self,
            status: int,
            body: bytes = b"",
            ctype: str = "application/json",
            extra: Mapping[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            if body:
                self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if self.close_connection:
                self.send_header("Connection", "close")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _json(self, status: int, obj: Any, extra: Mapping[str, str] | None = None) -> None:
            self._send(
                status,
                json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode(),
                extra=extra,
            )

        def _guard(self) -> bool:
            """Path, Host, Origin and bearer checks. False = the answer is already sent."""
            if urlsplit(self.path).path != server.path:
                self.close_connection = True  # the request body is not read
                self._json(404, {"error": "not found"})
                return False
            if not server.host_ok(self.headers.get("Host")):
                self.close_connection = True  # the request body is not read
                self._json(403, {"error": "host not allowed"})
                return False
            if not server.origin_ok(self.headers.get("Origin")):
                self.close_connection = True  # the request body is not read
                self._json(403, {"error": "origin not allowed"})
                return False
            if server.listen_token is not None:
                got = self.headers.get("Authorization", "")
                want = f"Bearer {server.listen_token}"
                if not hmac.compare_digest(got.encode(), want.encode()):
                    self.close_connection = True  # the request body is not read
                    self._json(401, {"error": "authorization required"})
                    return False
            return True

        # -- verbs
        def do_GET(self) -> None:  # noqa: N802
            if self._guard():  # the optional server-to-client stream is not offered
                self._send(405, extra={"Allow": "POST, DELETE"})

        def do_DELETE(self) -> None:  # noqa: N802
            if not self._guard():
                return
            sid = self.headers.get("Mcp-Session-Id")
            ending = getattr(proxy._upstream, "delete_session", None)
            if not sid or ending is None:
                self._send(405, extra={"Allow": "POST"})
                return
            try:
                self._send(int(ending(sid)))
            except Exception:  # noqa: BLE001
                self._json(502, {"error": "upstream failure"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._guard():
                return
            try:
                n = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                n = -1
            if n < 0:
                self._json(411, {"error": "Content-Length required"})
                return
            if n > MAX_BODY:
                self.close_connection = True
                self._json(413, {"error": "request body too large"})
                return
            raw = self.rfile.read(n)
            try:
                message = json.loads(raw)
            except ValueError:
                self._json(400, _err(None, PARSE_ERROR, "parse error"))
                return
            up = proxy._upstream
            if hasattr(up, "bind"):
                up.bind(
                    self.headers.get("Mcp-Session-Id"), self.headers.get("MCP-Protocol-Version")
                )
            try:
                responses = self._dispatch(message)
            except Exception as exc:  # noqa: BLE001 - never a 500 with a trace
                log.error("mcp_http handler failed: %s", type(exc).__name__)
                self._json(502, _err(None, INTERNAL_ERROR, "proxy failure"))
                return
            extras, sid = up.take() if hasattr(up, "take") else ([], None)
            headers = {"Mcp-Session-Id": sid} if sid else {}
            if not responses and not extras:
                self._send(202, extra=headers)
                return
            if extras:
                events = [*extras, *responses]
                body = "".join(
                    "event: message\ndata: "
                    + json.dumps(m, ensure_ascii=True, separators=(",", ":"))
                    + "\n\n"
                    for m in events
                ).encode()
                self._send(200, body, "text/event-stream", headers)
                return
            batch = isinstance(message, list)
            self._json(200, responses if batch else responses[0], headers)

        def _dispatch(self, message: Any) -> list[dict[str, Any]]:
            items = message if isinstance(message, list) else [message]
            if not items:
                return [_err(None, INVALID_REQUEST, "empty batch")]
            out: list[dict[str, Any]] = []
            for item in items:
                r = proxy.handle(item)
                if r is not None:
                    out.append(r)
            return out

    return Handler


# ---------------------------------------------------------------------------------- CLI
def _say(text: str) -> None:
    print(text.encode("ascii", "replace").decode("ascii"))  # noqa: T201


def _hostport(text: str) -> tuple[str, int]:
    host, sep, port = text.rpartition(":")
    if not sep or not port.isdigit() or not 0 <= int(port) <= 65535:
        raise argparse.ArgumentTypeError("--listen must look like 127.0.0.1:9701")
    return host or "127.0.0.1", int(port)


def build_run_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m supervisor.gateway.mcp_http",
        description=__doc__.split("Run (")[0] if __doc__ else None,
        epilog="Review commands: python -m supervisor.gateway.mcp_http tools --help",
    )
    p.add_argument("--upstream", required=True, help="URL of the remote MCP endpoint")
    p.add_argument("--agent", required=True, help="agent id the gate judges these calls for")
    p.add_argument("--agent-version", default=DEFAULT_AGENT_VERSION)
    p.add_argument("--listen", type=_hostport, default=("127.0.0.1", 9701), metavar="HOST:PORT")
    p.add_argument("--path", default=DEFAULT_PATH, help="endpoint path of the listener")
    p.add_argument("--gate-url", default="http://127.0.0.1:8000")
    p.add_argument("--key-file", default=None, help="HMAC key file for ingress signing (WP20)")
    p.add_argument("--bearer-token-env", default=None, help="env var with a gate bearer token")
    p.add_argument("--server-name", default=None, help="lock id of the server (default: from URL)")
    p.add_argument("--upstream-bearer-env", default=None, help="env var with the upstream token")
    p.add_argument("--listen-token-env", default=None, help="env var: require this inbound bearer")
    p.add_argument("--allow-origin", action="append", default=[], help="extra allowed Origin")
    p.add_argument("--allow-non-loopback", action="store_true")
    p.add_argument(
        "--refresh-s", type=float, default=None, help="lock view lifetime (MCP_LOCK_REFRESH_S)"
    )
    p.add_argument("--no-tool-lock", action="store_true", help="gate only (also MCP_TOOL_LOCK=0)")
    p.add_argument("--trust-on-first-use", action="store_true", help="seed the first manifest")
    p.add_argument("--by", default=None, help="who runs trust-on-first-use (recorded)")
    p.add_argument("--inline-redaction", action="store_true")
    p.add_argument("--timeout-s", type=float, default=30.0, help="upstream read timeout")
    return p


def run_proxy(argv: list[str]) -> int:
    from supervisor.bootstrap import bootstrap

    bootstrap()
    ns = build_run_parser().parse_args(argv)
    from supervisor.config import load_settings
    from supervisor.core.errors import SupervisorError

    try:
        settings = load_settings()
    except SupervisorError as exc:
        _say(f"[FAIL] settings: {exc}")
        return 2
    if not settings.mcp_http_enabled:
        _say("[SKIP] the HTTP MCP gateway is off (MCP_HTTP_ENABLED=1 turns it on)")
        return 2
    if ns.trust_on_first_use and not ns.by:
        _say("[FAIL] --trust-on-first-use needs --by USER (it is recorded in the evidence chain)")
        return 2
    for env in (ns.upstream_bearer_env, ns.listen_token_env):
        if env and not os.environ.get(env):
            _say(f"[FAIL] environment variable {env} is empty")
            return 2
    from supervisor.gateway.ingress_sign import CredentialError
    from supervisor.gateway.sdk import HttpGate

    try:
        credential = make_credential(ns.agent, ns.key_file, ns.bearer_token_env)
    except CredentialError as exc:
        _say(f"[FAIL] ingress credential: {exc}")
        return 2
    from supervisor.adapters.mcp_upstream import HttpUpstream

    upstream = HttpUpstream(
        ns.upstream,
        bearer=os.environ.get(ns.upstream_bearer_env) if ns.upstream_bearer_env else None,
        timeout_s=ns.timeout_s,
    )
    lock_on = settings.mcp_tool_lock and not ns.no_tool_lock
    server_id = ns.server_name or server_id_for_url(ns.upstream)
    from supervisor.adapters.http_json import PooledJson

    pool = (
        PooledJson()
    )  # keep-alive to the gate too (the stdio proxy opens one connection per call)
    lock = HttpLockClient(ns.gate_url, credential, transport=pool.post_bytes) if lock_on else None
    if ns.trust_on_first_use:
        if not lock_on:
            _say("[FAIL] --trust-on-first-use needs the tool lock (MCP_TOOL_LOCK=1)")
            return 2
        sys.stderr.write(TOFU_WARNING + "\n")
    proxy = McpHttpGateProxy(
        HttpGate(
            ns.gate_url,
            credential=credential,
            transport=pool.post_json,
            signed_transport=pool.post_bytes,
        ),
        ns.agent,
        ns.agent_version,
        upstream,
        server_id=server_id,
        lock=lock,
        refresh_s=ns.refresh_s if ns.refresh_s is not None else settings.mcp_lock_refresh_s,
        tofu_by=ns.by if ns.trust_on_first_use else None,
        inline_redaction=True if ns.inline_redaction else None,
    )
    host, port = ns.listen
    try:
        server = McpHttpServer(
            proxy,
            host,
            port,
            path=ns.path,
            listen_token=os.environ.get(ns.listen_token_env) if ns.listen_token_env else None,
            allow_origins=tuple(ns.allow_origin),
            allow_non_loopback=ns.allow_non_loopback,
        )
    except (ValueError, OSError) as exc:
        _say(f"[FAIL] listener: {exc}")
        upstream.close()
        return 2
    _say(
        f"[OK] mcp_http listening on {server.url} for agent {ns.agent}; "
        f"upstream lock id {server_id}; tool lock {'on' if lock_on else 'OFF'}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        upstream.close()
    return 0


# -- review commands --------------------------------------------------------------------
def build_tools_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m supervisor.gateway.mcp_http tools",
        description="Review the tool lock: list, diff, propose, approve.",
    )
    p.add_argument("--supervisor-url", default=None, help="use the running app's routes (laptop)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("list", help="tools and their lock status")
    s.add_argument("server", nargs="?")
    s = sub.add_parser("diff", help="locked against observed definition")
    s.add_argument("server")
    s.add_argument("tool")
    for name, text in (("propose", "first approval"), ("approve", "approval (2nd person locks)")):
        s = sub.add_parser(name, help=text)
        s.add_argument("server")
        s.add_argument("tool")
        s.add_argument("--by", required=True, help="your user name")
        s.add_argument("--hash", required=True, help="observed hash you reviewed (12+ chars)")
    return p


def _print_rows(rows: list[dict[str, Any]]) -> None:
    for r in rows:
        mark = "HIDDEN" if r["hidden"] else r["status"].upper()
        sus = " SUSPICIOUS" if r["suspicious"] else ""
        have = len(r["approvals"])
        _say(
            f"{r['server_id']:30} {r['tool']:30} {mark:8}{sus} "
            f"approvals {have}/{r['approvals_needed']} hash {str(r['observed_hash'])[:12]}"
            f" case {r.get('case_id') or '-'}"
        )
    _say(f"[OK] {len(rows)} tool(s)")


def _print_diff(d: dict[str, Any]) -> None:
    _say(f"tool {d['tool']} on {d['server_id']}: {d['status']}, hash {d['observed_hash']}")
    _say(f"locked hash {d.get('locked_hash')}")
    _say(f"fields changed: {', '.join(d['diff']['changed']) or 'none'}")
    for note in d["diff"]["notes"]:
        _say(f"  note: {note}")
    for f in d["findings"]:
        _say(f"  scan: {f['kind']} in {f['field']} x{f['count']} (report only)")
    for label, key in (("LOCKED", "locked"), ("OBSERVED", "observed")):
        _say(f"--- {label} definition (ASCII-escaped) ---")
        _say(json.dumps(d.get(key), ensure_ascii=True, indent=2, sort_keys=True)[:6000])


def run_tools(argv: list[str]) -> int:
    from supervisor.bootstrap import bootstrap

    bootstrap()
    ns = build_tools_parser().parse_args(argv)
    from supervisor.core.errors import SupervisorError

    try:
        if ns.supervisor_url:
            return _tools_over_http(ns)
        return _tools_direct(ns)
    except SupervisorError as exc:
        _say(f"[FAIL] {exc}")
        return 1
    except OSError as exc:
        _say(f"[FAIL] {type(exc).__name__}: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - an HTTP error from the app: show its message
        resp = getattr(exc, "response", None)
        text = ""
        if resp is not None:
            try:
                text = str(resp.json().get("error", ""))
            except Exception:  # noqa: BLE001
                text = ""
        _say(f"[FAIL] {text or type(exc).__name__}")
        return 1


def _tools_direct(ns: argparse.Namespace) -> int:
    from supervisor.cases import build_case_service
    from supervisor.config import load_settings
    from supervisor.gateway.mcp_lock_service import ToolLockService, inventory_hook
    from supervisor.wiring import build_runtime

    settings = load_settings()
    if not settings.mcp_http_enabled:
        _say("[SKIP] the HTTP MCP gateway is off (MCP_HTTP_ENABLED=1 turns it on)")
        return 2
    runtime = build_runtime(settings)
    try:
        a = runtime.adapters
        svc = ToolLockService(
            a.state,
            runtime.chain,
            a.clock,
            build_case_service(runtime),
            on_new_server=inventory_hook(a.state, a.clock) if settings.inventory_enabled else None,
        )
        if ns.cmd == "list":
            _print_rows(svc.list_tools(ns.server))
        elif ns.cmd == "diff":
            _print_diff(svc.diff(ns.server, ns.tool))
        else:
            fn = svc.propose if ns.cmd == "propose" else svc.approve
            r = fn(ns.server, ns.tool, ns.by, ns.hash)
            _say(
                f"[OK] {ns.cmd} recorded for {r['tool']}: "
                + (
                    "LOCKED (second person)"
                    if r["locked"]
                    else "waiting for a second, different person"
                )
            )
    finally:
        runtime.close()
    return 0


def _tools_over_http(ns: argparse.Namespace) -> int:
    from urllib.parse import quote

    from supervisor.adapters.http_json import get_json, post_json

    base = ns.supervisor_url.rstrip("/")
    headers = {"X-Dev-User": getattr(ns, "by", "") or "cli"}
    if ns.cmd == "list":
        q = f"?server_id={quote(ns.server)}" if ns.server else ""
        _print_rows(get_json(f"{base}/v1/mcp/tools{q}", 10.0, headers=headers)["tools"])
    elif ns.cmd == "diff":
        url = f"{base}/v1/mcp/tools/diff?server_id={quote(ns.server)}&tool={quote(ns.tool)}"
        _print_diff(get_json(url, 10.0, headers=headers))
    else:
        r = post_json(
            f"{base}/v1/mcp/tools/{ns.cmd}",
            {"server_id": ns.server, "tool": ns.tool, "observed_hash": ns.hash},
            10.0,
            headers=headers,
        )
        _say(
            f"[OK] {ns.cmd} recorded: "
            + ("LOCKED" if r.get("locked") else "waiting for a second person")
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "tools":
        return run_tools(args[1:])
    return run_proxy(args)


@contextmanager
def running(server: McpHttpServer) -> Iterator[McpHttpServer]:
    """Start and stop a listener (tests, harness)."""
    server.start()
    try:
        yield server
    finally:
        server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
