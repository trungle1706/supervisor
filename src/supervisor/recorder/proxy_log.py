"""Proxy log reader for black-box agents (source ``proxy``).

A black-box agent cannot emit spans. A proxy in front of its tool or LLM calls (API
gateway, MCP proxy, reverse proxy) writes one JSON object per call to a JSONL file. The
format is in ``docs/recorder.md``. Required keys: ``ts`` (RFC 3339), ``agent_id``,
``request_id``, ``kind`` (tool_call | llm_call | message | handoff). Optional: ``session_id``,
``agent_version``, ``tool``, ``args``, ``result``, ``status``, ``latency_ms``,
``amount_minor`` (integer), ``currency``, ``env``.

Each line becomes a ``SpanData`` and goes through the same ``Normaliser`` (same masking,
same capture levels). The field set is reduced: no parent span, no caller agent, no gate
decision on the span, ids derived from ``request_id``/``session_id``. One ``trace_coverage``
row per agent records that reduced capability.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from supervisor.core.canonical import CanonicalError, parse_ts, sha256_hex
from supervisor.recorder.normalise import (
    A_AGENT_ID,
    A_AGENT_VERSION,
    A_AMOUNT,
    A_ARGS,
    A_CURRENCY,
    A_ENV,
    A_EVENT_TYPE,
    A_RESULT,
    A_STATUS,
    A_TOOL,
    EVENT_TYPES,
    Normalised,
    Normaliser,
    SpanData,
    datetime_to_ns,
)

COVERAGE_TABLE = "trace_coverage"
PROXY_MISSING = (
    "parent_span_id",
    "caller_agent_id",
    "llm_prompt_structure",
    "gate_decision_on_span",
    "in_agent_reasoning",
)
REQUIRED = ("ts", "agent_id", "request_id", "kind")


class ProxyLogError(ValueError):
    pass


@dataclass
class ProxyReadResult:
    items: list[Normalised] = field(default_factory=list)
    coverage: list[dict[str, Any]] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)  # (line number, message)


def _hex(prefix: str, value: str, n: int) -> str:
    return hashlib.sha256(f"{prefix}:{value}".encode()).hexdigest()[:n]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def proxy_line_to_span(rec: Mapping[str, Any]) -> SpanData:
    """One proxy log object -> SpanData. Raises ProxyLogError on a bad line."""
    missing = [k for k in REQUIRED if not rec.get(k)]
    if missing:
        raise ProxyLogError(f"missing required keys {missing}")
    kind = str(rec["kind"])
    if kind not in EVENT_TYPES or kind == "gate_decision":
        raise ProxyLogError(f"kind must be tool_call, llm_call, message or handoff, not {kind!r}")
    try:
        ts = parse_ts(str(rec["ts"]))
    except ValueError as exc:
        raise ProxyLogError(f"ts is not RFC 3339: {rec['ts']!r}") from exc
    amount = rec.get("amount_minor")
    if amount is not None and type(amount) is not int:
        raise ProxyLogError("amount_minor must be an integer (minor units), not a float or text")
    latency = rec.get("latency_ms")
    if latency is not None and type(latency) is not int:
        raise ProxyLogError("latency_ms must be an integer")
    request_id = str(rec["request_id"])
    start = datetime_to_ns(ts)
    attrs: dict[str, Any] = {
        A_AGENT_ID: str(rec["agent_id"]),
        A_EVENT_TYPE: kind,
        "supervisor.proxy.request_id": request_id,
    }
    optional = {
        A_AGENT_VERSION: rec.get("agent_version"),
        A_TOOL: rec.get("tool"),
        A_ARGS: _text(rec.get("args")),
        A_RESULT: _text(rec.get("result")),
        A_STATUS: rec.get("status"),
        A_CURRENCY: rec.get("currency"),
        A_ENV: rec.get("env"),
        A_AMOUNT: amount,
    }
    attrs.update({k: v for k, v in optional.items() if v is not None and v != ""})
    if kind == "tool_call" and rec.get("args") is not None and isinstance(rec["args"], Mapping):
        try:
            attrs["supervisor.args_hash"] = sha256_hex(dict(rec["args"]))  # as the agent SDK
        except CanonicalError:
            pass  # not canonical (e.g. money as float): hash of the text (normaliser default)
    return SpanData(
        trace_id=_hex("proxy-trace", str(rec.get("session_id") or request_id), 32),
        span_id=_hex("proxy-span", request_id, 16),
        parent_span_id=None,
        name=f"proxy {kind}",
        kind="INTERNAL",
        start_ns=start,
        end_ns=start + latency * 1_000_000 if latency is not None else None,
        attributes=attrs,
    )


def coverage_row(agent_id: str, first_seen: datetime) -> dict[str, Any]:
    """The reduced-capability marker for an agent seen through the proxy log."""
    missing = list(PROXY_MISSING)
    cid = _hex("coverage", f"{agent_id}|proxy|reduced|{','.join(missing)}", 32)
    return {
        "coverage_id": cid,
        "ts": first_seen,
        "agent_id": agent_id,
        "source": "proxy",
        "capability": "reduced",
        "missing": missing,
        "note": "black-box agent: events from a proxy log; no span tree, no in-agent detail",
    }


def iter_lines(path: Path) -> Iterator[tuple[int, str]]:
    with Path(path).open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            if line.strip():
                yield n, line


def read_proxy_lines(lines: Iterable[tuple[int, str]], normaliser: Normaliser) -> ProxyReadResult:
    out = ProxyReadResult()
    first_seen: dict[str, datetime] = {}
    for n, line in lines:
        try:
            rec = json.loads(line)
            if not isinstance(rec, Mapping):
                raise ProxyLogError("line must be a JSON object")
            item = normaliser.normalise(proxy_line_to_span(rec), "proxy")
        except (ValueError, ProxyLogError) as exc:
            out.errors.append((n, str(exc)))
            continue
        if item is None:
            out.errors.append((n, "not an agent event"))
            continue
        out.items.append(item)
        ev = item.event
        if ev.agent_id not in first_seen or ev.ts < first_seen[ev.agent_id]:
            first_seen[ev.agent_id] = ev.ts
    out.coverage = [coverage_row(a, t) for a, t in sorted(first_seen.items())]
    return out


def read_proxy_log(path: Path, normaliser: Normaliser) -> ProxyReadResult:
    return read_proxy_lines(iter_lines(path), normaliser)


class ProxyLogSource:
    """``TraceSource`` over one proxy log file: yields agent_event rows (dicts)."""

    def __init__(self, path: Path, normaliser: Normaliser) -> None:
        self.path = Path(path)
        self.normaliser = normaliser

    def read(self, since: datetime | None = None) -> Iterable[Mapping[str, Any]]:
        res = read_proxy_log(self.path, self.normaliser)
        return [i.event.row() for i in res.items if since is None or i.event.ts >= since]
