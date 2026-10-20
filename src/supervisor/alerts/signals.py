"""Signals: the one flat shape the rule engine reads (WP21).

A ``Signal`` is a gate decision, a state change, a judge verdict, a scheduler job run, a
chain verify result, an ingress rejection, a fail-mode drill result or a case. Each has a
unique ``sid``, a timestamp, a few filterable ``fields`` (enums, ids, small ints, bools; no
free text) and, when it came from the evidence chain, its lane, seq and entry hash so an
alert can point at the evidence.

Loaders: ``load_signals`` reads the live store between two instants (chain entries by record
type, tier 2 verdicts, scheduler job state); ``read_jsonl`` reads the fixture format used by
the harness and by ``python -m supervisor.alerts test --signals FILE``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from supervisor.monitors.common import MonitorContext, as_dt, read_range

# chain record_type -> signal kind
CHAIN_KINDS = {
    "gate_decision": "gate_decision",
    "gate_state_change": "gate_state_change",
    "ingress_reject": "ingress_reject",
    "chain_verify": "chain_verify",
    "audit_pack_built": "chain_verify",
    "failmode_drill": "failmode_drill",
    "case": "case",
    "case_opened": "case",
}


@dataclass(frozen=True)
class Signal:
    sid: str
    kind: str
    ts: datetime
    fields: Mapping[str, Any] = field(default_factory=dict)
    lane: str | None = None
    seq: int | None = None
    entry_hash: str | None = None
    case_id: str | None = None

    @property
    def agent_id(self) -> str | None:
        v = self.fields.get("agent_id")
        return str(v) if v else None

    def order_key(self) -> tuple[datetime, str, str]:
        return (self.ts, self.kind, self.sid)


def _fields_from_chain(kind: str, record_type: str, p: Mapping[str, Any]) -> dict[str, Any]:
    if kind == "gate_decision":
        return {
            "agent_id": p.get("agent_id"),
            "action": p.get("action"),
            "rule_id": p.get("rule_id"),
            "allow": bool(p.get("allow")),
        }
    if kind == "gate_state_change":
        return {
            "agent_id": p.get("agent_id"),
            "event": p.get("event"),
            "to_state": p.get("to_state"),
        }
    if kind == "ingress_reject":
        return {"agent_id": p.get("agent_id"), "reason_code": p.get("reason_code")}
    if kind == "chain_verify":
        ok = p["ok"] if "ok" in p else p.get("verify_ok")
        return {"ok": bool(ok)}
    if kind == "failmode_drill":
        return {"ok": bool(p.get("ok"))}
    return {"agent_id": p.get("agent_id"), "severity": p.get("severity")}  # case


def load_signals(ctx: MonitorContext, ts_from: datetime, ts_to: datetime) -> list[Signal]:
    """All signals with ``ts_from <= ts < ts_to``, in a deterministic order."""
    out: list[Signal] = []
    for e in read_range(ctx, "chain_entry", ts_from, ts_to):
        kind = CHAIN_KINDS.get(str(e["record_type"]))
        if kind is None:
            continue
        rows = ctx.tables.query("chain_payload", {"lane": e["lane"], "seq": e["seq"]})
        p = json.loads(rows[0]["payload"]) if rows else {}
        out.append(
            Signal(
                sid=f"{e['lane']}:{e['seq']}",
                kind=kind,
                ts=as_dt(e["ts"]),
                fields=_fields_from_chain(kind, str(e["record_type"]), p),
                lane=str(e["lane"]),
                seq=int(e["seq"]),
                entry_hash=str(e["entry_hash"]),
                case_id=p.get("case_id"),
            )
        )
    for v in read_range(ctx, "verdict", ts_from, ts_to, {"tier": 2}):
        out.append(
            Signal(
                sid=f"verdict:{v['verdict_id']}",
                kind="verdict",
                ts=as_dt(v["ts"]),
                fields={
                    "agent_id": v["agent_id"],
                    "tier": int(v["tier"]),
                    "label": v["label"],
                    "action": v["action"],
                    "rule_id": v.get("rule_id"),
                    "is_mock": bool(v["is_mock"]),
                },
            )
        )
    for row in ctx.state.query("monitor_state", {"monitor": "scheduler"}):
        key = str(row["state_key"])
        if not key.startswith("last:"):
            continue
        val = row["value"]
        if isinstance(val, str):
            val = json.loads(val)
        if not val.get("ts"):
            continue
        ts = as_dt(val["ts"])
        if ts_from <= ts < ts_to:
            job = key[5:]
            out.append(
                Signal(
                    sid=f"job:{job}@{val['ts']}",
                    kind="job_run",
                    ts=ts,
                    fields={"job": job, "status": val.get("status")},
                )
            )
    out.sort(key=Signal.order_key)
    return out


def read_jsonl(path: Path) -> list[Signal]:
    """Fixture format, one object per line: ``{"id", "kind", "ts", "f": {...}}`` plus the
    optional ``lane``, ``seq``, ``entry_hash``, ``case_id`` and ``label`` (ignored here)."""
    out: list[Signal] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out.append(
            Signal(
                sid=str(d["id"]),
                kind=str(d["kind"]),
                ts=as_dt(d["ts"]),
                fields=dict(d.get("f") or {}),
                lane=d.get("lane"),
                seq=d.get("seq"),
                entry_hash=d.get("entry_hash"),
                case_id=d.get("case_id"),
            )
        )
    out.sort(key=Signal.order_key)
    return out


def sorted_signals(signals: Iterable[Signal]) -> list[Signal]:
    return sorted(signals, key=Signal.order_key)


__all__ = ["CHAIN_KINDS", "Signal", "load_signals", "read_jsonl", "sorted_signals"]
