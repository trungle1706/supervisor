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


# ---------------------------------------------------------------------------- agents

STAGES = ("discover", "understand", "plan", "instrument", "launch", "operate")
# The artefact each Onboard stage writes (supervisor.onboard.run.ARTEFACTS).
STAGE_ARTEFACT = {
    "discover": "inventory.json",
    "understand": "profile.json",
    "plan": "plan.json",
    "instrument": "pr_description.md",
    "launch": "launch_report.json",
    "operate": "handover.json",
}


def onboard_dir(settings: Any, agent_id: str) -> Path:
    return Path(settings.data_dir) / "onboard" / agent_id


def onboard_artefacts(settings: Any, agent_id: str) -> set[str]:
    d = onboard_dir(settings, agent_id)
    try:
        return {p.name for p in d.iterdir() if p.is_file()} if d.is_dir() else set()
    except OSError:
        return set()


def lifecycle(gate_state: str | None, artefacts: set[str]) -> list[dict[str, str]]:
    """Six-stage stepper. A registered agent is past Instrument: SHADOW means Launch
    (rules evaluated, nothing blocked yet); RUNNING / PAUSED / QUARANTINED means Operate
    (the default for a registered agent). An agent known only from Onboard artefacts is at
    the stage after the last artefact written."""
    if gate_state == "SHADOW":
        now = STAGES.index("launch")
        note = "stage_note_shadow"
    elif gate_state:
        now = STAGES.index("operate")
        note = "stage_note_enforced"
    else:
        done = [i for i, s in enumerate(STAGES) if STAGE_ARTEFACT[s] in artefacts]
        now = min(max(done) + 1, len(STAGES) - 1) if done else 0
        note = ""
    out = []
    for i, s in enumerate(STAGES):
        state = "done" if i < now else "now" if i == now else "todo"
        out.append({"key": s, "state": state, "note": note if i == now else ""})
    return out


def _allowed_tools(rules: Mapping[str, Mapping[str, Any]], agent_id: str) -> list[str]:
    """Tools named by the agent's approved-tools rule (``tool not_in [...]``)."""
    out: list[str] = []
    for r in rules.values():
        expr = r.get("expression") or {}
        scope = expr.get("agent_scope")
        if scope != "*" and agent_id not in (scope or []):
            continue
        tool = (expr.get("when") or {}).get("tool") or {}
        if tool.get("op") == "not_in":
            out += [t for t in tool.get("value") or [] if t not in out]
    return out


