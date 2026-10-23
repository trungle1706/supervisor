"""Agent-side SDK: gate hooks (in-process and HTTP) and the ``supervised_tool`` decorator.

Fail closed: no gate, no call. ``check`` on a hook never raises.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import inspect
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, TypeVar
from urllib.parse import urlparse

from supervisor.core.ports import GateHook
from supervisor.gateway.ingress_sign import IngressCredential

F = TypeVar("F", bound=Callable[..., Any])

Transport = Callable[[str, dict[str, Any], float], Mapping[str, Any]]
# WP20: a signed call sends exact bytes plus headers: (url, body, headers, timeout_s) -> JSON.
SignedTransport = Callable[[str, bytes, Mapping[str, str], float], Mapping[str, Any]]


class SupervisorBlocked(Exception):
    """The gate refused the call. ``decision`` holds the gate's answer."""

    def __init__(self, decision: Mapping[str, Any]) -> None:
        self.decision = dict(decision)
        rule = self.decision.get("rule_id")
        reason = self.decision.get("reason", "blocked")
        super().__init__(f"blocked by supervisor ({rule}): {reason}")


class SupervisorPaused(SupervisorBlocked):
    """The gate paused the agent (or the agent was already paused)."""


def _with_ids(
    context: Mapping[str, Any] | None, session_id: str | None, consumer_id: str | None
) -> Mapping[str, Any] | None:
    """WP-P2: put session_id and consumer_id into the context when given (None: unchanged)."""
    if session_id is None and consumer_id is None:
        return context
    out = dict(context or {})
    if session_id is not None:
        out["session_id"] = session_id
    if consumer_id is not None:
        out["consumer_id"] = consumer_id
    return out


def _closed_decision(rule_id: str, reason: str, t0: float) -> dict[str, Any]:
    return {
        "allow": False,
        "action": "block",
        "rule_id": rule_id,
        "reason": reason,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }


