"""Signals: the one flat shape the rule engine reads (WP21).

A ``Signal`` is a gate decision, a state change, a judge verdict, a scheduler job run, a
chain verify result, an ingress rejection, a fail-mode drill result or a case. Each has a
unique ``sid``, a timestamp, a few filterable ``fields`` (enums, ids, small ints, bools; no
free text) and, when it came from the evidence chain, its lane, seq and entry hash so an
alert can point at the evidence.

Loaders: ``load_signals`` reads the live store between two instants (chain entries by record
type, tier 2 verdicts, scheduler job state); ``read_jsonl`` reads the fixture format used by
the harness and by ``python -m supervisor.alerts test --signals FILE``.

Ingress rejections come from WP20's ``console_action`` audit rows (WP20 writes no chain
record for them); an ``ingress_reject`` chain record, if a later version writes one, is read
too.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from supervisor.analytics.decisions import DETECTOR_FAILED_REASONS, finding_class
from supervisor.monitors.common import MonitorContext, as_dt, read_range

log = logging.getLogger("supervisor.alerts")

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


# WP20 (ingress auth) writes each rejection as a ``console_action`` row (permission
# ``ingress.auth``, outcome ``denied``, ``target_id`` = the claimed agent, ``detail`` =
# ``<reason>`` or ``<reason>;suppressed=<n>`` when its audit throttle skipped n rows), not as a
# chain record. The claimed agent id is unverified input: kept only when it looks like an id.
INGRESS_PERMISSION = "ingress.auth"
MAX_INGRESS_WEIGHT = 1000  # throttled rows expand to at most this many signals
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:@-]{1,128}$")
_SAFE_REASON = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


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
    derived: bool = False  # WP39: built from other records (request, finding, gap); not "judged"

    @property
    def agent_id(self) -> str | None:
        v = self.fields.get("agent_id")
        return str(v) if v else None

    def order_key(self) -> tuple[datetime, str, str]:
        return (self.ts, self.kind, self.sid)


def _fields_from_chain(kind: str, record_type: str, p: Mapping[str, Any]) -> dict[str, Any]:
    if kind == "gate_decision":
        ne = [str(x) for x in (p.get("not_executed") or [])]
        lat = p.get("latency_us")
        return {
            "agent_id": p.get("agent_id"),
            "action": p.get("action"),
            "rule_id": p.get("rule_id"),
            "allow": bool(p.get("allow")),
            # WP39: verdict v2 facts (None on a record written without detectors)
            "status": p.get("status"),
            "direction": p.get("direction"),
            "agent_state": p.get("agent_state"),
            "detector_failed": any(x.rpartition(":")[2] in DETECTOR_FAILED_REASONS for x in ne),
            "not_evaluated": bool(ne),
            "correlation_id": p.get("correlation_id"),
            "latency_us": int(lat) if isinstance(lat, int) and not isinstance(lat, bool) else None,
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


def load_signals(
    ctx: MonitorContext,
    ts_from: datetime,
    ts_to: datetime,
    *,
    gap_window_s: int | None = None,
) -> list[Signal]:
    """All signals with ``ts_from <= ts < ts_to``, in a deterministic order. With
    ``gap_window_s`` the coverage-gap check (agents seen with no gate decision) also runs."""
    out: list[Signal] = []
    state_of: dict[str, str] = {}  # decision id -> agent state at the decision (WP39)
    for e in read_range(ctx, "chain_entry", ts_from, ts_to):
        kind = CHAIN_KINDS.get(str(e["record_type"]))
        if kind is None:
            continue
        rows = ctx.tables.query("chain_payload", {"lane": e["lane"], "seq": e["seq"]})
        p = json.loads(rows[0]["payload"]) if rows else {}
        if kind == "gate_decision":
            state_of[str(e["record_ref"])] = str(p.get("agent_state") or "")
            out.append(_request_signal(f"{e['lane']}:{e['seq']}", as_dt(e["ts"]), p))
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
    ingress = _ingress_rejects(ctx, ts_from, ts_to)
    out.extend(ingress)
    out.extend(_ingress_requests(ingress))
    out.extend(_finding_signals(ctx, ts_from, ts_to, state_of))
    if gap_window_s:
        out.extend(_coverage_gaps(ctx, ts_to, gap_window_s))
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


def _ingress_rejects(ctx: MonitorContext, ts_from: datetime, ts_to: datetime) -> list[Signal]:
    """WP20 rejection audit rows as ``ingress_reject`` signals. A row that stands for n
    throttled rejections as well (``;suppressed=n``) gives 1 + n signals at its time, so a
    burst rule still counts every rejection."""
    out: list[Signal] = []
    where = {"permission": INGRESS_PERMISSION, "outcome": "denied"}
    for row in read_range(ctx, "console_action", ts_from, ts_to, where):
        reason, _, rest = str(row.get("detail") or "").partition(";")
        skipped = 0
        if rest.startswith("suppressed="):
            try:
                skipped = max(0, int(rest[len("suppressed=") :]))
            except ValueError:
                skipped = 0
        claimed = row.get("target_id") if row.get("target_kind") == "agent" else None
        agent = str(claimed) if claimed and _SAFE_ID.match(str(claimed)) else None
        fields = {
            "agent_id": agent,
            "reason_code": reason if _SAFE_REASON.match(reason) else "unknown",
        }
        ts = as_dt(row["ts"])
        for k in range(1 + min(skipped, MAX_INGRESS_WEIGHT - 1)):
            sid = f"ingress:{row['action_id']}" + (f"#{k}" if k else "")
            out.append(Signal(sid=sid, kind="ingress_reject", ts=ts, fields=fields))
    return out


# --------------------------------------------------------------------------- WP39 signals

_CLIENT_ERROR_STATUS = {401: "rejected_401", 403: "rejected_403"}


def _request_signal(sid: str, ts: datetime, p: Mapping[str, Any]) -> Signal:
    """One ``gate_request`` per gate decision. HTTP statuses of the gate routes are not stored;
    a decision made by the fail mode (the gate could not decide) is the server-side error."""
    return Signal(
        sid=f"req:{sid}",
        kind="gate_request",
        ts=ts,
        derived=True,
        fields={
            "agent_id": p.get("agent_id"),
            "outcome_class": "gate_error" if p.get("fail_mode") else "ok",
            "reason_code": None,
            "correlation_id": p.get("correlation_id"),
        },
    )


def _ingress_requests(ingress: list[Signal]) -> list[Signal]:
    """Each rejected ingress call is a failed request on a gate route (401 or 403 here)."""
    from supervisor.gateway.ingress_auth import REASONS

    out = []
    for s in ingress:
        status = REASONS.get(str(s.fields.get("reason_code")), (401, ""))[0]
        out.append(
            Signal(
                sid=f"req:{s.sid}",
                kind="gate_request",
                ts=s.ts,
                derived=True,
                fields={
                    "agent_id": s.fields.get("agent_id"),
                    "outcome_class": _CLIENT_ERROR_STATUS.get(status, "rejected_4xx"),
                    "reason_code": s.fields.get("reason_code"),
                    "correlation_id": None,
                },
            )
        )
    return out


def _finding_signals(
    ctx: MonitorContext, ts_from: datetime, ts_to: datetime, state_of: Mapping[str, str]
) -> list[Signal]:
    """One ``gate_finding`` per fired finding row. ``enforcement`` is ``shadow`` when the agent
    was in SHADOW at the decision (nothing is enforced there) and ``enforced`` otherwise;
    ``observe`` is reserved for the policy observe mode of a later package."""
    out = []
    for f in read_range(ctx, "finding", ts_from, ts_to):
        if f.get("not_executed_reason"):
            continue
        state = state_of.get(str(f["event_id"]), "")
        out.append(
            Signal(
                sid=f"finding:{f['finding_id']}",
                kind="gate_finding",
                ts=as_dt(f["ts"]),
                derived=True,
                fields={
                    "agent_id": f["agent_id"],
                    "code": str(f["code"]),
                    "finding_class": finding_class(str(f["code"])),
                    "direction": f["direction"],
                    "detector_slug": f["detector_slug"],
                    "action_hint": f["action_hint"],
                    "enforcement": "shadow" if state == "SHADOW" else "enforced",
                    "is_mock": bool(f["is_mock"]),
                    "correlation_id": f.get("correlation_id"),
                },
            )
        )
    return out


def _coverage_gaps(ctx: MonitorContext, now: datetime, window_s: int) -> list[Signal]:
    """Agents seen in traces (any recorded event) or in the inventory during the last
    ``window_s`` seconds that have NO gate decision in the same window: the agent reaches its
    tools without passing the gate (a bypass or a mis-wired collector). One signal per agent,
    stamped ``now`` (the read watermark) with an id that changes once per window."""
    lo = now - timedelta(seconds=window_s)
    events = read_range(ctx, "agent_event", lo, now)
    decided = {str(e["agent_id"]) for e in events if e["event_type"] == "gate_decision"}
    seen: dict[str, str] = {}
    for e in events:
        if e["event_type"] != "gate_decision":
            seen.setdefault(str(e["agent_id"]), "trace")
    try:
        for n in ctx.state.query("inventory_node", {"kind": "system", "status": "active"}):
            name = str(n["name"])
            if not name.startswith("app:") and lo < as_dt(n["last_seen"]) <= now:
                seen.setdefault(name, "inventory")
    except Exception as exc:  # noqa: BLE001 - no inventory table: traces only
        log.debug("coverage gap: inventory not read (%s)", type(exc).__name__)
    registered = {str(a["agent_id"]) for a in ctx.state.query("agent")}
    bucket = int(now.timestamp()) // max(1, window_s)
    return [
        Signal(
            sid=f"gap:{agent}:{bucket}",
            kind="coverage_gap",
            ts=now,
            derived=True,
            fields={
                "agent_id": agent,
                "seen_in": where,
                "registered": agent in registered,
            },
        )
        for agent, where in sorted(seen.items())
        if agent not in decided and _SAFE_ID.match(agent)
    ]


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
