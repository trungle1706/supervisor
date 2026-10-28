"""My overview as a dashboard, and the candidate triage pages (WP-N1, CONSOLE_OVERVIEW_V4).

Read only: nothing here writes, and no table is added. Numbers are integers or basis points. The
data of the page is built on the helpers of ``systems_overview`` and ``overview_v3`` (scope,
actions, health rows, guardian cover); the triage rows come from ``governance.triage``.

Registration pipeline (counts of systems in scope that meet each condition; a system can be in
several stages, so the figures are a funnel, not a partition):

    candidates (unmanaged, no draft)  >  draft  >  intake confirmed  >  classified  >  guarded
    >  in production (lifecycle stage ``operation``)
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from supervisor.console import overview_v3, readmodels, systems_overview
from supervisor.console.listing import paginate, parse_int, parse_sort, query_string, sort_rows
from supervisor.console.overview_v3 import SCOPES
from supervisor.core.errors import SupervisorError
from supervisor.governance import duties_gap, triage
from supervisor.governance import model as gm
from supervisor.governance.guardians import instance_on
from supervisor.governance.next_action import (
    SHADOW_DAYS,
    describe_agent,
    describe_system,
    recommend,
    shadow_days,
)
from supervisor.inventory.service import InventoryService

CONFIRM_TASK = "SYS-INTAKE-CONFIRM"
CHECKS_TASK = "SYS-INTAKE-CHECKS"
STAGES = ("candidates", "draft", "intake", "classified", "guarded", "production")
DIMENSIONS = ("intake", "class", "checks", "guardians", "tasks")
LEVELS: tuple[str, ...] = tuple(x for x in triage.AUTONOMY_ORDER if x != "unspecified") + (
    "unspecified",
)
RISKS: tuple[str, ...] = ("prohibited", "high", "medium", "low", "unspecified")
CAND_SORTS = ("score", "impact", "autonomy", "kind", "name")
CAND_PAGE_TOP = 10
CAND_PAGE_FULL = 20
OPEN_TASK = ("open", "in_progress")


class CandidateError(SupervisorError):
    """Bad filter or page of the candidate list (HTTP 400)."""


def _on(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true")


# ------------------------------------------------------------------------- candidates


def load_candidates(ctx: Any) -> list[dict[str, Any]] | None:
    """Triage rows of the unmanaged candidates that no system component covers yet. None when the
    inventory is off (the page says so)."""
    if not ctx.settings.inventory_enabled:
        return None
    g = InventoryService.from_adapters(ctx.runtime.adapters).store.load_graph()
    # any component row covers the node, active or not (a removed link keeps the history)
    taken = {str(c["ref_id"]) for c in ctx.state.query("system_component", {"ref_kind": "node"})}
    return triage.triage(g, exclude=taken)


def _bad(what: str) -> CandidateError:
    return CandidateError(f"unknown {what} filter")


def candidates_view(
    rows: list[dict[str, Any]], query: Any, *, size: int, with_filters: bool
) -> dict[str, Any]:
    """Filter, sort and page the triage rows. An unknown filter value is HTTP 400; an unknown sort
    column falls back to the score; a bad page is a ``ListingError`` (HTTP 400)."""
    kind = query.get("kind") or ""
    signal = query.get("signal") or ""
    band = query.get("band") or ""
    if with_filters:
        if kind and kind not in triage.KINDS:
            raise _bad("kind")
        if signal and signal not in triage.SIGNALS:
            raise _bad("signal")
        if band and band not in triage.BANDS:
            raise _bad("score band")
    else:
        kind = signal = band = ""
    items = triage.filter_rows(rows, kind, signal, band)
    col, direction = parse_sort(query.get("sort"), query.get("dir"), CAND_SORTS, "score", "desc")
    keys = {
        "autonomy": lambda r: r["autonomy_rank"],
        "name": lambda r: r["name"].lower(),
    }
    items = sort_rows(items, col, direction, keys)
    pg = paginate(items, parse_int(query.get("page"), "page", 1), size)
    filters = {"kind": kind, "signal": signal, "band": band}
    return {
        "cand_page": pg,
        "cand_sort_col": col,
        "cand_sort_dir": direction,
        "cand_filters": filters,
        "cand_base_qs": query_string(filters),
        "cand_list_qs": query_string({**filters, "sort": col, "dir": direction}),
        "cand_kind_opts": [(k, f"tri_kind_{k}") for k in triage.KINDS],
        "cand_signal_opts": [(s, f"tri_sig_{s}") for s in triage.SIGNALS],
        "cand_band_opts": [(b, f"tri_band_{b}") for b in triage.BANDS],
        "cand_total": len(rows),
    }


def drawer_view(rows: list[dict[str, Any]], node_id: str) -> dict[str, Any]:
    for r in rows:
        if r["node_id"] == node_id:
            import json

            return {
                "c": r,
                "json_text": json.dumps(
                    {
                        k: r[k]
                        for k in (
                            "node_id",
                            "kind",
                            "name",
                            "impact",
                            "autonomy",
                            "complexity",
                            "score",
                            "signals",
                            "recommended_action",
                        )
                    },
                    sort_keys=True,
                    indent=2,
                ),
            }
    raise CandidateError("this candidate is not in the list (it may be registered or gone)")


def api_rows(rows: list[dict[str, Any]], query: Any) -> dict[str, Any]:
    """Body of ``GET /v1/candidates``: all filtered rows, sorted (default best first); no paging
    and no facts. Bad filter values are HTTP 400 as on the page."""
    q = {k: v for k, v in query.items() if k != "page"}  # the API does not page
    view = candidates_view(rows, q, size=1, with_filters=True)
    f = view["cand_filters"]
    items = triage.filter_rows(rows, f["kind"], f["signal"], f["band"])
    keys = {"autonomy": lambda r: r["autonomy_rank"], "name": lambda r: r["name"].lower()}
    items = sort_rows(items, view["cand_sort_col"], view["cand_sort_dir"], keys)
    return {
        "count": len(items),
        "total": len(rows),
        "items": [{k: v for k, v in r.items() if k != "facts"} for r in items],
    }


# ------------------------------------------------------------------------- my overview


def _tasks(ctx: Any) -> list[dict[str, Any]]:
    try:
        return list(ctx.tasks.list_tasks())
    except Exception:  # noqa: BLE001 - a convenience list, never a page failure
        return []


def _floor_state(ctx: Any, system_id: str) -> tuple[int, list[str]]:
    """(floor features, slugs the floor holds that are not effective on this instance)."""
    try:
        floor = [f["slug"] for f in ctx.rules.guardian_floor(system_id)]
    except Exception:  # noqa: BLE001
        return 0, []
    return len(floor), [s for s in floor if not instance_on(ctx.settings, s)]


def _risk_key(level: str) -> str:
    """i18n key of a risk word; the registry tier ``critical`` has its own label."""
    return f"sy_risk_{level}" if level in RISKS else "ov4_risk_critical"


def _intake_complete(row: dict[str, Any]) -> bool:
    return all(row.get(f) not in (None, "") for f in gm.REQUIRED)


def _banner(
    *,
    actions_n: int,
    overdue: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    top: dict[str, Any] | None,
) -> dict[str, Any]:
    high_overdue = [t for t in overdue if t.get("level") in ("high", "critical")]
    crit = [c for c in cases if c["severity"] == "critical"]
    high = [c for c in cases if c["severity"] == "high"]
    big = top is not None and top["score"] >= triage.HIGH_SCORE
    if high_overdue:
        return {
            "state": "attention",
            "why": "ov4_why_overdue_high",
            "arg": str(high_overdue[0]["title"]),
        }
    if crit:
        return {"state": "attention", "why": "ov4_why_critical", "arg": str(len(crit))}
    if big and top is not None:
        return {
            "state": "attention",
            "why": "ov4_why_candidate",
            "arg": f"{top['name']} ({top['score']})",
        }
    if overdue:
        return {"state": "work", "why": "ov4_why_overdue", "arg": str(len(overdue))}
    if high:
        return {"state": "work", "why": "ov4_why_high_case", "arg": str(len(high))}
    if actions_n:
        return {"state": "work", "why": "ov4_why_actions", "arg": str(actions_n)}
    return {"state": "good", "why": "ov4_why_good", "arg": ""}


def my_overview(
    ctx: Any, me: Any, scope_raw: str | None, now: dt.datetime, query: Any
) -> dict[str, Any]:
    rows = systems_overview._visible(ctx, me)  # noqa: SLF001 - same scope rules as UX4b
    scope = systems_overview.parse_scope(scope_raw, rows, ctx, me)
    scoped = systems_overview.in_scope(ctx, me, scope, rows)
    comps = systems_overview.components_by_system(ctx)
    cards = readmodels.agent_cards(ctx, me)
    by_lower = {c["agent_id"].lower(): c["agent_id"] for c in cards}
    by_cards = {c["agent_id"]: c for c in cards}
    agents_of = systems_overview.agent_ids_of(comps, scoped, by_lower)
    linked = {a for ag in agents_of.values() for a in ag if a in by_cards}
    loose = [
        c
        for c in overview_v3.in_scope(cards, me, scope)
        if c["agent_id"] not in {a for ag in agents_of.values() for a in ag}
    ]
    agent_ids = sorted(linked | {c["agent_id"] for c in loose})
    agent_cards = [by_cards[a] for a in agent_ids]
    cov = overview_v3.cover_for(ctx, agent_cards)
    health = systems_overview.health_rows(ctx, scoped, by_cards, agents_of, cov)
    tasks = _tasks(ctx)
    ids = {r["system_id"] for r in scoped} | set(agent_ids)
    by_task: dict[str, dict[str, dict[str, Any]]] = {}
    for t in tasks:
        by_task.setdefault(str(t["agent_id"]), {})[str(t["template_id"])] = t
    acts = systems_overview.actions(ctx, me)

    # ---- candidates
    cand = load_candidates(ctx)
    cand_view = (
        candidates_view(cand, query, size=CAND_PAGE_TOP, with_filters=False)
        if cand is not None
        else None
    )

    # ---- per system facts
    waiting = {}
    can = {}
    for r in scoped:
        pend = systems_overview.pending_of(ctx, r["system_id"])
        if pend:
            waiting[r["system_id"]] = pend[0]
            try:
                can[r["system_id"]] = bool(
                    getattr(me, "kind", "user") == "user"
                    and ctx.lifecycle.can_decide(r, str(me.user_id), me.roles)
                )
            except Exception:  # noqa: BLE001
                can[r["system_id"]] = False
    floor_of = {r["system_id"]: _floor_state(ctx, r["system_id"]) for r in scoped}

    def old_shadow(agents: list[str]) -> list[str]:
        out = []
        for a in agents:
            c = by_cards.get(a)
            age = shadow_days(c.get("created_at"), now) if c else None
            if c and c["state"] == "SHADOW" and age is not None and age > SHADOW_DAYS:
                out.append(a)
        return out

    system_cards = []
    by_id = {r["system_id"]: r for r in scoped}
    for h in health:
        sysrow = by_id[h["system_id"]]
        ag = agents_of.get(h["system_id"], [])
        rec = recommend(
            system=sysrow,
            agents=ag,
            tasks=tasks,
            waiting=waiting,
            can_decide=can.get(h["system_id"], False),
            below_floor=floor_of[h["system_id"]][1],
            shadow_agents=old_shadow(ag),
            open_cases=h["open_cases"],
            workflow=bool(ctx.settings.console_workflow_actions),
        )
        system_cards.append(
            {
                **h,
                "kind": "system",
                "risk_key": _risk_key(str(h["risk"])),
                "description": describe_system(sysrow),
                "autonomy": str(sysrow.get("autonomy_level") or "unspecified"),
                "agent_list": [
                    {"agent_id": a, "state": by_cards[a]["state"]} for a in ag if a in by_cards
                ],
                "recommended": rec,
            }
        )
    for c in loose:
        rec = recommend(
            system=None,
            agents=[c["agent_id"]],
            tasks=tasks,
            waiting={},
            can_decide=False,
            below_floor=[],
            shadow_agents=old_shadow([c["agent_id"]]),
            open_cases=int(c.get("open_cases", 0)),
            owner_id=c["agent_id"],
        )
        system_cards.append(
            {
                "kind": "agent",
                "system_id": "",
                "name": c["agent_id"],
                "stage": "",
                "risk": str(c.get("risk_tier") or "unspecified"),
                "risk_key": _risk_key(str(c.get("risk_tier") or "unspecified")),
                "agents": 1,
                "guard": (
                    None
                    if cov["covered"] is None
                    else {
                        "total": 1,
                        "full": bool((cov["by_agent"].get(c["agent_id"]) or {}).get("full")),
                        "below": [],
                    }
                ),
                "open_cases": int(c.get("open_cases", 0)),
                "next": None,
                "description": describe_agent(c),
                "autonomy": "unspecified",
                "agent_list": [{"agent_id": c["agent_id"], "state": c["state"]}],
                "recommended": rec,
            }
        )

    # ---- pipeline
    done = lambda sid, tid: (by_task.get(sid, {}).get(tid) or {}).get("status") == "done"  # noqa: E731
    pipeline = [
        ("candidates", len(cand) if cand is not None else None),
        ("draft", sum(1 for r in scoped if r["status"] == "draft")),
        ("intake", sum(1 for r in scoped if done(r["system_id"], CONFIRM_TASK))),
        (
            "classified",
            sum(1 for r in scoped if r.get("decision33_class") not in (None, "unclassified")),
        ),
        (
            "guarded",
            sum(
                1 for r in scoped if floor_of[r["system_id"]][0] and not floor_of[r["system_id"]][1]
            ),
        ),
        ("production", sum(1 for r in scoped if r["lifecycle_stage"] == "operation")),
    ]

    # ---- assessment completion (done, of)
    with_floor = [r for r in scoped if floor_of[r["system_id"]][0]]
    with_tasks = [r for r in scoped if any(t["agent_id"] == r["system_id"] for t in tasks)]
    with_checks = [r for r in scoped if CHECKS_TASK in by_task.get(r["system_id"], {})]
    open_req = {str(t["agent_id"]) for t in tasks if t["required"] and t["status"] in OPEN_TASK}
    assessment = [
        ("intake", sum(1 for r in scoped if _intake_complete(r)), len(scoped)),
        (
            "class",
            sum(1 for r in scoped if r.get("decision33_class") not in (None, "unclassified")),
            len(scoped),
        ),
        (
            "checks",
            sum(1 for r in with_checks if done(r["system_id"], CHECKS_TASK)),
            len(with_checks),
        ),
        (
            "guardians",
            sum(1 for r in with_floor if not floor_of[r["system_id"]][1]),
            len(with_floor),
        ),
        ("tasks", sum(1 for r in with_tasks if r["system_id"] not in open_req), len(with_tasks)),
    ]
    assess = [
        {"key": k, "done": d, "of": o, "bp": (d * 10000 // o) if o else None}
        for k, d, o in assessment
    ]
    if duties_gap.enabled(
        ctx.settings
    ):  # WP-L3: the duties dimension (absent while RISK_DUTIES is off)
        assess.append(duties_gap.overview_row(ctx.state, (r["system_id"] for r in scoped)))

    # ---- risk by autonomy
    grid: dict[str, dict[str, int]] = {lv: dict.fromkeys(RISKS, 0) for lv in LEVELS}
    for r in scoped:
        lv = str(r.get("autonomy_level") or "unspecified")
        lv = lv if lv in grid else "unspecified"
        rk = str(r.get("effective_risk_level") or "unspecified")
        grid[lv][rk if rk in RISKS else "unspecified"] += 1
    peak = max([sum(g.values()) for g in grid.values()] + [1])
    risk_rows = [
        {
            "level": lv,
            "total": sum(g.values()),
            "segs": [(rk, g[rk], g[rk] * 10000 // peak) for rk in RISKS if g[rk]],
        }
        for lv, g in grid.items()
    ]

    # ---- totals
    states: dict[str, int] = {}
    for c in agent_cards:
        states[c["state"]] = states.get(c["state"], 0) + 1
    open_cases = [c for c in readmodels.open_cases(ctx) if c["agent_id"] in set(agent_ids)]
    overdue = [t for t in tasks if t["overdue"] and t["required"] and t["agent_id"] in ids]
    models = overview_v3._asset_count(ctx, "models")  # noqa: SLF001
    with_agents = [h for h in health if h["guard"] is not None]
    totals = {
        "systems": len(scoped),
        "tiers": systems_overview.risk_detail(scoped),
        "agents": len(agent_ids),
        "states": states,
        "models": models[0] if models is not None else None,
        "cover": (
            None
            if cov["covered"] is None
            else {"n": sum(1 for h in with_agents if h["guard"]["full"]), "of": len(with_agents)}
        ),
        "cases": len(open_cases),
        "due": len(overdue),
    }
    top = cand[0] if cand else None
    banner = _banner(actions_n=acts["n"], overdue=overdue, cases=open_cases, top=top)
    banner["open_items"] = acts["n"] + len(open_cases)
    return {
        "unit": "systems",
        "scope": scope,
        "scopes": SCOPES,
        "banner": banner,
        "pipeline": pipeline,
        "assess": assess,
        "risk_rows": risk_rows,
        "risks": RISKS,
        "totals": totals,
        "actions": acts["items"][:10],
        "actions_n": acts["n"],
        "attention": [a for a in acts["items"] if a["kind"] in ("case", "approval", "stage")][:10],
        "waiting_input": [a for a in acts["items"] if a["kind"] == "task"][:10],
        "cand": cand_view,
        "cand_off": cand is None,
        "cards": system_cards,
        "cases_n": len(open_cases),
        "clock": overview_v3._nearest_clock(ctx, now),  # noqa: SLF001
        "systems_page": bool(ctx.settings.console_systems_enabled),
        "stages": STAGES,
    }
