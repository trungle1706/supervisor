"""My overview and Governance overview on AI systems (WP-UX4b).

With GOVERNANCE_ENABLED on and CONSOLE_NAV_V3 on, the two overview pages count **systems**, not
agents. With GOVERNANCE_ENABLED off the pages keep the agent-based path of WP-UX4a
(``overview_v3``), unchanged and tested.

Same rules as ``overview_v3``: read only, integers or basis points, a figure that cannot be
computed is ``None`` with a ``na`` reason key. The scope switch (my, team, all) works on
systems: my = systems I own or am on in the team; team = systems of the teams I work in
(``SystemService.teams_of``); all = every system the role may see (``SystemService.scope_for``).

The breakdown by ``autonomy_level`` appears only when WP-G2 added the column."""

from __future__ import annotations

import datetime as dt
from typing import Any

from supervisor.console import overview_v3, readmodels, systems_tabs
from supervisor.console.overview_v3 import SCOPES, ScopeError, tile
from supervisor.core import rbac
from supervisor.governance import model as gm


def _on(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true")


# ------------------------------------------------------------------------------ data


def components_by_system(ctx: Any) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for c in ctx.state.query("system_component"):
        if _on(c["active"]):
            out.setdefault(str(c["system_id"]), []).append(dict(c))
    return out


def memberships(ctx: Any, user_id: str) -> set[str]:
    return {
        str(m["system_id"])
        for m in ctx.state.query("system_team", {"user_id": user_id})
        if _on(m["active"])
    }


def in_scope(ctx: Any, me: Any, scope: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``rows`` are the systems the role may see (``list_systems`` with ``scope_for``)."""
    if scope == "all":
        return list(rows)
    uid = str(me.user_id)
    member = memberships(ctx, uid)
    mine = [r for r in rows if r["owner_user"] == uid or r["system_id"] in member]
    if scope == "my":
        return mine
    teams = ctx.systems.teams_of(uid) | {r["owner_team"] for r in mine}
    return [r for r in rows if r["owner_team"] in teams]


def parse_scope(raw: str | None, rows: list[dict[str, Any]], ctx: Any, me: Any) -> str:
    if raw in (None, ""):
        return "my" if in_scope(ctx, me, "my", rows) else "all"
    if raw not in SCOPES:
        raise ScopeError("scope must be my, team or all")
    return raw


def risk_detail(rows: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """(i18n key, count) by effective risk level, highest first."""
    out = []
    for level in reversed(gm.RISK_LEVELS):
        n = sum(1 for r in rows if r["effective_risk_level"] == level)
        if n:
            out.append((f"sy_risk_{level}", n))
    return out


def agent_ids_of(
    comps: dict[str, list[dict[str, Any]]], rows: list[dict[str, Any]], cards: dict[str, str]
) -> dict[str, list[str]]:
    """system id -> agent ids as the registry spells them (the component may differ in case)."""
    out: dict[str, list[str]] = {}
    for r in rows:
        ids = []
        for c in comps.get(r["system_id"], []):
            if c["ref_kind"] == "agent":
                ids.append(cards.get(str(c["ref_id"]).lower(), str(c["ref_id"])))
        out[r["system_id"]] = sorted(set(ids))
    return out


def _visible(ctx: Any, me: Any) -> list[dict[str, Any]]:
    svc = ctx.systems
    return svc.list_systems(svc.scope_for(me), {})  # type: ignore[no-any-return]


# ----------------------------------------------------------------------------- actions


def pending_of(ctx: Any, system_id: str) -> list[dict[str, Any]]:
    """Stage approvals of the system that wait for an answer; none if they cannot be read."""
    try:
        return [a for a in ctx.lifecycle.approvals(system_id) if a["status"] == "pending"]
    except Exception:  # noqa: BLE001 - a convenience list, never a page failure
        return []


def open_required_n(ctx: Any, task_owner_id: str) -> int:
    try:
        return len(ctx.tasks.open_required(task_owner_id))
    except Exception:  # noqa: BLE001 - an id without a task list counts nothing
        return 0


def stage_approvals(ctx: Any, me: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stage approvals that wait for an answer and that this person may decide."""
    if getattr(me, "kind", "user") != "user" or not rbac.allowed(me.roles, "systems.approve"):
        return []
    out = []
    for r in rows:
        try:
            may = ctx.lifecycle.can_decide(r, str(me.user_id), me.roles)
        except Exception:  # noqa: BLE001 - a convenience list, never a page failure
            may = False
        for a in pending_of(ctx, r["system_id"]) if may else []:
            out.append(
                {
                    "kind": "stage",
                    "text": f"{r['name']}: {a['from_stage']} -> {a['to_stage']}",
                    "href": f"/console/systems/{r['system_id']}",
                    "due": None,
                    "from_stage": a["from_stage"],
                    "to_stage": a["to_stage"],
                    "name": r["name"],
                }
            )
    return out


def my_ids(ctx: Any, me: Any) -> tuple[set[str], list[dict[str, Any]]]:
    """Ids whose open required tasks wait on this person: the agents they own, the agents of
    their systems and the systems themselves (a system has its own initiation tasks)."""
    rows = _visible(ctx, me)
    mine = in_scope(ctx, me, "my", rows)
    comps = components_by_system(ctx)
    ids = set(overview_v3.own_ids_of(ctx, me))
    for r in mine:
        ids.add(r["system_id"])
        ids |= {str(c["ref_id"]) for c in comps.get(r["system_id"], []) if c["ref_kind"] == "agent"}
    return ids, rows


def actions(ctx: Any, me: Any) -> dict[str, Any]:
    ids, rows = my_ids(ctx, me)
    base = overview_v3.open_actions(ctx, me, ids)
    stage = stage_approvals(ctx, me, rows)
    items = base["items"] + stage
    return {**base, "items": items, "n": len(items), "stages": len(stage)}


def actions_count(ctx: Any, me: Any) -> int:
    """The badge of My overview with systems on: the number of the page."""
    return int(actions(ctx, me)["n"])


# --------------------------------------------------------------------------- My overview


def next_action(
    sid: str, agents: list[str], tasks: list[dict[str, Any]], waiting: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """The first open required task of the system (its own or of its agents), else the stage
    approval that waits. None when there is nothing."""
    ids = {sid, *agents}
    open_ = [
        t
        for t in tasks
        if t["agent_id"] in ids and t["required"] and t["status"] in ("open", "in_progress")
    ]
    if open_:
        first = sorted(open_, key=lambda t: (str(t.get("due_at") or "9"), t["task_id"]))[0]
        return {"kind": "task", "text": str(first["title"]), "overdue": bool(first.get("overdue"))}
    ap = waiting.get(sid)
    if ap:
        return {
            "kind": "stage",
            "text": f"{ap['from_stage']} -> {ap['to_stage']}",
            "overdue": False,
        }
    return None


def health_rows(
    ctx: Any,
    scoped: list[dict[str, Any]],
    by_cards: dict[str, dict[str, Any]],
    agents_of: dict[str, list[str]],
    cov: dict[str, Any],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    if ctx.settings.controls_enabled:
        try:
            tasks = ctx.tasks.list_tasks()
        except Exception:  # noqa: BLE001
            tasks = []
    waiting: dict[str, dict[str, Any]] = {}
    for r in scoped:
        pend = pending_of(ctx, r["system_id"])
        if pend:
            waiting[r["system_id"]] = pend[0]
    rows = []
    for r in scoped:
        ag = agents_of.get(r["system_id"], [])
        if not ag or cov["covered"] is None:  # no agent, or no mandatory detector defined
            guard = None
        else:
            below = [a for a in ag if not (cov["by_agent"].get(a) or {}).get("full")]
            guard = {"total": len(ag), "full": not below, "below": below}
        rows.append(
            {
                "system_id": r["system_id"],
                "name": r["name"],
                "stage": r["lifecycle_stage"],
                "risk": r["effective_risk_level"],
                "agents": len(ag),
                "guard": guard,
                "open_cases": sum(int((by_cards.get(a) or {}).get("open_cases", 0)) for a in ag),
                "next": next_action(r["system_id"], ag, tasks, waiting),
            }
        )
    return rows


def my_overview(ctx: Any, me: Any, scope_raw: str | None, now: dt.datetime) -> dict[str, Any]:
    rows = _visible(ctx, me)
    scope = parse_scope(scope_raw, rows, ctx, me)
    scoped = in_scope(ctx, me, scope, rows)
    comps = components_by_system(ctx)
    cards = readmodels.agent_cards(ctx, me)
    by_lower = {c["agent_id"].lower(): c["agent_id"] for c in cards}
    by_cards = {c["agent_id"]: c for c in cards}
    agents_of = agent_ids_of(comps, scoped, by_lower)
    all_agents = sorted({a for ag in agents_of.values() for a in ag if a in by_cards})
    cov = overview_v3.cover_for(ctx, [by_cards[a] for a in all_agents])
    health = health_rows(ctx, scoped, by_cards, agents_of, cov)
    # guardian coverage: systems with an agent, covered = every agent has its mandatory detectors
    with_agents = [h for h in health if h["guard"] is not None]
    covered = sum(1 for h in with_agents if h["guard"]["full"])
    if cov["covered"] is None:
        cover = tile("cover", None, "", cov["na"], of=0)
    else:
        cover = tile(
            "cover",
            covered,
            "" if cov["master"] else "nv3_cover_master_off",
            "",
            of=len(with_agents),
            idle=len(health) - len(with_agents),
        )
    acts = actions(ctx, me)
    models = overview_v3._asset_count(ctx, "models")  # noqa: SLF001 - same tile as UX4a
    tiles = [
        tile("systems", len(scoped), "", "", tiers=risk_detail(scoped)),
        (
            tile("models", models[0], "", "", unmanaged=models[1])
            if models is not None
            else tile("models", None, "", "nv3_na_inventory_off", unmanaged=0)
        ),
        cover,
        tile(
            "actions",
            acts["n"],
            "",
            "",
            cases=acts["cases"],
            approvals=acts["approvals"],
            tasks=acts["tasks"],
            stages=acts["stages"],
        ),
    ]
    ids = {a for ag in agents_of.values() for a in ag}
    recent = [e for e in readmodels.latest_decisions(ctx, 40) if e["agent_id"] in ids][:6]
    return {
        "unit": "systems",
        "scope": scope,
        "scopes": SCOPES,
        "tiles": tiles,
        "rows": health,
        "actions": acts["items"][:10],
        "actions_n": acts["n"],
        "recent": recent,
        "cases_n": len(readmodels.open_cases(ctx)),
        "clock": overview_v3._nearest_clock(ctx, now),  # noqa: SLF001
        "systems_page": bool(ctx.settings.console_systems_enabled),
    }


# ------------------------------------------------------------------ Governance overview


def _autonomy(scoped: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Systems by autonomy level, only when the column exists (WP-G2); else None."""
    if not any("autonomy_level" in r for r in scoped):
        return None  # WP-G2 not merged (no column), or no system in scope
    counts: dict[str, int] = {}
    for r in scoped:
        key = str(r.get("autonomy_level") or "-")
        counts[key] = counts.get(key, 0) + 1
    return {"rows": sorted(counts.items())}


def governance_overview(
    ctx: Any, me: Any, scope_raw: str | None, now: dt.datetime
) -> dict[str, Any]:
    rows = _visible(ctx, me)
    scope = parse_scope(scope_raw, rows, ctx, me)
    scoped = in_scope(ctx, me, scope, rows)
    comps = components_by_system(ctx)
    cards = readmodels.agent_cards(ctx, me)
    by_lower = {c["agent_id"].lower(): c["agent_id"] for c in cards}
    agents_of = agent_ids_of(comps, scoped, by_lower)
    ids = {a for ag in agents_of.values() for a in ag}
    task_ids = ids | {r["system_id"] for r in scoped}
    s = ctx.settings
    classified = sum(1 for r in scoped if r.get("decision33_class") not in (None, "unclassified"))
    class_tile = (
        tile("classified", classified * 10000 // len(scoped), "", "", n=classified, of=len(scoped))
        if scoped
        else tile("classified", None, "", "ux4b_na_no_systems", n=0, of=0)
    )
    # control readiness per system: latest status of each control for each agent of the system
    ready_rows: list[dict[str, Any]] = []
    if not s.controls_enabled:
        ready = tile("readiness", None, "", "nv3_na_controls_off", n=0, of=0, capped=False)
    else:
        latest, capped = overview_v3._latest_status(ctx, ids)  # noqa: SLF001
        working = 0
        total = 0
        for r in scoped:
            ag = set(agents_of.get(r["system_id"], []))
            vals = [v for (cid, aid), v in latest.items() if aid in ag]
            w = sum(1 for v in vals if v == "working")
            working += w
            total += len(vals)
            ready_rows.append(
                {
                    "system_id": r["system_id"],
                    "name": r["name"],
                    "working": w,
                    "total": len(vals),
                    "bp": w * 10000 // len(vals) if vals else None,
                }
            )
        ready = (
            tile("readiness", working * 10000 // total, "", "", n=working, of=total, capped=capped)
            if total
            else tile("readiness", None, "", "nv3_na_no_status", n=0, of=0, capped=False)
        )
    # tasks: overdue and the stage table
    pending_by_stage: dict[str, int] = {}
    for r in scoped:
        # a pending request is counted on the stage the system is in now (it waits to leave it)
        for a in pending_of(ctx, r["system_id"]):
            pending_by_stage[a["from_stage"]] = pending_by_stage.get(a["from_stage"], 0) + 1
    if not s.controls_enabled:
        overdue = tile("overdue", None, "", "nv3_na_controls_off", oldest=None)
    else:
        tasks = ctx.tasks.list_tasks()
        late = [t for t in tasks if t["agent_id"] in task_ids and t["overdue"] and t["required"]]
        overdue = tile("overdue", len(late), "", "", oldest=overdue_days(late, now))
    by_stage: dict[str, dict[str, int]] = {}
    for r in scoped:
        row = by_stage.setdefault(r["lifecycle_stage"], {"systems": 0, "open": 0})
        row["systems"] += 1
        if s.controls_enabled:
            for aid in {r["system_id"], *agents_of.get(r["system_id"], [])}:
                row["open"] += open_required_n(ctx, aid)
    stage_rows = [
        {"stage": st, **by_stage[st], "pending": pending_by_stage.get(st, 0)}
        for st in gm.LIFECYCLE_STAGES
        if st in by_stage
    ]
    policy = _policy_rows(ctx, scoped, comps)
    return {
        "unit": "systems",
        "scope": scope,
        "scopes": SCOPES,
        "total": len(rows),
        "tiles": [
            tile("systems", len(scoped), "", "", tiers=risk_detail(scoped)),
            class_tile,
            ready,
            overdue,
        ],
        "stages": stage_rows,
        "open_na": not s.controls_enabled,
        "ready_rows": ready_rows,
        "risks": overview_v3._risk_posture(  # noqa: SLF001
            ctx, {a.lower() for a in ids}, "systems"
        ),
        "policy": policy,
        "autonomy": _autonomy(scoped),
        "systems_page": bool(ctx.settings.console_systems_enabled),
    }


def overdue_days(rows: list[dict[str, Any]], now: dt.datetime) -> int | None:
    return overview_v3._oldest_days(rows, now)  # noqa: SLF001


def _policy_rows(
    ctx: Any, scoped: list[dict[str, Any]], comps: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """Compliance matrix figures per system, in basis points (obligations that apply, met)."""
    if not ctx.settings.console_compliance_enabled:
        return {"na": "nv3_na_compliance_off", "rows": []}
    out = []
    for r in scoped:
        data = systems_tabs.policies_tab(
            ctx, {"system_id": r["system_id"], "components": comps.get(r["system_id"], [])}
        )
        if data["pl_bp"] is None and not data["pl_rows"]:
            continue
        out.append(
            {
                "system_id": r["system_id"],
                "name": r["name"],
                "applies": data["pl_applies"],
                "met": data["pl_met"],
                "gap": data["pl_gap"],
                "bp": data["pl_bp"],
            }
        )
    return {"na": "", "rows": out}
