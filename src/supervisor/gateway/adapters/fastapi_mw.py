"""ASGI middleware for the inbound traffic of an agent app (FastAPI or any ASGI app; WP38).

Two phases around the app, both through the gate:

* input: the request body (JSON or text) is sent as ``args`` of the tool ``http_inbound`` (rename
  with ``tool_name``; register it in the policy ``tools`` section, usually as ``read_only``);
* output: the response body is sent with ``direction=output`` and ``context.output``.

The response is held back until the output check is done, so a block or a pause on the output
replaces the whole response (nothing of it has left the process). The price is that a streamed
response is buffered; a response above ``max_response_bytes`` is refused when ``fail_mode`` is
closed. Binary responses (not JSON or text) are not inspected and pass.

Answers made here are JSON: 403 for a block, 503 for a pause or an unreachable gate, 413 for an
oversized request. Each carries ``correlation_id``, also sent as ``X-Supervisor-Correlation-Id``.

Starlette is not imported: this is plain ASGI, so it works under FastAPI, Starlette and others.

    app.add_middleware(SupervisorASGIMiddleware, gate=HttpGate(url, credential=cred),
                       agent_id="my-agent", agent_version="1")
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable, Mapping, MutableMapping
from typing import Any

from supervisor.core.ports import GateHook
from supervisor.gateway.adapters.common import (
    CORRELATION_HEADER,
    UNAVAILABLE_RULES,
    GateAnswer,
    GateClient,
    clean_id,
    new_correlation_id,
)

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

DEFAULT_SKIP = ("/health", "/healthz", "/ready", "/docs", "/openapi.json")
_TEXT_TYPES = ("application/json", "text/")


def _header(scope: Scope, name: str) -> str | None:
    want = name.lower().encode("latin-1")
    for k, v in scope.get("headers") or []:
        if k.lower() == want:
            try:
                return v.decode("latin-1")
            except UnicodeDecodeError:  # pragma: no cover - latin-1 never fails
                return None
    return None


class SupervisorASGIMiddleware:
    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        *,
        gate: GateHook,
        agent_id: str,
        agent_version: str = "1",
        tool_name: str = "http_inbound",
        fail_mode: str = "closed",
        consumer_header: str = "X-Consumer-Id",
        session_header: str = "X-Session-Id",
        skip_paths: Iterable[str] = DEFAULT_SKIP,
        check_input: bool = True,
        check_output: bool = True,
        max_request_bytes: int = 256 * 1024,
        max_response_bytes: int = 1024 * 1024,
        risk_class: str | None = "read_only",
    ) -> None:
        self.app = app
        self.client = GateClient(
            gate,
            agent_id,
            agent_version,
            fail_mode=fail_mode,
            default_risk_class=risk_class,
            max_payload_bytes=max(max_request_bytes, max_response_bytes),
        )
        self.tool_name = tool_name
        self.consumer_header = consumer_header
        self.session_header = session_header
        self.skip_paths = tuple(skip_paths)
        self.check_input = check_input
        self.check_output = check_output
        self.max_request_bytes = max_request_bytes
        self.max_response_bytes = max_response_bytes
        self.closed = fail_mode == "closed"

    # ------------------------------------------------------------------ small helpers

    @staticmethod
    async def _reply(send: Send, status: int, body: Mapping[str, Any], cid: str) -> None:
        raw = json.dumps(body, ensure_ascii=True).encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(raw)).encode()),
            (CORRELATION_HEADER.lower().encode(), cid.encode()),
        ]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": raw})

    async def _refuse(self, send: Send, ans: GateAnswer) -> None:
        unavailable = (ans.rule_id or "") in UNAVAILABLE_RULES
        kind = "paused" if ans.paused else ("unavailable" if unavailable else "blocked")
        await self._reply(
            send,
            403 if kind == "blocked" else 503,
            {
                "error": kind,
                "rule_id": ans.rule_id,
                "status": ans.status,
                "correlation_id": ans.correlation_id,
            },
            ans.correlation_id,
        )

    @staticmethod
    async def _read_body(receive: Receive, cap: int) -> tuple[bytes, bool]:
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return b"".join(chunks), False
            part = message.get("body", b"")
            size += len(part)
            if size > cap:
                return b"", True
            chunks.append(part)
            if not message.get("more_body", False):
                return b"".join(chunks), False

    @staticmethod
    def _args_of(scope: Scope, body: bytes) -> dict[str, Any]:
        args: dict[str, Any] = {"method": str(scope.get("method", "")), "path": scope["path"][:512]}
        if body:
            try:
                args["body"] = json.loads(body)
            except (ValueError, UnicodeDecodeError):
                args["text"] = body.decode("utf-8", "replace")
        return args

    @staticmethod
    def _body_from(answer: GateAnswer, original: bytes) -> bytes | None:
        """The body to pass on; None when masked values exist but cannot be applied."""
        new = answer.transformed_args
        if new is None:
            return original
        if "body" in new:
            return json.dumps(new["body"], ensure_ascii=False).encode("utf-8")
        if isinstance(new.get("text"), str):
            return new["text"].encode("utf-8")
        return None

    # ------------------------------------------------------------------ the middleware

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path", ""))
        if scope["type"] != "http" or any(path.startswith(p) for p in self.skip_paths):
            await self.app(scope, receive, send)
            return
        cid = clean_id(_header(scope, CORRELATION_HEADER)) or new_correlation_id()
        consumer = _header(scope, self.consumer_header)
        session = _header(scope, self.session_header)
        if self.check_input:
            body, too_big = await self._read_body(receive, self.max_request_bytes)
            if too_big:  # the body is partly read: it cannot be passed on, in any fail mode
                await self._reply(send, 413, {"error": "too large", "correlation_id": cid}, cid)
                return
            ans = await self.client.acheck(
                self.tool_name,
                self._args_of(scope, body),
                correlation_id=cid,
                consumer_id=consumer,
                session_id=session,
            )
            if (stop := GateClient.refusal(ans)) is not None:
                await self._refuse(send, stop)
                return
            cid = ans.correlation_id
            new_body = self._body_from(ans, body)
            if new_body is None:  # a transform without a body or text: fail closed
                await self._reply(
                    send,
                    403,
                    {
                        "error": "blocked",
                        "rule_id": "SDK-TRANSFORM-UNAPPLIED",
                        "correlation_id": cid,
                    },
                    cid,
                )
                return
            body = new_body
            scope = dict(scope)
            scope["headers"] = [
                (k, str(len(body)).encode() if k.lower() == b"content-length" else v)
                for k, v in scope.get("headers") or []
            ]
            sent = False

            async def replay() -> MutableMapping[str, Any]:
                nonlocal sent
                if sent:
                    return {"type": "http.disconnect"}
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}

            receive = replay
        if not self.check_output:
            await self.app(scope, receive, send)
            return
        await self._buffered(scope, receive, send, cid, consumer, session)

    async def _buffered(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        cid: str,
        consumer: str | None,
        session: str | None,
    ) -> None:
        start: MutableMapping[str, Any] | None = None
        chunks: list[bytes] = []
        size = 0
        overflow = False

        async def capture(message: MutableMapping[str, Any]) -> None:
            nonlocal start, size, overflow
            if message["type"] == "http.response.start":
                start = message
            elif message["type"] == "http.response.body":
                size += len(message.get("body", b""))
                if size > self.max_response_bytes:
                    overflow = True
                else:
                    chunks.append(message.get("body", b""))

        await self.app(scope, receive, capture)
        if start is None:
            return
        headers = list(start.get("headers") or [])
        ctype = next((v.decode("latin-1") for k, v in headers if k.lower() == b"content-type"), "")
        body = b"".join(chunks)
        if overflow:
            # The part above the cap was not kept (memory stays bounded), so the response cannot
            # be passed on whole in any fail mode (WP38 review: open mode sent a cut body).
            await self._reply(
                send,
                502,
                {"error": "response too large to inspect", "correlation_id": cid},
                cid,
            )
            return
        elif ctype.lower().startswith(_TEXT_TYPES) and body:
            ans = await self.client.acheck(
                self.tool_name,
                {},
                direction="output",
                context={"output": body.decode("utf-8", "replace")},
                correlation_id=cid,
                consumer_id=consumer,
                session_id=session,
            )
            if (stop := GateClient.refusal(ans)) is not None:
                await self._refuse(send, stop)
                return
            new = ans.transformed_output
            if isinstance(new, str):
                body = new.encode("utf-8")
        headers = [
            h for h in headers if h[0].lower() not in (b"content-length", b"transfer-encoding")
        ]
        headers.append((b"content-length", str(len(body)).encode()))
        headers.append((CORRELATION_HEADER.lower().encode(), cid.encode()))
        await send({**start, "headers": headers})
        await send({"type": "http.response.body", "body": body})