def _coverage(ctx: Any, agent_id: str) -> dict[str, Any]:
    """Coverage in basis points and where the number comes from.

    1. ``coverage`` rows (capabilities on / all, written by Onboard);
    2. else the latest ``oversight_metric.coverage_bp`` (gated / seen tool calls);
    3. else gate decisions / tool calls over the agent's newest 2000 events.
    ``trace_coverage`` rows add the capabilities a trace path cannot see."""
    from supervisor.console import views

    reduced = ctx.tables.query("trace_coverage", {"agent_id": agent_id}, limit=200)
    missing = sorted({m for r in reduced for m in (jloads(r.get("missing"), []) or [])})
    rows = ctx.state.query("coverage", {"agent_id": agent_id})
    if rows:
        on = sum(1 for r in rows if str(r.get("status", "")).lower() in ("on", "enabled"))
        return {
            "bp": views.coverage_bp(rows),
            "source": "cov_src_capabilities",
            "detail": f"{on}/{len(rows)}",
            "missing": missing,
        }
    metric = ctx.state.query("oversight_metric", {"agent_id": agent_id})
    metric = [m for m in metric if m.get("coverage_bp") is not None]
    if metric:
        latest = max(metric, key=lambda m: m["metric_date"])
        return {
            "bp": int(latest["coverage_bp"]),
            "source": "cov_src_metric",
            "detail": str(latest["metric_date"]),
            "missing": missing,
        }
    events = ctx.tables.query("agent_event", {"agent_id": agent_id}, order_by=("-ts",), limit=2000)
    calls = sum(1 for e in events if e["event_type"] == "tool_call")
    gated = sum(1 for e in events if e["event_type"] == "gate_decision")
    if calls == 0 and gated == 0:
        return {"bp": None, "source": "cov_src_none", "detail": "", "missing": missing}
    seen = calls or gated
    return {
        "bp": min(10000, gated * 10000 // seen),
        "source": "cov_src_events",
        "detail": f"{gated}/{seen}",
        "missing": missing,
    }


def _judge_family(ctx: Any, agent_id: str) -> dict[str, Any]:
    rows = ctx.tables.query("verdict", {"agent_id": agent_id}, order_by=("-ts",), limit=500)
    judge = next((v for v in rows if int(v["tier"]) >= 1), None)
    if judge is not None:
        return {
            "family": judge.get("model_family") or "-",
            "model": judge.get("model_id") or "-",
            "mock": bool(judge.get("is_mock")),
        }
    s = ctx.settings
    if not getattr(s, "judge_t1_model", ""):
        return {"family": "mock", "model": "-", "mock": True}
    return {
        "family": getattr(s, "judge_t1_family", None) or "-",
        "model": s.judge_t1_model,
        "mock": False,
    }


def _stop_cause(ctx: Any, agent_id: str, state: str) -> dict[str, Any] | None:
    """Who or which rule put the agent in PAUSED / QUARANTINED (active gate_control)."""
    if state not in ("PAUSED", "QUARANTINED"):
        return None
    action = "pause" if state == "PAUSED" else "quarantine"
    rows = [
        r
        for r in ctx.state.query("gate_control", {"agent_id": agent_id, "status": "active"})
        if r["action"] == action
    ]
    if not rows:
        return None
    row = max(rows, key=lambda r: r["created_at"])
    principal = str(row.get("principal") or "")
    rule = principal.split(":", 1)[1] if principal.startswith("rule:") else None
    return {"rule": rule, "principal": None if rule else principal, "at": row["created_at"]}


def decision33(ctx: Any, agent: Mapping[str, Any]) -> dict[str, Any]:
    """Registry value, else the Onboard proposal (profile.json), else not classified."""
    cls = agent.get("decision33_class")
    if cls:
        return {"cls": str(cls), "source": "registry"}
    prof = onboard_dir(ctx.settings, agent["agent_id"]) / "profile.json"
    if prof.is_file():
        try:
            data = json.loads(prof.read_text(encoding="utf-8"))
            return {"cls": data["decision33"]["classification"], "source": "proposal"}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return {"cls": None, "source": None}


def agent_cards(ctx: Any, me: Any) -> list[dict[str, Any]]:
    from supervisor.core.errors import SupervisorError

    states = ctx.gateway.states
    rules = rules_index(ctx)
    classes = tool_classes(ctx)
    try:
        doc = states.policy.current().doc
        reviewers, admins = set(doc.reviewers), set(doc.admins)
    except Exception:  # noqa: BLE001
        reviewers, admins = set(), set()
    open_by_agent: dict[str, int] = {}
    for c in open_cases(ctx):
        open_by_agent[c["agent_id"]] = open_by_agent.get(c["agent_id"], 0) + 1
    cards = []
    for a in sorted(ctx.state.query("agent"), key=lambda r: r["agent_id"]):
        aid = a["agent_id"]
        try:
            desc = states.describe(aid)
        except SupervisorError:
            desc = {"state": a["gate_state"], "pending_resume": []}
        state = desc["state"]
        pending = desc.get("pending_resume") or []
        scoped = [
            r
            for r in rules.values()
            if (r["expression"].get("agent_scope") == "*")
            or aid in (r["expression"].get("agent_scope") or [])
        ]
        fail_modes = sorted({r.get("fail_mode") or "-" for r in scoped})
        tools = _allowed_tools(rules, aid)
        seen = {
            e["tool_name"]
            for e in ctx.tables.query(
                "agent_event",
                {"agent_id": aid, "event_type": "gate_decision"},
                order_by=("-ts",),
                limit=2000,
            )
            if e.get("tool_name")
        }
        tools += sorted(t for t in seen if t not in tools)
        money = [t for t in tools if classes.get(t) == "money"]
        me_role = (
            "owner"
            if me.user_id == a.get("owner_user")
            else "reviewer"
            if me.user_id in reviewers
            else None
        )
        approved = {p["principal"] for p in pending}
        cards.append(
            {
                **a,
                "state": state,
                "cause": _stop_cause(ctx, aid, state),
                "pending": pending,
                "pending_roles": sorted({p["role"] for p in pending}),
                "me_role": me_role,
                "me_approved": me.user_id in approved,
                "me_policy_admin": me.user_id in admins,
                "stages": lifecycle(state, onboard_artefacts(ctx.settings, aid)),
                "coverage": _coverage(ctx, aid),
                "open_cases": open_by_agent.get(aid, 0),
                "tools_n": len(tools),
                "money_n": len(money),
                "fail_mode": fail_modes[0] if len(fail_modes) == 1 else "mixed",
                "rules_n": len(scoped),
                "judge": _judge_family(ctx, aid),
                "d33": decision33(ctx, a),
            }
        )
    rank = {"QUARANTINED": 0, "PAUSED": 1, "SHADOW": 2, "RUNNING": 3}
    cards.sort(key=lambda c: (rank.get(c["state"], 4), c["agent_id"]))
    return cards


# ---------------------------------------------------------------------------- cases

WHAT_BY_CLASS = {
    "money": "what_money",
    "credit": "what_credit",
    "pii_export": "what_pii",
    "read_only": "what_read",
}


def case_head(
    ctx: Any,
    case: Mapping[str, Any],
    *,
    rules: Mapping[str, Mapping[str, Any]] | None = None,
    classes: Mapping[str, str] | None = None,
    agents: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """What the case is about, in plain words, from its first gate stop (rule + tool).

    Returns the source kinds, the stopping rule, the tool and amount of the stopped call,
    and a headline key with its parameters (the template translates). Cases opened by a
    judge or a monitor keep their own summary as the headline."""
    rules = rules if rules is not None else rules_index(ctx)
    classes = classes if classes is not None else tool_classes(ctx)
    links = ctx.cases.links(case["case_id"])
    kinds = sorted({link["source_kind"] for link in links})
    agent = (agents or {}).get(case["agent_id"]) or ctx.state.get(
        "agent", {"agent_id": case["agent_id"]}
    )
    agent_label = (agent or {}).get("name") or case["agent_id"]
    out: dict[str, Any] = {
        "kinds": kinds or ["manual"],
        "rule_id": None,
        "rule": None,
        "tool": None,
        "amount": None,
        "currency": None,
        "action": None,
        "latency_ms": None,
        "event_id": None,
        "trace_id": None,
        "key": None,
        "params": {},
        "agent_label": agent_label,
        "joined": max(0, len([lk for lk in links if lk["source_kind"] == "gate"]) - 1),
    }
    gate_links = [lk for lk in links if lk["source_kind"] == "gate"]
    if gate_links:
        ref = gate_links[0]["source_ref"]
        verdicts = ctx.tables.query("verdict", {"event_id": ref})
        stops = [
            v
            for v in verdicts
            if int(v["tier"]) == 0 and v["action"] in STOP_ACTIONS and not v["advisory"]
        ]
        stop = min(stops, key=lambda v: v["action"] != "pause") if stops else None
        events = ctx.tables.query("agent_event", {"event_id": ref}, limit=1)
        ev = events[0] if events else {}
        tool = ev.get("tool_name")
        out.update(
            {
                "event_id": ref,
                "trace_id": ev.get("trace_id") or (stop or {}).get("trace_id"),
                "tool": tool,
                "amount": ev.get("amount_minor"),
                "currency": ev.get("currency") or ("VND" if ev.get("amount_minor") else None),
                "latency_ms": ev.get("latency_ms"),
            }
        )
        if stop is not None:
            rid = stop.get("rule_id")
            out.update(
                {
                    "rule_id": rid,
                    "rule": rules.get(rid) if rid else None,
                    "action": stop["action"],
                }
            )
            what = WHAT_BY_CLASS.get(classes.get(tool or "", ""), "what_call")
            out["key"] = "hl_pause" if stop["action"] == "pause" else "hl_block"
            out["params"] = {"agent": agent_label, "what": what, "tool": tool or "-"}
    return out


def case_rows(ctx: Any, cases: Sequence[Mapping[str, Any]], now: dt.datetime) -> list[dict]:
    from supervisor.console import views

    rules = rules_index(ctx)
    classes = tool_classes(ctx)
    agents = {a["agent_id"]: a for a in ctx.state.query("agent")}
    rows = []
    for c in cases:
        head = case_head(ctx, c, rules=rules, classes=classes, agents=agents)
        clock = (
            views.countdown(c.get("report_due_at"), now, severity=c["severity"])
            if c["status"] != "closed"
            else None
        )
        rows.append({**c, "head": head, "sources": head["kinds"], "clock": clock})
    return rows


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