class InProcessGate:
    """GateHook that calls a ``Gateway`` in the same process."""

    def __init__(self, gateway: Any) -> None:
        self.gateway = gateway

    def check(
        self,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        return self.check_v2(agent_id, agent_version, tool_name, args, context)

    def check_v2(
        self,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
        *,
        direction: str = "input",
        correlation_id: str | None = None,
        session_id: str | None = None,
        consumer_id: str | None = None,
    ) -> Mapping[str, Any]:
        """``check`` plus ``direction`` and ``correlation_id`` (WP38 adapters), and
        ``session_id`` / ``consumer_id`` (WP-P2, sent in the context)."""
        context = _with_ids(context, session_id, consumer_id)
        t0 = time.perf_counter()
        try:
            if direction == "input" and correlation_id is None:
                return self.gateway.check(agent_id, agent_version, tool_name, args, context)
            if not getattr(self.gateway, "detectors_on", False) and direction != "input":
                # the HTTP route answers 400 here; in process the output check would be run as a
                # tool call, which is wrong. Fail closed.
                return _closed_decision("GATE-DIRECTION", "direction=output needs detectors", t0)
            return self.gateway.check(
                agent_id,
                agent_version,
                tool_name,
                args,
                context,
                direction=direction,
                correlation_id=correlation_id,
            )
        except Exception:  # noqa: BLE001 - the hook must never raise
            return _closed_decision("GATE-ERROR", "gateway error: fail closed", t0)


def _default_transport(url: str, payload: dict[str, Any], timeout_s: float) -> Mapping[str, Any]:
    from supervisor.adapters.http_json import post_json

    return post_json(url, payload, timeout_s)


def _default_signed_transport(
    url: str, body: bytes, headers: Mapping[str, str], timeout_s: float
) -> Mapping[str, Any]:
    from supervisor.adapters.http_json import post_bytes

    return post_bytes(url, body, dict(headers), timeout_s)


# Same value as gateway.detector_gate.CORRELATION_HEADER (a test keeps them equal); the SDK must
# not import the server side.
CORRELATION_HEADER = "X-Supervisor-Correlation-Id"
GATE_PATH = "/v1/gate/check"
LEGACY_GATE_PATH = "/gate/check"  # deprecated alias, used only as a fallback on 404


class HttpGate:
    """GateHook that POSTs to ``{base_url}/v1/gate/check`` (D12); applies the fail mode locally.

    A base URL that already ends in ``/v1`` posts to ``{base_url}/gate/check`` (the same URL).
    A server that answers 404 on the versioned path (an older Supervisor) is retried once
    on the legacy ``/gate/check`` and the SDK then keeps using it. A signed request signs
    the path it actually sends (method + path are covered by the WP20 signature).

    With ``credential`` (WP20, ingress auth) every request carries the agent's signature or
    bearer token (``gateway/ingress_sign.py``) and goes through ``signed_transport``. Without
    it the request is sent as before. A 401/403 answer is a configuration fault, not an
    outage: it always fails closed (rule ``GATE-AUTH``), even for a read-only tool."""

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 2.0,
        transport: Transport | None = None,
        fail_modes: Mapping[str, str] | None = None,
        credential: IngressCredential | None = None,
        signed_transport: SignedTransport | None = None,
    ) -> None:
        self.credential = credential
        self.signed_transport: SignedTransport = signed_transport or _default_signed_transport
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.transport: Transport = transport or _default_transport
        # WP38 review: a caller's own ``transport`` (proxy, TLS settings, a test double) must not
        # be bypassed because an adapter adds the correlation header. Without a credential and
        # without a matching ``signed_transport`` the header is then not sent.
        self._own_transport_only = transport is not None and signed_transport is None
        self.fail_modes: dict[str, str] = dict(fail_modes or {})
        # A base URL that already ends in /v1 (a common setting) keeps working: /v1 + /gate/check.
        self.versioned = not self.base_url.endswith("/v1")
        self.gate_path = GATE_PATH if self.versioned else LEGACY_GATE_PATH

    def _fallback(self, tool_name: str, t0: float) -> dict[str, Any]:
        latency = int((time.perf_counter() - t0) * 1000)
        if self.fail_modes.get(tool_name) == "read_only":
            return {
                "allow": True,
                "action": "alert",
                "rule_id": "GATE-UNREACHABLE",
                "reason": "gateway unreachable: fail open (read only)",
                "latency_ms": latency,
            }
        return _closed_decision("GATE-UNREACHABLE", "gateway unreachable: fail closed", t0)

    def check(
        self,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        return self.check_v2(agent_id, agent_version, tool_name, args, context)

    def check_v2(
        self,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
        *,
        direction: str = "input",
        correlation_id: str | None = None,
        session_id: str | None = None,
        consumer_id: str | None = None,
    ) -> Mapping[str, Any]:
        """``check`` plus ``direction`` and ``correlation_id`` (WP38), sent only when set:
        ``direction`` as a body field when it is not ``input`` (an older server rejects
        unknown fields), the correlation id as the ``X-Supervisor-Correlation-Id`` header.
        WP-P2: ``session_id`` and ``consumer_id`` go into ``context`` (session monitor)."""
        context = _with_ids(context, session_id, consumer_id)
        t0 = time.perf_counter()
        payload: dict[str, Any] = {
            "agent_id": agent_id,
            "agent_version": agent_version,
            "tool_name": tool_name,
            "args": dict(args),
            "context": dict(context) if context is not None else None,
        }
        if direction != "input":
            payload["direction"] = direction
        try:
            result = self._call(
                payload, {CORRELATION_HEADER: correlation_id} if correlation_id else None
            )
            if not isinstance(result, Mapping) or not isinstance(result.get("allow"), bool):
                return self._fallback(tool_name, t0)
            out = dict(result)
            out["latency_ms"] = int(out.get("latency_ms") or 0)
            return out
        except Exception as exc:  # noqa: BLE001 - timeouts and transport errors: fail mode
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (401, 403):
                return _closed_decision("GATE-AUTH", "gateway refused the credential", t0)
            return self._fallback(tool_name, t0)

    def _send(
        self, path: str, payload: dict[str, Any], extra: Mapping[str, str] | None = None
    ) -> Mapping[str, Any]:
        url = f"{self.base_url}{path}"
        if self.credential is None and (not extra or self._own_transport_only):
            return self.transport(url, payload, self.timeout_s)
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode()
        headers = (
            self.credential.headers_for("POST", urlparse(url).path, body)
            if self.credential is not None
            else {}
        )
        headers.update(extra or {})
        headers["Content-Type"] = "application/json"
        return self.signed_transport(url, body, headers, self.timeout_s)

    def _call(
        self, payload: dict[str, Any], extra: Mapping[str, str] | None = None
    ) -> Mapping[str, Any]:
        """Run the transport with a hard deadline, even if the transport ignores it."""
        box: dict[str, Any] = {}

        def run() -> None:
            try:
                try:
                    box["value"] = self._send(self.gate_path, payload, extra)
                except Exception as exc:  # noqa: BLE001
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    if status != 404 or not self.versioned or self.gate_path != GATE_PATH:
                        raise
                    box["value"] = self._send(LEGACY_GATE_PATH, payload, extra)
                    self.gate_path = LEGACY_GATE_PATH  # an older server: stop probing
            except BaseException as exc:  # noqa: BLE001
                box["error"] = exc

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(self.timeout_s)
        if worker.is_alive():
            raise TimeoutError("gateway call timed out")
        if "error" in box:
            raise box["error"]
        return box["value"]  # type: ignore[no-any-return]


_default_gate: GateHook | None = None

# WP24b: apply the gate's ``transformed_args`` (masked copy of the arguments of a pii_export
# tool) before the tool runs. Off by default. ``set_inline_redaction(None)`` falls back to the
# INLINE_REDACTION_ENABLED environment variable (1/true/yes/on).
INLINE_REDACTION_ENABLED = False
log = logging.getLogger("supervisor.gateway.sdk")
_warned_inline = False


def warn_inline_once() -> None:
    """One warning per process when the local switch is on. The SDK cannot see the server
    flag: if the gateway runs without INLINE_REDACTION_ENABLED, a pii_export tool still gets
    the original arguments, silently. Called at decoration time and by the MCP proxy."""
    global _warned_inline
    if _warned_inline:
        return
    _warned_inline = True
    log.warning(
        "inline redaction is ON in this process; it only has effect when the gateway server "
        "also runs with INLINE_REDACTION_ENABLED=1, otherwise pii_export tools get the "
        "original arguments"
    )


_warned_not_applied: set[str] = set()


def warn_not_applied_once(agent_id: str) -> None:
    """WP-P2: one warning per agent when the gate returned ``transformed_args`` and this process
    is configured not to apply them (INLINE_REDACTION_ENABLED is off here): the tool then gets
    the original arguments. The gate is told in ``context.redaction_applied`` (false) and shows
    it in the decision."""
    if agent_id in _warned_not_applied:
        return
    _warned_not_applied.add(agent_id)
    log.warning(
        "the gate masked the arguments of agent %s but inline redaction is OFF in this process "
        "(INLINE_REDACTION_ENABLED): the tool gets the original arguments. Switch it on on the "
        "agent side too; see docs/collectors.md",
        agent_id,
    )


# WP-P2: session and consumer id for the session monitor, without a GateHook wrapper of your own.
_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "supervisor_session_id", default=None
)
_consumer_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "supervisor_consumer_id", default=None
)


