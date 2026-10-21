"""ASGI middleware (inbound traffic of an agent app), run without a server."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from supervisor.gateway.adapters.fastapi_mw import SupervisorASGIMiddleware
from tests.collectors.fakes import ALLOW, BLOCK, PAUSE, DownGate, FakeGate, transform


class App:
    """A tiny ASGI app: echoes JSON; records the body it received."""

    def __init__(self, reply: bytes = b'{"ok": true}', ctype: bytes = b"application/json") -> None:
        self.reply, self.ctype = reply, ctype
        self.bodies: list[bytes] = []
        self.chunks = 1

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        body = b""
        while True:
            m = await receive()
            body += m.get("body", b"")
            if not m.get("more_body"):
                break
        self.bodies.append(body)
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", self.ctype), (b"content-length", b"999")],
            }
        )
        step = max(1, len(self.reply) // self.chunks)
        parts = [self.reply[i : i + step] for i in range(0, len(self.reply), step)] or [b""]
        for i, part in enumerate(parts):
            await send(
                {"type": "http.response.body", "body": part, "more_body": i < len(parts) - 1}
            )


def call(mw: Any, body: bytes = b'{"q": "hi"}', headers: list | None = None, path: str = "/chat"):
    sent: list[dict] = []
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers or [(b"content-type", b"application/json")],
    }
    chunks = [body[i : i + 7] for i in range(0, len(body), 7)] or [b""]
    feed = [
        {"type": "http.request", "body": c, "more_body": i < len(chunks) - 1}
        for i, c in enumerate(chunks)
    ]

    async def receive() -> dict:
        return feed.pop(0) if feed else {"type": "http.disconnect"}

    async def send(m: dict) -> None:
        sent.append(m)

    asyncio.run(mw(scope, receive, send))
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
    headers_out = {
        k.decode(): v.decode()
        for m in sent
        if m["type"] == "http.response.start"
        for k, v in m["headers"]
    }
    out = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, headers_out, out


def build(gate: Any, app: App | None = None, **kw: Any) -> tuple[SupervisorASGIMiddleware, App]:
    app = app or App()
    return SupervisorASGIMiddleware(app, gate=gate, agent_id="agent-1", **kw), app


def test_allowed_request_passes_through_both_phases() -> None:
    gate = FakeGate(ALLOW)
    mw, app = build(gate)
    status, headers, out = call(
        mw, headers=[(b"x-consumer-id", b"user-9"), (b"x-session-id", b"s-1")]
    )
    assert status == 200 and json.loads(out) == {"ok": True}
    assert app.bodies == [b'{"q": "hi"}']
    inp, outp = gate.calls
    assert inp["tool_name"] == "http_inbound" and inp["direction"] == "input"
    assert inp["args"]["body"] == {"q": "hi"} and inp["args"]["path"] == "/chat"
    assert inp["context"]["consumer_id"] == "user-9" and inp["context"]["session_id"] == "s-1"
    assert outp["direction"] == "output" and json.loads(outp["context"]["output"]) == {"ok": True}
    assert headers["x-supervisor-correlation-id"] == inp["correlation_id"] == outp["correlation_id"]
    assert headers["content-length"] == str(len(out))  # the stale length of the app is replaced


def test_input_block_is_403_and_the_app_is_not_called() -> None:
    mw, app = build(FakeGate(BLOCK))
    status, headers, out = call(mw)
    body = json.loads(out)
    assert status == 403 and app.bodies == [] and body["error"] == "blocked"
    assert (
        body["rule_id"] == "PAY-06"
        and body["correlation_id"] == headers["x-supervisor-correlation-id"]
    )


def test_pause_is_503_paused() -> None:
    status, _, out = call(build(FakeGate(PAUSE))[0])
    assert status == 503 and json.loads(out)["error"] == "paused"


def test_gate_down_is_503_unavailable_and_closed() -> None:
    mw, app = build(DownGate())
    status, _, out = call(mw)
    assert status == 503 and json.loads(out)["error"] == "unavailable" and app.bodies == []


def test_gate_down_open_mode_passes_a_plain_route() -> None:
    mw, app = build(DownGate(), fail_mode="open")
    assert call(mw)[0] == 200 and len(app.bodies) == 1


def test_output_block_replaces_the_whole_response() -> None:
    gate = FakeGate(lambda c: dict(BLOCK) if c["direction"] == "output" else dict(ALLOW))
    app = App(reply=b'{"secret": "' + b"x" * 300 + b'"}')
    app.chunks = 5  # the app streams in pieces; none of it may reach the client
    status, _, out = call(build(gate, app)[0])
    assert status == 403 and b"secret" not in out


def test_pause_on_the_output_in_the_middle_of_a_stream_sends_nothing_of_the_response() -> None:
    gate = FakeGate(lambda c: dict(PAUSE) if c["direction"] == "output" else dict(ALLOW))
    app = App(reply=b"line one\nline two\nline three\n", ctype=b"text/plain")
    app.chunks = 3
    status, _, out = call(build(gate, app)[0])
    assert status == 503 and b"line" not in out


def test_masked_request_body_reaches_the_app_with_the_right_length() -> None:
    def answer(c: dict) -> dict:
        return transform(args={"body": {"q": "<PERSON>"}}) if c["direction"] == "input" else ALLOW

    gate = FakeGate(answer)
    mw, app = build(gate)
    assert call(mw, body=b'{"q": "Nguyen Van A"}')[0] == 200
    assert json.loads(app.bodies[0]) == {"q": "<PERSON>"}


def test_masked_response_replaces_the_body() -> None:
    gate = FakeGate(lambda c: transform(output="MASKED") if c["direction"] == "output" else ALLOW)
    status, headers, out = call(build(gate)[0])
    assert status == 200 and out == b"MASKED" and headers["content-length"] == "6"


def test_oversize_request_is_413_and_never_reaches_gate_or_app() -> None:
    gate = FakeGate(ALLOW)
    mw, app = build(gate, max_request_bytes=50)
    status, _, _ = call(mw, body=b"x" * 200)
    assert status == 413 and gate.calls == [] and app.bodies == []


def test_oversize_response_is_refused_when_closed_and_not_leaked() -> None:
    app = App(reply=b"y" * 500, ctype=b"text/plain")
    mw, _ = build(FakeGate(ALLOW), app, max_response_bytes=100)
    status, _, out = call(mw)
    assert status == 502 and b"yyy" not in out


def test_binary_responses_and_skipped_paths_are_not_checked() -> None:
    gate = FakeGate(ALLOW)
    app = App(reply=b"\x00\x01", ctype=b"application/octet-stream")
    mw, _ = build(gate, app)
    assert call(mw)[0] == 200 and len(gate.calls) == 1  # input only
    gate2 = FakeGate(ALLOW)
    mw2, app2 = build(gate2)
    assert call(mw2, path="/healthz")[0] == 200 and gate2.calls == [] and len(app2.bodies) == 1


def test_header_injection_in_the_correlation_id_session_and_consumer_is_dropped() -> None:
    gate = FakeGate(ALLOW)
    mw, _ = build(gate)
    hdrs = [
        (b"x-supervisor-correlation-id", b"abc\r\nx-evil: 1"),
        (b"x-session-id", b"s\r\ns"),
        (b"x-consumer-id", b"\xff\xfe"),
    ]
    status, headers, _ = call(mw, headers=hdrs)
    assert status == 200
    assert "\n" not in headers["x-supervisor-correlation-id"]
    assert "evil" not in headers["x-supervisor-correlation-id"]
    ctx = gate.calls[0]["context"]
    assert "session_id" not in ctx and "consumer_id" not in ctx


def test_a_valid_inbound_correlation_id_is_kept() -> None:
    gate = FakeGate(ALLOW)
    mw, _ = build(gate)
    _, headers, _ = call(mw, headers=[(b"x-supervisor-correlation-id", b"trace-123")])
    assert headers["x-supervisor-correlation-id"] == "trace-123"


def test_non_json_body_is_sent_as_text_and_empty_body_works() -> None:
    gate = FakeGate(ALLOW)
    mw, _ = build(gate)
    call(mw, body=b"plain words")
    assert gate.calls[0]["args"]["text"] == "plain words"
    call(mw, body=b"")
    assert "body" not in gate.calls[2]["args"]


def test_other_scope_types_pass_untouched() -> None:
    seen: list[str] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        seen.append(scope["type"])

    mw = SupervisorASGIMiddleware(app, gate=FakeGate(), agent_id="agent-1")
    asyncio.run(mw({"type": "lifespan"}, None, None))  # type: ignore[arg-type]
    assert seen == ["lifespan"]
