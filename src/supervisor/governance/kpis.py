"""Governance KPIs (WP-G6, docs/mcp-server.md section 5).

One function, ``compute(ctx, me, now)``, read by ``GET /v1/kpis``, the MCP tool ``kpis`` and the
Governance overview. It reads rows; it writes nothing. Every figure is an integer or a count; a
rate is in basis points (0 to 10000); a figure that cannot be computed is ``None`` and its key is
listed in ``unavailable`` with a fixed reason code. Scope is the one of G0: ``scope_for(me)``.

Three groups:

* coverage: assets by kind, systems by risk level and by stage, classification rate, policy
  coverage (systems with at least one obligation assigned by the rules).
* quality: risk treatment coverage (active risks with a control), acceptable residual rate
  (active risks in band low or medium), control readiness (controls with working evidence),
  implementation per policy (obligations met over obligations that apply, per system).
* speed: average days per stage (from stage approvals that were applied), overdue tasks,
  inheritance rate (systems whose effective risk level comes from a linked part), automation
  runs and their success (rule runs on the chain, governance events and their actions).

Pure Python over the ``ctx`` services; no SQL and no web imports here.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import logging
import threading
import time
from collections.abc import Iterable
from typing import Any

from supervisor.governance import model as gm
from supervisor.governance.systems import ALL

log = logging.getLogger("supervisor.kpis")
STATUS_CAP = 20000
READ_CAP = 20000
CACHE_TTL_S = 30
CACHE_MAX = 256
RUN_CAP = 5000
ACTION_OK = ("done",)
ACTION_BAD = ("failed", "failed_final")


def _on(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true")


def bp(n: int, of: int) -> int | None:
    """Basis points of n over of; None when there is nothing to divide by."""
    return n * 10000 // of if of > 0 else None


def _ts(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    if isinstance(value, str) and value:
        try:
            out = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return out if out.tzinfo else out.replace(tzinfo=dt.UTC)
    return None


def _count_by(items: Iterable[str], order: Iterable[str] = ()) -> dict[str, int]:
    keys = tuple(order)
    out: dict[str, int] = dict.fromkeys(keys, 0)
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out


def _latest_control_status(
    ctx: Any, agent_ids: set[str]
) -> tuple[dict[tuple[str, str], str], bool]:
    """Newest status per (control, agent) for the agents given; and whether the scan hit its cap."""
    rows = ctx.tables.query("control_status", None, order_by=("-ts",), limit=STATUS_CAP)
    out: dict[tuple[str, str], str] = {}
    for r in rows:
        key = (str(r["control_id"]), str(r["agent_id"]))
        if str(r["agent_id"]).lower() in agent_ids and key not in out:
            out[key] = str(r["status"])
    return out, len(rows) >= STATUS_CAP


def _bounded(
    state: Any, table: str, unavailable: dict[str, str], order_by: tuple[str, ...] = ()
) -> list[Any]:
    """At most READ_CAP rows of a state table; a table that hits the cap says so (review M5)."""
    rows = state.query(table, None, order_by=order_by, limit=READ_CAP)
    if len(rows) >= READ_CAP:
        unavailable[f"{table}_capped"] = "capped"
    return list(rows)


def empty(reason: str = "error") -> dict[str, Any]:
    """A document of the same shape with nothing computed: every rate is None and says why."""
    rates = (
        "classification_rate_bp",
        "policy_coverage_bp",
        "risk_treatment_coverage_bp",
        "acceptable_residual_bp",
        "control_readiness_bp",
        "implementation_per_policy_bp",
        "inheritance_rate_bp",
        "action_success_bp",
    )
    return {
        "generated_at": None,
        "coverage": {
            "assets_by_kind": {},
            "systems_total": 0,
            "systems_by_risk": {},
            "systems_by_stage": {},
            "classification_rate_bp": None,
            "policy_coverage_bp": None,
        },
        "quality": {
            "risk_treatment_coverage_bp": None,
            "acceptable_residual_bp": None,
            "control_readiness_bp": None,
            "control_readiness_n": 0,
            "control_readiness_of": 0,
            "implementation_per_policy_bp": None,
            "implementation_by_system": [],
        },
        "speed": {
            "avg_days_per_stage": {},
            "overdue_tasks": None,
            "inheritance_rate_bp": None,
            "automation": {
                "rule_runs": 0,
                "rule_runs_capped": False,
                "events": 0,
                "events_done": 0,
                "actions_ok": 0,
                "actions_failed": 0,
                "action_success_bp": None,
            },
        },
        "unavailable": {**dict.fromkeys(rates, reason), "overdue_tasks": reason},
    }


_cache_lock = threading.Lock()
_cache: dict[Any, tuple[float, dict[str, Any]]] = {}
_clock = time.monotonic


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def compute(
    ctx: Any, me: Any, now: dt.datetime | None = None, *, cache: bool = True
) -> dict[str, Any]:
    """The KPI document for the systems ``me`` may see. The answer is kept for CACHE_TTL_S
    seconds for the same person, scope and settings (a KPI page must not rescan the store at
    each load); the caller gets a copy."""
    if not cache:
        return _compute(ctx, me, now)
    scope = ctx.systems.scope_for(me)
    s = ctx.settings
    key = (
        id(ctx.state),
        str(me.user_id),
        tuple(sorted(getattr(me, "roles", ()) or ())),
        "ALL" if scope is ALL else tuple(sorted(scope)),
        bool(s.risk_register_enabled),
        bool(s.controls_enabled),
        bool(s.governance_enabled),
    )
    t = _clock()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and t - hit[0] < CACHE_TTL_S:
            return copy.deepcopy(hit[1])
    doc = _compute(ctx, me, now)
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            _cache.clear()
        _cache[key] = (t, doc)
    return copy.deepcopy(doc)


def _compute(ctx: Any, me: Any, now: dt.datetime | None = None) -> dict[str, Any]:
    s = ctx.settings
    now = now or ctx.clock.now()
    svc = ctx.systems
    scope = svc.scope_for(me)
    rows = svc.list_systems(scope, {})
    sids = {str(r["system_id"]) for r in rows}
    unavailable: dict[str, str] = {}

    comps: dict[str, list[dict[str, Any]]] = {}
    for c in _bounded(ctx.state, "system_component", unavailable):
        if _on(c["active"]) and str(c["system_id"]) in sids:
            comps.setdefault(str(c["system_id"]), []).append(dict(c))
    sys_agents = {
        sid: sorted({str(c["ref_id"]) for c in cs if c["ref_kind"] == "agent"})
        for sid, cs in comps.items()
    }
    agent_ids = {a.lower() for ag in sys_agents.values() for a in ag}
    visible_agents = {str(a["agent_id"]).lower() for a in svc.agents_in_scope(me)}
    task_owners = {x.lower() for x in sids} | agent_ids

    # ------------------------------------------------------------------ coverage
    assets: dict[str, int] = {"agent": len(visible_agents)}
    node_ids = {str(c["ref_id"]) for cs in comps.values() for c in cs if c["ref_kind"] == "node"}
    for n in _bounded(ctx.state, "inventory_node", unavailable):
        if scope is ALL or str(n["node_id"]) in node_ids:
            if n["status"] != "gone":
                assets[str(n["kind"])] = assets.get(str(n["kind"]), 0) + 1
    classified = sum(1 for r in rows if r.get("decision33_class") not in (None, "unclassified"))
    obligation_systems = {
        str(a["system_id"])
        for a in ctx.state.query("assignment", {"kind": "obligation"})
        if _on(a["active"]) and str(a["system_id"]) in sids
    }
    coverage = {
        "assets_by_kind": dict(sorted(assets.items())),
        "systems_total": len(rows),
        "systems_by_risk": _count_by(
            (str(r["effective_risk_level"]) for r in rows), reversed(gm.RISK_LEVELS)
        ),
        "systems_by_stage": _count_by(
            (str(r["lifecycle_stage"]) for r in rows), gm.LIFECYCLE_STAGES
        ),
        "classification_rate_bp": bp(classified, len(rows)),
        "policy_coverage_bp": bp(len(obligation_systems), len(rows)),
    }

    # ------------------------------------------------------------------ quality
    risk_treatment = acceptable = None
    if not s.risk_register_enabled:
        unavailable["risk_treatment_coverage_bp"] = "risk_register_off"
        unavailable["acceptable_residual_bp"] = "risk_register_off"
    else:
        active = [r for r in ctx.risks.list_risks() if r["status"] == "active"]
        if scope is not ALL:
            active = [r for r in active if visible_agents & {a.lower() for a in r["agents"]}]
        acceptable = bp(
            sum(1 for r in active if r["residual_band"] in ("low", "medium")), len(active)
        )
        if not s.controls_enabled:
            unavailable["risk_treatment_coverage_bp"] = "controls_off"
        else:
            bare = set(ctx.controls.uncovered_risks())
            risk_treatment = bp(sum(1 for r in active if r["risk_id"] not in bare), len(active))
        if not active:
            unavailable["risk_treatment_coverage_bp"] = "no_active_risks"
            unavailable["acceptable_residual_bp"] = "no_active_risks"
    readiness: int | None = None
    ready_n = ready_of = 0
    if not s.controls_enabled:
        unavailable["control_readiness_bp"] = "controls_off"
    else:
        latest, _capped = _latest_control_status(ctx, agent_ids)
        ready_n = sum(1 for v in latest.values() if v == "working")
        ready_of = len(latest)
        readiness = bp(ready_n, ready_of)
        if readiness is None:
            unavailable["control_readiness_bp"] = "no_status"
    policy_rows: list[dict[str, Any]] = []
    implementation: int | None = None
    if not s.governance_enabled:
        unavailable["implementation_per_policy_bp"] = "governance_off"
    else:
        policy_rows, implementation = _implementation(ctx, rows)
        if implementation is None:
            unavailable["implementation_per_policy_bp"] = "no_obligations"
    quality = {
        "risk_treatment_coverage_bp": risk_treatment,
        "acceptable_residual_bp": acceptable,
        "control_readiness_bp": readiness,
        "control_readiness_n": ready_n,
        "control_readiness_of": ready_of,
        "implementation_per_policy_bp": implementation,
        "implementation_by_system": policy_rows,
    }

    # ------------------------------------------------------------------ speed
    overdue: int | None = None
    if not s.controls_enabled:
        unavailable["overdue_tasks"] = "controls_off"
    else:
        overdue = sum(
            1
            for t in ctx.tasks.list_tasks()
            if str(t["agent_id"]).lower() in task_owners and t["overdue"] and t["required"]
        )
    inherited = sum(1 for r in rows if r.get("effective_risk_source") == "inherited")
    speed = {
        "avg_days_per_stage": _days_per_stage(ctx, sids, unavailable),
        "overdue_tasks": overdue,
        "inheritance_rate_bp": bp(inherited, len(rows)),
        "automation": _automation(ctx, sids, unavailable),
    }
    return {
        "generated_at": now.isoformat() if isinstance(now, dt.datetime) else str(now),
        "coverage": coverage,
        "quality": quality,
        "speed": speed,
        "unavailable": unavailable,
    }


def _implementation(
    ctx: Any, rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int | None]:
    """Obligations met over obligations that apply, per system and overall. A system without
    assigned obligations is left out. ``met`` needs working evidence of the controls that hold it
    (the matrix of the rules service); with the control catalogue off nothing is met."""
    out: list[dict[str, Any]] = []
    met_all = of_all = 0
    for r in rows:
        try:
            obl = ctx.rules.obligations(str(r["system_id"]))
        except Exception:  # noqa: BLE001 - one system never stops the figure
            log.warning("kpis: obligations of a system could not be read")
            continue
        if not obl:
            continue
        met = sum(1 for o in obl if o["status"] == "working")
        met_all += met
        of_all += len(obl)
        out.append(
            {
                "system_id": str(r["system_id"]),
                "applies": len(obl),
                "met": met,
                "bp": bp(met, len(obl)),
            }
        )
    return out, bp(met_all, of_all)


def _days_per_stage(ctx: Any, sids: set[str], unavailable: dict[str, str]) -> dict[str, int]:
    """Whole days from the request of a stage approval to the move that used it, averaged by the
    stage left. Only applied approvals count; a stage with none is left out."""
    total: dict[str, list[int]] = {}
    for a in _bounded(ctx.state, "stage_approval", unavailable, ("-created_at",)):
        if str(a["system_id"]) not in sids:
            continue
        start, end = _ts(a["created_at"]), _ts(a.get("applied_at"))
        if start is None or end is None or end < start:
            continue
        total.setdefault(str(a["from_stage"]), []).append((end - start).days)
    return {k: sum(v) // len(v) for k, v in sorted(total.items())}


def _automation(ctx: Any, sids: set[str], unavailable: dict[str, str]) -> dict[str, Any]:
    """Rule runs (chain records ``rule_run``) and governance events with their actions."""
    runs = 0
    entries = ctx.tables.query(
        "chain_entry", {"record_type": "rule_run"}, order_by=("-ts",), limit=RUN_CAP
    )
    capped = len(entries) >= RUN_CAP  # the newest RUN_CAP runs; older ones are not counted
    if capped:
        unavailable["rule_runs"] = "capped"
    for e in entries:
        ref = str(e["record_ref"])
        if ref.startswith("system:") and ref[7:] in sids:
            runs += 1
    events = done = ok = bad = 0
    for ev in _bounded(ctx.state, "governance_event", unavailable, ("-started_at",)):
        if str(ev.get("system_id") or "") not in sids:  # an event of no system is no one's figure
            continue
        events += 1
        done += 1 if ev["status"] == "done" else 0
        raw = ev.get("actions")
        try:
            actions = raw if isinstance(raw, list) else json.loads(raw or "[]")
        except (TypeError, ValueError):
            actions = []
        for a in actions if isinstance(actions, list) else []:
            st = a.get("status") if isinstance(a, dict) else None
            ok += 1 if st in ACTION_OK else 0
            bad += 1 if st in ACTION_BAD else 0
    return {
        "rule_runs": runs,
        "rule_runs_capped": capped,
        "events": events,
        "events_done": done,
        "actions_ok": ok,
        "actions_failed": bad,
        "action_success_bp": bp(ok, ok + bad),
    }