def set_session(session_id: str | None, consumer_id: str | None = None) -> None:
    """Set the session (and consumer) id for the current thread or async task."""
    _session_id.set(session_id)
    _consumer_id.set(consumer_id)


@contextlib.contextmanager
def supervised_session(session_id: str | None, consumer_id: str | None = None) -> Any:
    """``with supervised_session(sid, consumer): ...`` sets both ids for the calls inside."""
    t1, t2 = _session_id.set(session_id), _consumer_id.set(consumer_id)
    try:
        yield
    finally:
        _session_id.reset(t1)
        _consumer_id.reset(t2)


def _ids(value: Any, bound: Mapping[str, Any], fallback: str | None) -> str | None:
    """A decorator argument: text, or a callable taking no argument or the bound arguments."""
    if callable(value):
        try:
            value = value(bound)
        except TypeError:
            value = value()
    got = value if value is not None else fallback
    return str(got) if isinstance(got, str | int) and str(got) else None


_inline_override: bool | None = None


def set_inline_redaction(value: bool | None) -> None:
    global _inline_override
    _inline_override = value


def inline_redaction_on() -> bool:
    if _inline_override is not None:
        return _inline_override
    env = os.environ.get("INLINE_REDACTION_ENABLED", "").strip().lower()
    return INLINE_REDACTION_ENABLED or env in ("1", "true", "yes", "on")


