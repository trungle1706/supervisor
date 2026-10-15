"""Read models for the console screens (WP12). Pure functions over the stores; no writes.

The console shows times in Vietnam time (ICT, UTC+7): "today" is the ICT calendar day.
Counts come from the append-only tables (``agent_event``, ``verdict``, ``chain_*``) and the
state tables (``agent``, ``cases``). Stores only filter by equality, so a scan is ordered
newest first and capped at ``SCAN_CAP`` rows; a capped count is shown with a "+".
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from supervisor.cases.service import TRANSITIONS

ICT = dt.timezone(dt.timedelta(hours=7))
SCAN_CAP = 20000
OPEN_STATUSES = (*TRANSITIONS.keys(), "escalated", "resolved")
STOP_ACTIONS = ("block", "pause")


# ---------------------------------------------------------------------------- small helpers


def ict(value: dt.datetime | None) -> dt.datetime | None:
    return value.astimezone(ICT) if value is not None else None


def hhmm(value: dt.datetime | None, seconds: bool = False) -> str:
    if value is None:
        return "-"
    return ict(value).strftime("%H:%M:%S" if seconds else "%H:%M")  # type: ignore[union-attr]


def day_start(now: dt.datetime) -> dt.datetime:
    """Midnight of the ICT day that contains ``now`` (aware, UTC)."""
    local = now.astimezone(ICT)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt.UTC)


def greeting_key(now: dt.datetime) -> str:
    hour = now.astimezone(ICT).hour
    if 4 <= hour < 12:
        return "greet_morning"
    if 12 <= hour < 18:
        return "greet_afternoon"
    return "greet_evening"


def first_name(me: Any) -> str:
    """Vietnamese names put the given name last ("Nguyễn Văn An" -> "An"). A label with a
    note in brackets ("Payments Ops lead (owner)") is used as it is, without the note."""
    name = (getattr(me, "display_name", "") or "").strip()
    if not name:
        uid = str(getattr(me, "user_id", "") or "")
        return uid.split("@")[0] or uid
    if "(" in name:
        return name.split("(")[0].strip() or name
    parts = name.split()
    return parts[-1] if len(parts) >= 2 else name


def initials(me: Any) -> str:
    name = (getattr(me, "display_name", "") or "").split("(")[0].strip()
    if name:
        parts = name.split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return name[:2].upper()
    uid = str(getattr(me, "user_id", "") or "?")
    return uid[:2].upper()


def main_role(me: Any) -> str:
    order = ("admin", "approver", "reviewer", "owner", "auditor")
    roles = set(getattr(me, "roles", ()) or ())
    for r in order:
        if r in roles:
            return r
    return "service" if getattr(me, "kind", "") == "service_principal" else "viewer"


def median(values: Sequence[int]) -> int | None:
    """Nearest-rank median (always one of the values), as in docs/metrics.md."""
    vals = sorted(values)
    if not vals:
        return None
    return vals[(len(vals) + 1) // 2 - 1]


def is_demo_store(settings: Any) -> bool:
    from supervisor.demo.session import MARKER

    try:
        return (Path(settings.data_dir) / MARKER).is_file()
    except (OSError, TypeError):
        return False


def open_cases(ctx: Any) -> list[dict[str, Any]]:
    return ctx.cases.list_cases(statuses=OPEN_STATUSES)


# ---------------------------------------------------------------------------- shell


def shell(ctx: Any, me: Any) -> dict[str, Any]:
    """Header data for every full page: counts on the pills, environment badge, identity."""
    agents = ctx.state.query("agent")
    cases = open_cases(ctx)
    try:
        unread = sum(1 for n in ctx.inbox.list() if n.get("status") == "unread")
    except Exception:  # noqa: BLE001 - the badge is a convenience, never a page failure
        unread = 0
    return {
        "agents_n": len(agents),
        "cases_n": len(cases),
        "critical_n": sum(1 for c in cases if c["severity"] == "critical"),
        "demo": is_demo_store(ctx.settings),
        "mode": ctx.settings.supervisor_mode,
        "unread": unread,
        "initials": initials(me),
        "first_name": first_name(me),
        "role": main_role(me),
    }


def jloads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def as_list(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------- policy lookups


def rules_index(ctx: Any) -> dict[str, dict[str, Any]]:
    """Latest deployed version of every rule: description, action, severity, refs."""
    out: dict[str, dict[str, Any]] = {}
    for r in ctx.state.query("rule"):
        cur = out.get(r["rule_id"])
        if cur is not None and cur["version"] >= r["version"]:
            continue
        expr = jloads(r.get("expression"), {})
        expr = expr if isinstance(expr, dict) else {}
        out[r["rule_id"]] = {
            "rule_id": r["rule_id"],
            "version": r["version"],
            "description": expr.get("description") or "",
            "action": r["action"],
            "severity": r["severity"],
            "fail_mode": r.get("fail_mode"),
            "regulation_ref": r.get("regulation_ref"),
            "owner": r.get("owner"),
            "agent_scope": r.get("agent_scope"),
            "expression": expr,
        }
    return out


def tool_classes(ctx: Any) -> dict[str, str]:
    """Tool -> risk class (read_only, money, credit, pii_export, ...) from the policy."""
    try:
        return dict(ctx.gateway.states.policy.current().doc.tools)
    except Exception:  # noqa: BLE001 - no policy loaded: no classes, the screen still renders
        return {}


RISK_WORD = {
    "read_only": "risk_read_only",
    "money": "risk_money",
    "credit": "risk_credit",
    "pii_export": "risk_pii_export",
}


# ---------------------------------------------------------------------------- overview


def gate_today(ctx: Any, now: dt.datetime) -> dict[str, Any]:
    """Gate decisions of the ICT day: checked, stopped (blocked / paused), latencies."""
    start = day_start(now)
    events = ctx.tables.query(
        "agent_event", {"event_type": "gate_decision"}, order_by=("-ts",), limit=SCAN_CAP
    )
    today = [e for e in events if e["ts"] >= start]
    capped = len(events) >= SCAN_CAP and len(today) == len(events)
    verdicts = ctx.tables.query("verdict", {"tier": 0}, order_by=("-ts",), limit=SCAN_CAP)
    stops: dict[str, str] = {}
    for v in verdicts:
        if v["ts"] < start or v["advisory"] or v["action"] not in STOP_ACTIONS:
            continue
        key = str(v.get("event_id") or v["verdict_id"])
        if stops.get(key) != "pause":
            stops[key] = v["action"]
    lat_by_event = {e["event_id"]: e.get("latency_ms") for e in today}
    stop_lat = [int(lat_by_event[k]) for k in stops if lat_by_event.get(k) is not None]
    all_lat = [int(e["latency_ms"]) for e in today if e.get("latency_ms") is not None]
    return {
        "checked": len(today),
        "capped": capped,
        "agents": len({e["agent_id"] for e in today}),
        "stopped": len(stops),
        "blocked": sum(1 for a in stops.values() if a == "block"),
        "paused": sum(1 for a in stops.values() if a == "pause"),
        "stop_median_ms": median(stop_lat),
        "median_ms": median(all_lat),
    }


def chain_summary(ctx: Any) -> dict[str, Any]:
    """Entries per lane, last signed root (key id, dev/managed), last anchor, last verify."""
    heads = ctx.runtime.chain.heads()
    lanes = {k: v.seq + 1 for k, v in sorted(heads.items())}
    sig_rows = ctx.tables.query("chain_signature", {"lane": "root"}, order_by=("-seq",), limit=1)
    signed = None
    if sig_rows:
        s = sig_rows[0]
        entry = ctx.tables.query("chain_entry", {"lane": "root", "seq": s["seq"]}, limit=1)
        signed = {
            "seq": s["seq"],
            "key_id": s["key_id"],
            "key_kind": s["key_kind"],
            "algorithm": s["algorithm"],
            "ts": entry[0]["ts"] if entry else None,
        }
    anchors = ctx.tables.query("anchor", None, order_by=("-anchored_at",), limit=1)
    anchor = anchors[0] if anchors else None
    return {
        "entries": sum(lanes.values()),
        "lanes": lanes,
        "agent_lanes": sum(1 for k in lanes if k != "root"),
        "signed": signed,
        "anchor": anchor,
        "anchored": anchor is not None,
        "verify": ctx.last_verify.get("all"),
    }


def latest_decisions(ctx: Any, limit: int = 6) -> list[dict[str, Any]]:
    """Newest gate decisions with their outcome, rule and case (if one was opened)."""
    rules = rules_index(ctx)
    classes = tool_classes(ctx)
    out = []
    for e in ctx.tables.query(
        "agent_event", {"event_type": "gate_decision"}, order_by=("-ts",), limit=limit
    ):
        verdicts = ctx.tables.query("verdict", {"event_id": e["event_id"]})
        stops = [
            v
            for v in verdicts
            if int(v["tier"]) == 0 and v["action"] in STOP_ACTIONS and not v["advisory"]
        ]
        stop = min(stops, key=lambda v: v["action"] != "pause") if stops else None
        rule = rules.get(stop["rule_id"]) if stop and stop.get("rule_id") else None
        if stop:
            outcome = "paused" if stop["action"] == "pause" else "blocked"
        else:
            outcome = "allowed" if e.get("status") == "allowed" else (e.get("status") or "-")
        out.append(
            {
                "ts": e["ts"],
                "agent_id": e["agent_id"],
                "tool": e.get("tool_name") or "-",
                "outcome": outcome,
                "rule_id": stop.get("rule_id") if stop else None,
                "rule_text": (rule or {}).get("description")
                or ((stop or {}).get("rationale_masked") or ""),
                "risk": RISK_WORD.get(classes.get(e.get("tool_name") or "", ""), ""),
                "case_id": ctx.cases.linked_case("gate", e["event_id"]) if stop else None,
            }
        )
    return out


def overview(ctx: Any, now: dt.datetime) -> dict[str, Any]:
    from supervisor.console import views

    cases = open_cases(ctx)
    due = [c for c in cases if c.get("report_due_at") is not None]
    nearest = min(due, key=lambda c: c["report_due_at"]) if due else None
    nearest_clock = (
        views.countdown(nearest["report_due_at"], now, severity=nearest["severity"])
        if nearest
        else None
    )
    return {
        "agents_n": len(ctx.state.query("agent")),
        "gate": gate_today(ctx, now),
        "cases_n": len(cases),
        "critical_n": sum(1 for c in cases if c["severity"] == "critical"),
        "clock_running_n": len(due),
        "nearest": nearest,
        "nearest_clock": nearest_clock,
        "chain": chain_summary(ctx),
        "latest": latest_decisions(ctx),
        "demo": is_demo_store(ctx.settings),
    }
