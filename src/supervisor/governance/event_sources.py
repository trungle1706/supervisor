"""Event sources of the governance loop (WP-G5, docs/governance-actions.md section 2).

Read-only adapters over tables that already exist. Nothing is captured anew and nothing here
writes. Each source reads the rows with ``lo <= time < hi`` and returns normalised
``GovernanceEvent`` objects (severity from the source row or a fixed rule, ids only, no text).

=====================  ==================================================================
kind                   source
=====================  ==================================================================
alert                  ``alert`` rows (every rule id); severity of the alert
gate_stop              tier 0 ``verdict`` rows with action block or pause, on a tool whose
                       risk class is money, credit or pii_export; block high, pause medium
detector_failed        ``finding`` rows of a detector that did not run (execution_failed,
                       timed_out); one event per agent, detector and hour; medium
monitor_failing        cases of type drift, fairness or multiagent (a monitor breach; severity
                       of the case) and low groundedness verdicts of the quality monitor (one
                       event per agent and day; low). ``monitor_status`` has no ``failing``
                       value, the breach cases are the deterministic outcome of a monitor
pack_no_go             ``eval_result`` rows with status fail or error on a pack whose launch
                       gate is ``required`` (a NO-GO item), not mock; high
chain_break            ``chain_verify`` and ``audit_pack_built`` chain records that say the
                       verify failed; critical
model_version_change   ``agent_version`` rows whose model endpoint or model family differs
                       from the version before; medium
judge_escalation       cases of type judge (a judge asked for a person); severity of the case
=====================  ==================================================================

``attach_systems`` then gives each event the system (``system_component``, agent links) it
belongs to: one event per linked system, or one event with no system.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from supervisor.core.canonical import format_ts
from supervisor.governance.actions_model import (
    ID_PATTERN,
    SEVERITIES,
    GovernanceEvent,
    safe_ref,
)
from supervisor.monitors.common import MonitorContext, as_dt, read_range

log = logging.getLogger("supervisor.governance.actions")

RISKY_CLASSES = ("money", "credit", "pii_export")
DETECTOR_FAILED_REASONS = ("execution_failed", "timed_out")
MONITOR_CASE_TYPES = ("drift", "fairness", "multiagent")
TOOL_BATCH = 200  # decision ids in one lookup
# Verdict rows that are not a rule decision (the same list as supervisor.risk.evidence).
NON_HIT_LABEL_PREFIXES = ("shadow_",)
NON_HIT_LABELS = ("rule_error", "fail_open", "fail_closed")
NON_HIT_CHECKERS = ("gate:fail_mode",)
NO_AGENT = "-"
QUALITY_CHECKER = "quality.groundedness"
CHAIN_VERIFY_TYPES = ("chain_verify", "audit_pack_built")
LAUNCH_REQUIRED = "required"


def _agent(value: Any) -> str:
    text = str(value or "")
    return text if ID_PATTERN.match(text) else NO_AGENT


def _sev(value: Any, default: str = "low") -> str:
    return str(value) if value in SEVERITIES else default


def _true(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)


# --------------------------------------------------------------------------- sources


def alerts(ctx: MonitorContext, lo: datetime, hi: datetime) -> list[GovernanceEvent]:
    out = []
    for a in read_range(ctx, "alert", lo, hi):
        out.append(
            GovernanceEvent(
                kind="alert",
                severity=_sev(a.get("severity")),
                agent_id=_agent(a.get("agent_id")),
                ref=safe_ref("alert", a["alert_id"]),
                at=as_dt(a["ts"]),
                rule_id=str(a.get("rule_id") or ""),
                case_id=a.get("case_id") or None,
            )
        )
    return out


def _range(
    ctx: MonitorContext,
    table: str,
    column: str,
    lo: datetime,
    hi: datetime,
    where: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Rows with ``lo <= column < hi`` (and equality filters) read by the store, not in Python.
    Like ``read_range`` for a table whose time column is not ``ts``."""
    t = ctx.model.table(table)
    t.column(column)
    params: dict[str, Any] = {"r_from": lo, "r_to": hi}
    types: dict[str, str] = {"r_from": "timestamp", "r_to": "timestamp"}
    parts = [f"{column} >= :r_from", f"{column} < :r_to"]
    for i, (name, value) in enumerate(sorted((where or {}).items())):
        col = t.column(name)
        parts.append(f"{col.name} = :w{i}")
        params[f"w{i}"] = value
        types[f"w{i}"] = col.type
    sql = (
        f"SELECT {', '.join(t.column_names)} FROM {ctx.executor.qualify(t.name)} "  # noqa: S608 - names from model.yaml
        f"WHERE {' AND '.join(parts)} ORDER BY {column}"
    )
    return ctx.executor.query(sql, params, column_types=t.types, param_types=types)