def apply_transformed(
    sig: inspect.Signature,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    decision: Mapping[str, Any],
    agent_id: str | None = None,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """(args, kwargs) for the tool call: the gate's masked values when redaction is on and the
    decision carries ``transformed_args``; otherwise the original call, untouched."""
    transformed = decision.get("transformed_args")
    if isinstance(transformed, Mapping) and not inline_redaction_on():
        warn_not_applied_once(agent_id or str(decision.get("agent_id") or "agent"))  # WP-P2
    if not inline_redaction_on() or not isinstance(transformed, Mapping):
        return args, kwargs
    try:
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        for name, value in transformed.items():
            if name in bound.arguments:
                bound.arguments[name] = value
        return bound.args, bound.kwargs
    except TypeError:
        # cannot map the answer onto the signature: the safe choice is to refuse the call
        raise SupervisorBlocked(
            {
                "allow": False,
                "action": "block",
                "rule_id": "GATE-REDACTION",
                "reason": "inline redaction could not be applied: fail closed",
            }
        ) from None


def _documents_on() -> bool:
    from supervisor.gateway.adapters.attachments import intake_on

    return intake_on()


def set_default_gate(gate: GateHook | None) -> None:
    global _default_gate
    _default_gate = gate


def get_default_gate() -> GateHook | None:
    return _default_gate


def _enforce(decision: Mapping[str, Any]) -> None:
    if decision.get("allow") is True:
        return
    reason = str(decision.get("reason", ""))
    if decision.get("action") == "pause" or "paused" in reason.lower():
        raise SupervisorPaused(decision)
    raise SupervisorBlocked(decision)


def supervised_tool(
    agent_id: str,
    agent_version: str,
    tool_name: str,
    risk_class: str,
    gate: GateHook | None = None,
    documents_arg: str | None = None,
    session_id: str | Callable[..., str | None] | None = None,
    consumer_id: str | Callable[..., str | None] | None = None,
) -> Callable[[F], F]:
    """Decorator: ask the gate before the tool runs; do not run it unless allowed.

    ``documents_arg`` (WP-D1) names a parameter of the tool that holds the files the user attached
    (bytes, ``(name, bytes)`` pairs, ``pathlib.Path`` objects or document dicts). While
    ``DOCUMENT_INTAKE_ENABLED`` is on in this process the files go to the gate as
    ``context.documents`` and the parameter is left out of ``args``; with the switch off nothing
    changes.

    ``session_id`` and ``consumer_id`` (WP-P2) go to the gate as ``context.session_id`` and
    ``context.consumer_id`` for the session monitor. Each is a text, or a function that takes the
    bound arguments (or nothing) and returns the text; when it is not given the value set with
    ``set_session`` / ``supervised_session`` (a context variable) is used. Nothing is sent when
    there is none."""

    def resolve() -> GateHook:
        g = gate or _default_gate
        if g is None:
            raise SupervisorBlocked(
                {
                    "allow": False,
                    "action": "block",
                    "rule_id": "GATE-MISSING",
                    "reason": "no gate configured: fail closed",
                }
            )
        return g

    def decorate(fn: F) -> F:
        sig = inspect.signature(fn)

        def bind(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
            try:
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                return dict(bound.arguments)
            except TypeError:
                return dict(kwargs)

        context = {"declared_risk_class": risk_class}
        if risk_class == "pii_export" and inline_redaction_on():
            warn_inline_once()

        def call_context(bound_args: dict[str, Any]) -> dict[str, Any]:
            ctx = dict(context)
            sid = _ids(session_id, bound_args, _session_id.get())
            cid = _ids(consumer_id, bound_args, _consumer_id.get())
            if sid:
                ctx["session_id"] = sid
            if cid:
                ctx["consumer_id"] = cid
            if risk_class == "pii_export" and not inline_redaction_on():
                # WP-P2: this process will not apply masking (other tool classes keep the old
                # context; the warning still fires when masked arguments come back)
                ctx["redaction_applied"] = False
            return ctx

        def with_documents(
            bound_args: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            """(args, context) for the gate call. WP-D1: off, both are what they were."""
            ctx = call_context(bound_args)
            if documents_arg is None or not _documents_on():
                return bound_args, ctx
            from supervisor.gateway.adapters.attachments import to_documents

            args_ = dict(bound_args)
            found = to_documents(args_.pop(documents_arg, None))
            return args_, ({**ctx, "documents": found} if found else ctx)

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def awrapper(*args: Any, **kwargs: Any) -> Any:
                g = resolve()
                gate_args, gate_ctx = with_documents(bind(args, kwargs))
                decision = await asyncio.to_thread(
                    g.check, agent_id, agent_version, tool_name, gate_args, gate_ctx
                )
                _enforce(decision)
                args, kwargs = apply_transformed(sig, args, kwargs, decision, agent_id)
                return await fn(*args, **kwargs)

            return awrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            g = resolve()
            gate_args, gate_ctx = with_documents(bind(args, kwargs))
            decision = g.check(agent_id, agent_version, tool_name, gate_args, gate_ctx)
            _enforce(decision)
            args, kwargs = apply_transformed(sig, args, kwargs, decision, agent_id)
            return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorate
