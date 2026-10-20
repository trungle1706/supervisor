"""Upstream client of the HTTP MCP proxy (WP26): MCP streamable HTTP, one pooled client.

The only module of the proxy that uses httpx (ports and adapters). One ``httpx.Client`` per
upstream server is kept for the life of the proxy, so every call reuses a keep-alive
connection (the latency doc compares this with a new connection per call).

Transport rules followed (MCP streamable HTTP, revisions 2025-03-26 and 2025-06-18):

* every message is a POST of one JSON-RPC message to the single MCP endpoint, with
  ``Accept: application/json, text/event-stream``;
* the answer is ``application/json`` (one response), ``text/event-stream`` (zero or more
  server messages, then the response with the same id), or ``202`` with no body (a
  notification or a response);
* ``Mcp-Session-Id`` and ``MCP-Protocol-Version`` are passed through per request; the proxy
  keeps no client session of its own. For the tool lock it opens ONE session of its own.

Not done (docs/mcp-gateway.md, BACKLOG): the optional GET stream for server-initiated messages,
stream resumption (``Last-Event-ID``), OAuth to the upstream server (a static bearer token from
the environment is supported).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx

MAX_BODY = 8 * 1024 * 1024
MAX_EVENTS = 200
SESSION_HEADER = "Mcp-Session-Id"
PROTOCOL_HEADER = "MCP-Protocol-Version"
LOCK_PROTOCOL = "2025-06-18"


class UpstreamError(Exception):
    """The upstream server answered with an HTTP error or an unusable body."""


@dataclass
class UpstreamReply:
    messages: list[dict[str, Any]] = field(default_factory=list)
    session_id: str | None = None
    status: int = 200


def parse_sse(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    """JSON messages from the ``data:`` fields of a server-sent-events stream."""
    data: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line == "":
            if data:
                text = "\n".join(data)
                data = []
                try:
                    obj = json.loads(text)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    yield obj
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        if name == "data":
            data.append(value[1:] if value.startswith(" ") else value)
    if data:
        try:
            obj = json.loads("\n".join(data))
        except ValueError:
            return
        if isinstance(obj, dict):
            yield obj


class HttpUpstream:
    """``request(message)`` for ``McpGateProxy`` plus per-request session context."""

    def __init__(
        self,
        url: str,
        *,
        bearer: str | None = None,
        timeout_s: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.url = url
        self._bearer = bearer
        self._timeout = httpx.Timeout(timeout_s, connect=min(5.0, timeout_s))
        self._client = client or httpx.Client(
            timeout=self._timeout,
            limits=httpx.Limits(max_keepalive_connections=20, keepalive_expiry=60.0),
            follow_redirects=False,
        )
        self._tl = threading.local()
        self._own_lock = threading.Lock()
        self._own_session: str | None = None
        self._own_ready = False

    # ------------------------------------------------------------------ context
    def bind(self, session_id: str | None, protocol_version: str | None) -> None:
        """Session headers of the client request being served on this thread."""
        self._tl.session_id = session_id
        self._tl.protocol = protocol_version
        self._tl.extras = []
        self._tl.reply_session = None

    def take(self) -> tuple[list[dict[str, Any]], str | None]:
        """Server messages seen before the response, and the session id the upstream set."""
        extras = getattr(self._tl, "extras", [])
        sid = getattr(self._tl, "reply_session", None)
        self._tl.extras = []
        self._tl.reply_session = None
        return extras, sid

    @contextmanager
    def own_session(self) -> Iterator[None]:
        """Run requests on this thread inside the proxy's own upstream session (tool lock)."""
        self._ensure_own_session()
        prev = (
            getattr(self._tl, "session_id", None),
            getattr(self._tl, "protocol", None),
            getattr(self._tl, "extras", []),
            getattr(self._tl, "reply_session", None),
        )
        self._tl.session_id, self._tl.protocol = self._own_session, LOCK_PROTOCOL
        self._tl.extras = []
        try:
            yield
        finally:
            self._tl.session_id, self._tl.protocol, self._tl.extras, self._tl.reply_session = prev

    def _ensure_own_session(self) -> None:
        with self._own_lock:
            if self._own_ready:
                return
            init = {
                "jsonrpc": "2.0",
                "id": "sup-lock-init",
                "method": "initialize",
                "params": {
                    "protocolVersion": LOCK_PROTOCOL,
                    "capabilities": {},
                    "clientInfo": {"name": "supervisor-mcp-lock", "version": "1"},
                },
            }
            reply = self.post(init, None, LOCK_PROTOCOL)
            resp = next((m for m in reply.messages if m.get("id") == "sup-lock-init"), None)
            if resp is None or "error" in resp:
                raise UpstreamError("upstream refused the lock session")
            self._own_session = reply.session_id
            self.post(
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                self._own_session,
                LOCK_PROTOCOL,
            )
            self._own_ready = True

    def reset_own_session(self) -> None:
        with self._own_lock:
            self._own_ready = False
            self._own_session = None

    # ------------------------------------------------------------------ transport
    def _headers(self, session_id: str | None, protocol: str | None) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if session_id:
            h[SESSION_HEADER] = session_id
        if protocol:
            h[PROTOCOL_HEADER] = protocol
        if self._bearer:
            h["Authorization"] = f"Bearer {self._bearer}"
        return h

    def post(
        self, message: Mapping[str, Any], session_id: str | None, protocol: str | None
    ) -> UpstreamReply:
        body = json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        want = message.get("id") if "method" in message else None
        out = UpstreamReply()
        try:
            with self._client.stream(
                "POST", self.url, content=body, headers=self._headers(session_id, protocol)
            ) as resp:
                out.status = resp.status_code
                out.session_id = resp.headers.get(SESSION_HEADER)
                if resp.status_code == 202 or (resp.status_code == 200 and "id" not in message):
                    return out
                if resp.status_code >= 400:
                    raise UpstreamError(f"upstream answered HTTP {resp.status_code}")
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype == "text/event-stream":
                    n = 0
                    for msg in parse_sse(resp.iter_lines()):
                        out.messages.append(msg)
                        n += 1
                        if (
                            want is not None
                            and msg.get("id") == want
                            and ("result" in msg or "error" in msg)
                        ) or n >= MAX_EVENTS:
                            break
                    return out
                data = bytearray()
                for chunk in resp.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BODY:
                        raise UpstreamError("upstream body is too large")
                parsed = json.loads(bytes(data) or b"null")
        except httpx.HTTPError as exc:
            raise UpstreamError(f"upstream transport failure: {type(exc).__name__}") from None
        except ValueError:
            raise UpstreamError("upstream answered with invalid JSON") from None
        items = parsed if isinstance(parsed, list) else [parsed]
        out.messages = [m for m in items if isinstance(m, dict)]
        return out

    def request(self, message: dict[str, Any]) -> dict[str, Any] | None:
        reply = self.post(
            message, getattr(self._tl, "session_id", None), getattr(self._tl, "protocol", None)
        )
        if reply.session_id:
            self._tl.reply_session = reply.session_id
        if "id" not in message:
            return None
        want = message["id"]
        # Only server REQUESTS and NOTIFICATIONS (with a method) are passed on to the client. A
        # response with any other id is dropped: the client never asked for it on this POST, and
        # relayed it could answer one of the client's own requests (for example a tools/list with
        # the hidden tools in it, sent ahead of the proxy's filtered answer). Review WP26 F1.
        extras = [m for m in reply.messages if "method" in m and isinstance(m.get("method"), str)]
        if extras and hasattr(self._tl, "extras"):
            self._tl.extras = [*self._tl.extras, *extras]
        for m in reply.messages:
            if m.get("id") == want and "method" not in m:
                return m
        raise UpstreamError("upstream sent no response for the request")

    def delete_session(self, session_id: str) -> int:
        """Pass a client's session end (HTTP DELETE) to the upstream server."""
        try:
            resp = self._client.delete(self.url, headers=self._headers(session_id, None))
        except httpx.HTTPError as exc:
            raise UpstreamError(f"upstream transport failure: {type(exc).__name__}") from None
        return resp.status_code

    def close(self) -> None:
        self._client.close()