def _tools_of(ctx: MonitorContext, event_ids: list[str]) -> dict[str, str]:
    """event id -> tool name for a set of gate decisions, in batches (one query per 200 ids)."""
    t = ctx.model.table("agent_event")
    out: dict[str, str] = {}
    ids = sorted(set(event_ids))
    for i in range(0, len(ids), TOOL_BATCH):
        chunk = ids[i : i + TOOL_BATCH]
        names = [f"e{k}" for k in range(len(chunk))]
        sql = (
            f"SELECT event_id, tool_name FROM {ctx.executor.qualify(t.name)} "  # noqa: S608 - names from model.yaml
            f"WHERE event_id IN ({', '.join(':' + n for n in names)})"
        )
        rows = ctx.executor.query(
            sql,
            dict(zip(names, chunk, strict=True)),
            column_types={"event_id": t.types["event_id"], "tool_name": t.types["tool_name"]},
            param_types=dict.fromkeys(names, "string"),
        )
        out.update({str(r["event_id"]): str(r["tool_name"]) for r in rows if r.get("tool_name")})
    return out


def gate_stops(
    ctx: MonitorContext,
    lo: datetime,
    hi: datetime,
    *,
    classes: Mapping[str, str] | None = None,
) -> list[GovernanceEvent]:
    """Gate block or pause on a money, credit or pii_export tool. ``classes`` is tool -> risk
    class (default: the policy catalogue and the agent manifests, as tool analytics reads it).
    One event per agent, action and hour (review L4): a burst of blocked calls is one event; the
    rule and the evidence are those of the first stop of the group."""
    if classes is None:
        from supervisor.analytics.tools import risk_classes

        classes = risk_classes()
    stops: list[tuple[Mapping[str, Any], str]] = []
    for action, severity in (("block", "high"), ("pause", "medium")):
        for v in read_range(ctx, "verdict", lo, hi, {"tier": 0, "action": action}):
            label = str(v.get("label") or "")
            if (
                _true(v.get("is_mock"))
                or _true(v.get("advisory"))
                or label in NON_HIT_LABELS
                or label.startswith(NON_HIT_LABEL_PREFIXES)
                or str(v.get("checker_id") or "") in NON_HIT_CHECKERS
                or not v.get("event_id")
            ):
                continue
            stops.append((v, severity))
    tools = _tools_of(ctx, [str(v["event_id"]) for v, _ in stops])
    groups: dict[tuple[str, str, str], tuple[Mapping[str, Any], str]] = {}
    for v, severity in sorted(stops, key=lambda x: (as_dt(x[0]["ts"]), str(x[0]["verdict_id"]))):
        tool = tools.get(str(v["event_id"]))
        if tool is None or classes.get(tool) not in RISKY_CLASSES:
            continue
        key = (_agent(v["agent_id"]), str(v["action"]), as_dt(v["ts"]).strftime("%Y%m%d%H"))
        groups.setdefault(key, (v, severity))
    out = []
    for (agent, action, hour), (v, severity) in sorted(groups.items()):
        rule = str(v.get("rule_id") or "")
        out.append(
            GovernanceEvent(
                kind="gate_stop",
                severity=severity,
                agent_id=agent,
                ref=safe_ref("gatestop", agent, action, hour),
                at=as_dt(v["ts"]),
                rule_id=rule,
                evidence=("rule", rule) if rule else None,
            )
        )
    return out


