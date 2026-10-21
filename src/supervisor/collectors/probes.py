"""Adversarial probes of the collector adapters (team brief section 3 point 9).

26 inputs that the contract templates do not produce: hostile or odd ids, header injection,
oversized or strange payloads, a pause in the middle of a run, malformed gate answers, a hostile
hook event. Each probe returns True when the adapter behaved safely. They were written before the
first run and not changed after. Used by ``harness.py`` and ``tests/collectors/test_probes.py``.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from supervisor.gateway.adapters import claude_code_hook as hook
from supervisor.gateway.adapters.common import GateClient, clean_id, safe_tool_name
from supervisor.gateway.adapters.fastapi_mw import SupervisorASGIMiddleware
from supervisor.gateway.adapters.langgraph import SupervisorToolMiddleware
from supervisor.gateway.adapters.litellm_guardrail import SupervisorGuardrail
from supervisor.gateway.sdk import HttpGate, SupervisorBlocked, SupervisorPaused

ROUTE_ID = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")  # the gate route's pattern for tool names
OK_ANSWER: dict[str, Any] = {"allow": True, "action": "allow", "rule_id": None, "reason": "ok"}
PAUSE_ANSWER: dict[str, Any] = {
    "allow": False,
    "action": "pause",
    "rule_id": "P-1",
    "reason": "agent paused",
    "status": "pause",
}


class Spy:
    """A gate that records what it was asked and answers from a function."""

    def __init__(self, fn: Callable[[dict], Mapping[str, Any]] | None = None) -> None:
        self.fn = fn or (lambda c: OK_ANSWER)
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def check_v2(
        self,
        agent_id,
        agent_version,
        tool_name,
        args,
        context=None,
        *,
        direction="input",
        correlation_id=None,
    ):  # type: ignore[no-untyped-def]
        call = {
            "tool": tool_name,
            "args": dict(args),
            "ctx": dict(context or {}),
            "direction": direction,
            "cid": correlation_id,
        }
        with self._lock:
            self.calls.append(call)
        return dict(self.fn(call))

    def check(self, agent_id, agent_version, tool_name, args, context=None):  # type: ignore[no-untyped-def]
        return self.check_v2(agent_id, agent_version, tool_name, args, context)


@dataclass
class _Req:
    tool_call: dict[str, Any]
    runtime: Any = None


@dataclass
class _Msg:
    content: Any


def _tool(spy: Spy, **kw: Any) -> SupervisorToolMiddleware:
    return SupervisorToolMiddleware(spy, "agent-1", "1", **kw)


def _run_tool(mw: SupervisorToolMiddleware, name: str = "pay", args: Any = None) -> bool:
    """True when the tool ran."""
    ran: list[int] = []

    def handler(r: Any) -> _Msg:
        ran.append(1)
        return _Msg("done")

    try:
        mw.wrap_tool_call(_Req({"name": name, "args": args if args is not None else {}}), handler)
    except SupervisorBlocked:
        pass
    return bool(ran)


async def _asgi(
    mw: Any, body: bytes, headers: list | None = None
) -> tuple[int | None, dict, bytes]:
    sent: list[dict] = []
    feed = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive() -> dict:
        return feed.pop(0) if feed else {"type": "http.disconnect"}

    async def send(m: dict) -> None:
        sent.append(m)

    scope = {"type": "http", "method": "POST", "path": "/chat", "headers": headers or []}
    await mw(scope, receive, send)
    start = next((m for m in sent if m["type"] == "http.response.start"), None)
    hdr = {k.decode(): v.decode("latin-1") for k, v in (start or {}).get("headers", [])}
    out = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return (start or {}).get("status"), hdr, out


def _echo_app(reply: bytes = b'{"ok": true}', ctype: bytes = b"application/json") -> Any:
    async def app(scope: Any, receive: Any, send: Any) -> None:
        await receive()
        await send(
            {"type": "http.response.start", "status": 200, "headers": [(b"content-type", ctype)]}
        )
        await send({"type": "http.response.body", "body": reply})

    return app


# ----------------------------------------------------------------------------- the probes


def p01() -> bool:  # consumer id with a newline
    spy = Spy()
    _run_tool(_tool(spy, consumer_id=lambda r: "a\nb"))
    return "consumer_id" not in spy.calls[0]["ctx"]


def p02() -> bool:  # consumer id of 129 characters
    spy = Spy()
    g = SupervisorGuardrail(spy, "agent-1")
    asyncio.run(g.async_pre_call_hook({"user_id": "x" * 129}, None, {"messages": []}, "completion"))
    return "consumer_id" not in spy.calls[0]["ctx"]


def p03() -> bool:  # consumer id with non-ASCII bytes in a header
    spy = Spy()
    mw = SupervisorASGIMiddleware(_echo_app(), gate=spy, agent_id="agent-1")
    asyncio.run(_asgi(mw, b"{}", [(b"x-consumer-id", "café".encode("latin-1"))]))
    return "consumer_id" not in spy.calls[0]["ctx"]


def p04() -> bool:  # consumer id that is an object
    spy = Spy()
    _run_tool(_tool(spy, consumer_id=lambda r: {"id": 1}))  # type: ignore[arg-type,return-value]
    return "consumer_id" not in spy.calls[0]["ctx"]


def p05() -> bool:  # CRLF in the inbound correlation id
    spy = Spy()
    mw = SupervisorASGIMiddleware(_echo_app(), gate=spy, agent_id="agent-1")
    _, hdr, _ = asyncio.run(
        _asgi(mw, b"{}", [(b"x-supervisor-correlation-id", b"abc\r\nx-evil: 1")])
    )
    v = hdr.get("x-supervisor-correlation-id", "")
    return "\n" not in v and "\r" not in v and "evil" not in v and bool(clean_id(v))


def p06() -> bool:  # 200 character correlation id
    spy = Spy()
    mw = SupervisorASGIMiddleware(_echo_app(), gate=spy, agent_id="agent-1")
    _, hdr, _ = asyncio.run(_asgi(mw, b"{}", [(b"x-supervisor-correlation-id", b"a" * 200)]))
    return len(hdr.get("x-supervisor-correlation-id", "x" * 200)) <= 128


def p07() -> bool:  # a hostile correlation id never reaches the wire of the SDK transport
    seen: list[dict] = []

    def signed(url, body, headers, timeout):  # type: ignore[no-untyped-def]
        seen.append(dict(headers))
        return OK_ANSWER

    gate = HttpGate("http://x.invalid", signed_transport=signed)
    GateClient(gate, "agent-1").check("pay", {}, correlation_id="a\r\nInjected: 1")
    h = seen[0] if seen else {}
    return bool(h) and all("\n" not in v and "\r" not in v for v in h.values())


def p08() -> bool:  # oversized args on a money tool: not sent, tool does not run
    spy = Spy()
    ran = _run_tool(
        _tool(spy, max_payload_bytes=1000, risk_classes={"pay": "money"}),
        args={"blob": "x" * 5000},
    )
    return not ran and spy.calls == []


def p09() -> bool:  # oversized args, plain tool, open mode: marked, gate not called
    spy = Spy()
    a = GateClient(spy, "agent-1", fail_mode="open", max_payload_bytes=1000).check(
        "lookup", {"blob": "x" * 5000}
    )
    return a.allow and a.rule_id == "SDK-UNINSPECTED" and spy.calls == []


def p10() -> bool:  # oversized HTTP request
    spy = Spy()
    app_calls: list[int] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        app_calls.append(1)

    mw = SupervisorASGIMiddleware(app, gate=spy, agent_id="agent-1", max_request_bytes=100)
    status, _, _ = asyncio.run(_asgi(mw, b"x" * 1000))
    return status == 413 and not app_calls and spy.calls == []


def p11() -> bool:  # oversized response is refused, nothing of it leaks
    mw = SupervisorASGIMiddleware(
        _echo_app(b"SECRET" * 100, b"text/plain"),
        gate=Spy(),
        agent_id="agent-1",
        max_response_bytes=100,
    )
    status, _, body = asyncio.run(_asgi(mw, b"{}"))
    return status == 502 and b"SECRET" not in body


def p12() -> bool:  # unicode tool names become names the route accepts
    names = ["chuyển tiền", "转账", "\U0001f4b8pay", "tool\u0000x", "a b/c"]
    mapped = [safe_tool_name(n) for n in names]
    return all(ROUTE_ID.match(m) for m in mapped) and len(set(mapped)) == len(names)


def p13() -> bool:  # path traversal and empty names
    return all(ROUTE_ID.match(safe_tool_name(n)) for n in ("../../etc/passwd", "", "x" * 400))


def p14() -> bool:  # pause in the middle of a run (sync): that call and later ones stop
    n = {"i": 0}

    def fn(call: dict) -> Mapping[str, Any]:
        n["i"] += 1
        return PAUSE_ANSWER if n["i"] >= 3 else OK_ANSWER

    mw = _tool(Spy(fn))
    ran = []
    for _ in range(4):
        try:
            mw.wrap_tool_call(
                _Req({"name": "pay", "args": {}}), lambda r: ran.append(1) or _Msg("x")
            )
        except SupervisorPaused:
            pass
    return len(ran) == 1


def p15() -> bool:  # pause in the middle of a run (async guardrail)
    state = {"i": 0}

    def fn(call: dict) -> Mapping[str, Any]:
        state["i"] += 1
        return PAUSE_ANSWER if state["i"] >= 2 else OK_ANSWER

    g = SupervisorGuardrail(Spy(fn), "agent-1")
    stops = 0
    for _ in range(3):
        try:
            asyncio.run(g.async_pre_call_hook({}, None, {"messages": []}, "completion"))
        except SupervisorPaused:
            stops += 1
    return stops == 2


def p16() -> bool:  # gate answers with a string, a list, None
    for bad in ("allow", ["allow"], None):
        spy = Spy(lambda c, b=bad: b)  # type: ignore[misc,return-value]
        if GateClient(spy, "agent-1").check("pay", {}).allow:
            return False
    return True


def p17() -> bool:  # allow is the string "yes"
    spy = Spy(lambda c: {"allow": "yes", "action": "allow"})
    return not GateClient(spy, "agent-1").check("pay", {}).allow


def p18() -> bool:  # a transform answer with no values is a block
    spy = Spy(lambda c: {"allow": True, "action": "allow", "status": "transform"})
    return not _run_tool(_tool(spy))


def p19() -> bool:  # NUL, lone surrogate, huge ints in args: no exception
    spy = Spy()
    try:
        for args in ({"a": "\x00"}, {"a": "\ud800"}, {"a": 10**400}):
            _run_tool(_tool(spy), args=args)
    except Exception:  # noqa: BLE001
        return False
    return True


def p20() -> bool:  # 5000 levels of nesting: no exception, closed
    deep: dict = {}
    cur = deep
    for _ in range(5000):
        cur["a"] = {}
        cur = cur["a"]
    spy = Spy()
    return not _run_tool(_tool(spy), args=deep) and spy.calls == []


def p21() -> bool:  # hook: a 10 MB event is refused without calling the gate
    spy = Spy()
    big = json.dumps({"tool_name": "Bash", "tool_input": {"command": "x" * 10_000_000}})
    env = {"SUPERVISOR_URL": "http://x", "SUPERVISOR_AGENT_ID": "agent-1"}
    import io

    return hook.run(big, env, spy, io.StringIO(), io.StringIO()) == 2 and spy.calls == []


def p22() -> bool:  # hook: ANSI and newlines in a gate reason become one ASCII line
    import io

    bad = {"allow": False, "action": "block", "rule_id": "R", "reason": "x\n\x1b[31mredđ\n"}
    err = io.StringIO()
    env = {"SUPERVISOR_URL": "http://x", "SUPERVISOR_AGENT_ID": "agent-1"}
    code = hook.run(
        json.dumps({"tool_name": "Bash", "tool_input": {}}),
        env,
        Spy(lambda c: bad),
        io.StringIO(),
        err,
    )
    text = err.getvalue()
    return code == 2 and text.isascii() and text.count("\n") == 1 and "\x1b" not in text


def p23() -> bool:  # hook: event is a list, a number, or has the wrong types
    import io

    env = {"SUPERVISOR_URL": "http://x", "SUPERVISOR_AGENT_ID": "agent-1"}
    for raw in ("[]", "7", '{"tool_name": ["a"], "tool_input": {}}', "\x00\x01"):
        if hook.run(raw, env, Spy(), io.StringIO(), io.StringIO()) != 2:
            return False
    return True


def p24() -> bool:  # 40 threads: every call keeps its own correlation id
    spy = Spy()
    mw = _tool(spy)
    ids: list[str] = []

    def work() -> None:
        _run_tool(mw)

    threads = [threading.Thread(target=work) for _ in range(40)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    ids = [c["cid"] for c in spy.calls if c["direction"] == "input"]
    return len(ids) == 40 and len(set(ids)) == 40


def p25() -> bool:  # session id with CRLF in a header
    spy = Spy()
    mw = SupervisorASGIMiddleware(_echo_app(), gate=spy, agent_id="agent-1")
    asyncio.run(_asgi(mw, b"{}", [(b"x-session-id", b"s\r\ns")]))
    return "session_id" not in spy.calls[0]["ctx"]


def p26() -> bool:  # a block message never carries the arguments (no personal data in errors)
    block = {"allow": False, "action": "block", "rule_id": "R", "reason": "no", "status": "block"}
    spy = Spy(lambda c: block)
    try:
        _tool(spy).wrap_tool_call(
            _Req({"name": "pay", "args": {"phone": "0912345678"}}), lambda r: _Msg("x")
        )
    except SupervisorBlocked as exc:
        return "0912345678" not in str(exc) and "0912345678" not in json.dumps(exc.decision)
    return False


PROBES: list[tuple[str, str, str, Callable[[], bool]]] = [
    ("P01", "langgraph", "consumer id with a newline is dropped", p01),
    ("P02", "litellm", "consumer id of 129 characters is dropped", p02),
    ("P03", "fastapi", "consumer id with non-ASCII bytes is dropped", p03),
    ("P04", "langgraph", "consumer id that is an object is dropped", p04),
    ("P05", "fastapi", "CRLF in the inbound correlation id is replaced", p05),
    ("P06", "fastapi", "200 character correlation id is replaced", p06),
    ("P07", "sdk", "hostile correlation id never reaches the transport headers", p07),
    ("P08", "langgraph", "oversized args on a money tool: not sent, tool stops", p08),
    ("P09", "common", "oversized args, plain tool, open mode: marked pass, not sent", p09),
    ("P10", "fastapi", "oversized request is 413, app and gate not called", p10),
    ("P11", "fastapi", "oversized response is refused, nothing leaks", p11),
    ("P12", "common", "unicode tool names map to accepted, distinct names", p12),
    ("P13", "common", "traversal, empty and long tool names are accepted names", p13),
    ("P14", "langgraph", "pause in the middle of a run stops that call and later ones", p14),
    ("P15", "litellm", "pause in the middle of an async run stops later calls", p15),
    ("P16", "common", "string, list, None answers fail closed", p16),
    ("P17", "common", "allow as the string yes fails closed", p17),
    ("P18", "langgraph", "transform answer without values is a block", p18),
    ("P19", "langgraph", "NUL, lone surrogate and huge integers do not raise", p19),
    ("P20", "langgraph", "5000 levels of nesting: closed, no crash, gate not called", p20),
    ("P21", "hook", "10 MB hook event refused without a gate call", p21),
    ("P22", "hook", "ANSI and newlines in a reason become one ASCII line", p22),
    ("P23", "hook", "malformed hook events exit 2", p23),
    ("P24", "langgraph", "40 threads keep distinct correlation ids", p24),
    ("P25", "fastapi", "session id with CRLF is dropped", p25),
    ("P26", "langgraph", "a block message carries no argument value", p26),
]


def run_probes() -> dict[str, Any]:
    rows = []
    for pid, adapter, text, fn in PROBES:
        try:
            ok = bool(fn())
        except Exception as exc:  # noqa: BLE001 - a probe that raises has failed
            ok = False
            text = f"{text} (raised {type(exc).__name__})"
        rows.append({"id": pid, "adapter": adapter, "text": text, "ok": ok})
    n, k = len(rows), sum(r["ok"] for r in rows)
    return {
        "n": n,
        "pass": k,
        "pass_bp": k * 10000 // n,
        "failed": [r["id"] for r in rows if not r["ok"]],
        "rows": rows,
    }