def detector_failures(ctx: MonitorContext, lo: datetime, hi: datetime) -> list[GovernanceEvent]:
    groups: dict[tuple[str, str, str], datetime] = {}
    for reason in DETECTOR_FAILED_REASONS:
        for f in read_range(ctx, "finding", lo, hi, {"not_executed_reason": reason}):
            ts = as_dt(f["ts"])
            key = (_agent(f["agent_id"]), str(f["detector_slug"]), ts.strftime("%Y%m%d%H"))
            if key not in groups or ts < groups[key]:
                groups[key] = ts
    return [
        GovernanceEvent(
            kind="detector_failed",
            severity="medium",
            agent_id=agent,
            ref=safe_ref("finding", agent, slug, hour),
            at=ts,
        )
        for (agent, slug, hour), ts in sorted(groups.items())
    ]


def _cases(
    ctx: MonitorContext, case_type: str, lo: datetime, hi: datetime
) -> Iterable[Mapping[str, Any]]:
    return _range(ctx, "cases", "opened_at", lo, hi, {"case_type": case_type})


def monitor_failures(ctx: MonitorContext, lo: datetime, hi: datetime) -> list[GovernanceEvent]:
    out = []
    for ctype in MONITOR_CASE_TYPES:
        for c in _cases(ctx, ctype, lo, hi):
            out.append(
                GovernanceEvent(
                    kind="monitor_failing",
                    severity=_sev(c.get("severity"), "medium"),
                    agent_id=_agent(c["agent_id"]),
                    ref=safe_ref("case", c["case_id"]),
                    at=as_dt(c["opened_at"]),
                    rule_id=ctype,
                    case_id=str(c["case_id"]),
                    evidence=("monitor", ctype),
                )
            )
    days: dict[tuple[str, str], datetime] = {}
    for v in read_range(ctx, "verdict", lo, hi, {"checker_id": QUALITY_CHECKER, "label": "low"}):
        ts = as_dt(v["ts"])
        key = (_agent(v["agent_id"]), ts.strftime("%Y%m%d"))
        if key not in days or ts < days[key]:
            days[key] = ts
    for (agent, day), ts in sorted(days.items()):
        out.append(
            GovernanceEvent(
                kind="monitor_failing",
                severity="low",
                agent_id=agent,
                ref=safe_ref("quality", agent, day),
                at=ts,
                rule_id="quality",
                evidence=("monitor", "quality"),
            )
        )
    return out


def pack_no_go(ctx: MonitorContext, lo: datetime, hi: datetime) -> list[GovernanceEvent]:
    out = []
    for status in ("fail", "error"):
        for r in read_range(ctx, "eval_result", lo, hi, {"status": status}):
            if _true(r.get("is_mock")) or str(r.get("launch_gate") or "") != LAUNCH_REQUIRED:
                continue
            if r.get("target_kind") not in ("agent", "traces"):
                continue
            pack = str(r["pack_id"])
            out.append(
                GovernanceEvent(
                    kind="pack_no_go",
                    severity="high",
                    agent_id=_agent(r["target_id"]),
                    ref=safe_ref("eval", r["run_id"], pack, r["target_kind"], r["target_id"]),
                    at=as_dt(r["ts"]),
                    rule_id=pack,
                    evidence=("pack", pack),
                )
            )
    return out


def chain_breaks(ctx: MonitorContext, lo: datetime, hi: datetime) -> list[GovernanceEvent]:
    out = []
    for rtype in CHAIN_VERIFY_TYPES:
        for e in read_range(ctx, "chain_entry", lo, hi, {"record_type": rtype}):
            rows = ctx.tables.query("chain_payload", {"lane": e["lane"], "seq": e["seq"]})
            p = json.loads(rows[0]["payload"]) if rows else {}
            ok = p["ok"] if "ok" in p else p.get("verify_ok")
            if ok is None or _true(ok):
                continue
            out.append(
                GovernanceEvent(
                    kind="chain_break",
                    severity="critical",
                    agent_id=NO_AGENT,
                    ref=safe_ref("chain", e["lane"], e["seq"]),
                    at=as_dt(e["ts"]),
                )
            )
    return out


def model_changes(ctx: MonitorContext, lo: datetime, hi: datetime) -> list[GovernanceEvent]:
    """Only the versions deployed in the range are read by the store; the history of an agent
    is read (small) only for an agent that has one."""
    fresh = _range(ctx, "agent_version", "deployed_at", lo, hi)
    out = []
    for agent in sorted({str(r["agent_id"]) for r in fresh}):
        rows = sorted(
            ctx.tables.query("agent_version", {"agent_id": agent}),
            key=lambda r: (as_dt(r["deployed_at"]), str(r["version"])),
        )
        for i, r in enumerate(rows):
            at = as_dt(r["deployed_at"])
            if i == 0 or not (lo <= at < hi):
                continue
            prev = rows[i - 1]
            if (r.get("model_endpoint"), r.get("model_family")) == (
                prev.get("model_endpoint"),
                prev.get("model_family"),
            ):
                continue
            out.append(
                GovernanceEvent(
                    kind="model_version_change",
                    severity="medium",
                    agent_id=_agent(agent),
                    ref=safe_ref("agent_version", agent, r["version"]),
                    at=at,
                )
            )
    return out


def judge_escalations(ctx: MonitorContext, lo: datetime, hi: datetime) -> list[GovernanceEvent]:
    return [
        GovernanceEvent(
            kind="judge_escalation",
            severity=_sev(c.get("severity"), "medium"),
            agent_id=_agent(c["agent_id"]),
            ref=safe_ref("case", c["case_id"]),
            at=as_dt(c["opened_at"]),
            case_id=str(c["case_id"]),
        )
        for c in _cases(ctx, "judge", lo, hi)
    ]


# name -> reader. The name is the cursor key, so one failing source never holds back the others.
SOURCES: dict[str, Callable[..., list[GovernanceEvent]]] = {
    "alerts": alerts,
    "gate_stops": gate_stops,
    "detector_failures": detector_failures,
    "monitor_failures": monitor_failures,
    "pack_no_go": pack_no_go,
    "chain_breaks": chain_breaks,
    "model_changes": model_changes,
    "judge_escalations": judge_escalations,
}


# --------------------------------------------------------------------------- systems


def systems_of(state: Any) -> dict[str, list[str]]:
    """agent id (lower case) -> ids of the systems it is an active part of, not archived,
    sorted."""
    open_systems = {
        str(s["system_id"]) for s in state.query("ai_system") if s["status"] != "archived"
    }
    out: dict[str, set[str]] = {}
    for c in state.query("system_component", {"ref_kind": "agent"}):
        if _true(c["active"]) and str(c["system_id"]) in open_systems:
            out.setdefault(str(c["ref_id"]).lower(), set()).add(str(c["system_id"]))
    return {k: sorted(v) for k, v in out.items()}


def attach_systems(
    events: Iterable[GovernanceEvent], links: Mapping[str, list[str]]
) -> list[GovernanceEvent]:
    """One event per linked system; an event with no linked system (or no agent) stays with no
    system. The order is the sort key of the events."""
    out: list[GovernanceEvent] = []
    for e in events:
        ids = links.get(e.agent_id.lower(), []) if e.agent_id != NO_AGENT else []
        if not ids:
            out.append(e.for_system(None))
        else:
            out.extend(e.for_system(sid) for sid in ids)
    out.sort(key=GovernanceEvent.sort_key)
    return out


def stamp(at: datetime) -> str:
    return format_ts(at)


OVERLAP = timedelta(seconds=300)  # each run re-reads this much before its cursor (markers dedupe)
