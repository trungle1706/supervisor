"""Systems pages (WP-G0): list with filter bar and row drawer, and the system detail page.

Read models over ``SystemService`` (``ctx.systems``). The list shows only the systems in the
caller's scope (``scope_for``). Filters are checked against allow-lists; a bad value is a
``ListingError`` (HTTP 400). A system outside the scope is reported as not existing."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from supervisor.cases.service import PermissionDenied
from supervisor.console import systems_duties, systems_riskdim, systems_tabs, systems_workflow, ux3
from supervisor.console.listing import (
    ListingError,
    paginate,
    parse_int,
    parse_sort,
    query_string,
    sort_rows,
)
from supervisor.core import rbac
from supervisor.core.errors import NotFoundError
from supervisor.governance import model as gm
from supervisor.governance.systems import ALL

COLUMNS = ("name", "owner_team", "lifecycle_stage", "risk", "status")
DRAWER_TABS = ("details", "team", "components")
DETAIL_TABS = (
    "overview",
    "components",
    "tasks",
    "reviews",  # tasks, reviews: WP-G1
    "rules",
    "classification",  # rules, classification: WP-G2
)
# WP-UX4b: the tabs with CONSOLE_NAV_V3 on (G2 tabs after Components).
DETAIL_TABS_V3 = (
    "overview",
    "components",
    "rules",
    "classification",
    "riskdim",  # WP-C2: only with RISK_DIMENSIONS (detail_tabs leaves it out otherwise)
    "risks",
    "controls",
    "policies",
    "guardians",
    "tasks",
    "duties",  # WP-L3: only with RISK_DUTIES (detail_tabs leaves it out otherwise)
    "reviews",
    "reports",
)
PAGE_SIZE = 25
FILTERS = ("q", "status", "owner_team", "lifecycle_stage", "risk", "system_type")
REGISTER_CHOICES = {
    "system_type": gm.SYSTEM_TYPES,
    "org_role": gm.ORG_ROLES,
    "user_segment": gm.USER_SEGMENTS,
    "personal_data": gm.PERSONAL_DATA,
    "human_control": gm.HUMAN_CONTROLS,
    "autonomy_level": gm.AUTONOMY_LEVELS,  # WP-G2
}


def parse_params(query: Mapping[str, str]) -> dict[str, str]:
    p = {
        "q": ux3.token(query, "q"),
        "status": ux3.choice(query, "status", gm.STATUSES),
        "owner_team": ux3.token(query, "owner_team"),
        "lifecycle_stage": ux3.choice(query, "lifecycle_stage", gm.LIFECYCLE_STAGES),
        "risk": ux3.choice(query, "risk", gm.RISK_LEVELS),
        "system_type": ux3.choice(query, "system_type", gm.SYSTEM_TYPES),
        "outcome": ux3.token(query, "outcome"),  # WP-C4: approved classification outcome or "none"
        "sort": query.get("sort") or "",
        "dir": query.get("dir") or "",
        "page": query.get("page") or "",
    }
    parse_int(p["page"], "page", 1)
    return p


def _risk_key(r: Mapping[str, Any]) -> int:
    return gm.rank(r.get("effective_risk_level"))


def _ordered(rows: list[dict[str, Any]], p: Mapping[str, str]) -> tuple[list[Any], str, str]:
    col, direction = parse_sort(p["sort"], p["dir"], COLUMNS, "name", "asc")
    return sort_rows(rows, col, direction, {"risk": _risk_key}), col, direction


def _rows(ctx: Any, me: Any, p: Mapping[str, str]) -> list[dict[str, Any]]:
    svc = ctx.systems
    filters = {k: p[k] for k in FILTERS if p[k]}
    rows: list[dict[str, Any]] = svc.list_systems(svc.scope_for(me), filters)
    if p.get("outcome"):  # WP-C4: needs CLASSIFICATION_V2; a bad value or the flag off is HTTP 400
        from supervisor.console import portfolio

        keep = portfolio.outcome_filter(ctx, [str(r["system_id"]) for r in rows], p["outcome"])
        rows = [r for r in rows if str(r["system_id"]) in keep]
    return rows


def list_view(ctx: Any, me: Any, query: Mapping[str, str]) -> dict[str, Any]:
    p = parse_params(query)
    svc = ctx.systems
    everything = svc.list_systems(svc.scope_for(me), {})
    shown_all = _rows(ctx, me, p)
    shown, col, direction = _ordered(shown_all, p)
    page = paginate(shown, parse_int(p["page"], "page", 1), PAGE_SIZE)
    base = {k: p[k] for k in (*FILTERS, "outcome")}
    tiles = [
        {
            "label": "sy_tile_all",
            "n": len(everything),
            "on": not p["status"] and not p["risk"],
            "qs": query_string(base, status="", risk=""),
        },
        {
            "label": "sy_tile_active",
            "n": sum(1 for r in everything if r["status"] == "active"),
            "on": p["status"] == "active",
            "qs": query_string(base, status="active", risk=""),
        },
        {
            "label": "sy_tile_high",
            "n": sum(1 for r in everything if r["effective_risk_level"] in ("high", "prohibited")),
            "on": p["risk"] == "high",
            "qs": query_string(base, status="", risk="high"),
        },
    ]
    return {
        "page": page,
        "params": p,
        "sort_col": col,
        "sort_dir": direction,
        "tiles": tiles,
        "status_opts": [(s, f"sy_st_{s}") for s in gm.STATUSES],
        "stage_opts": [(s, f"sy_stage_{s}") for s in gm.LIFECYCLE_STAGES],
        "risk_opts": [(s, f"sy_risk_{s}") for s in gm.RISK_LEVELS],
        "type_opts": [(s, f"sy_system_type_{s}") for s in gm.SYSTEM_TYPES],
        "team_opts": [(t, t) for t in sorted({r["owner_team"] for r in everything})],
        "total_systems": len(everything),
        "base_qs": query_string(base),
        "list_qs": query_string({**base, "sort": col, "dir": direction}),
        "choices": {k: [(v, f"sy_{k}_{v}") for v in vs] for k, vs in REGISTER_CHOICES.items()},
        "scope_all": svc.scope_for(me) is ALL,
        "can_edit": getattr(me, "kind", "") == "user" and rbac.allowed(me.roles, "systems.edit"),
        # WP-UX4b: the link to the register wizard, with CONSOLE_NAV_V3
        "wizard": bool(ctx.settings.console_nav_v3)
        and getattr(me, "kind", "") == "user"
        and rbac.allowed(me.roles, "systems.edit"),
    }


def _need_visible(ctx: Any, me: Any, system_id: str) -> dict[str, Any]:
    try:
        gm.check_system_id(system_id)
        if system_id not in ctx.systems.scope_for(me):
            raise NotFoundError(system_id)
        return dict(ctx.systems.get(system_id))
    except (NotFoundError, gm.SystemsError):
        raise ListingError(f"AI system {system_id[:64]} does not exist") from None


def drawer_view(
    ctx: Any, me: Any, system_id: str, tab: str, query: Mapping[str, str]
) -> dict[str, Any]:
    if tab not in DRAWER_TABS:
        raise ListingError("unknown drawer tab")
    system = _need_visible(ctx, me, system_id)
    p = parse_params(query)
    rows, _, _ = _ordered(_rows(ctx, me, p), p)
    ids = [r["system_id"] for r in rows]
    i = ids.index(system_id) if system_id in ids else -1
    return {
        "s": system,
        "tab": tab,
        "tabs": DRAWER_TABS,
        "prev_id": ids[i - 1] if i > 0 else None,
        "next_id": ids[i + 1] if 0 <= i < len(ids) - 1 else None,
        "qs": query_string({k: v for k, v in p.items() if k != "page" and v}),
        "json_text": json.dumps(system, sort_keys=True, indent=2, default=str),
    }


def detail_tabs(ctx: Any, me: Any) -> tuple[str, ...]:
    """The tabs of the system page. WP-UX4b: with CONSOLE_NAV_V3 on, the governance tabs too (a
    tab needs the permission of the page it summarises). Off: the tabs of WP-G0 to WP-G2, and
    WP-G5's Reports tab (incidents) with GOVERNANCE_ACTIONS_ENABLED."""
    duties = systems_duties.is_on(ctx)  # WP-L3: the Duties tab (RISK_DUTIES)
    riskdim = systems_riskdim.is_on(ctx)  # WP-C2: the Risk assessment tab (RISK_DIMENSIONS)
    if not ctx.settings.console_nav_v3:
        tabs = DETAIL_TABS
        if getattr(ctx.settings, "governance_actions_enabled", False) and "reports" not in tabs:
            tabs = (*tabs, "reports")
        tabs = (*tabs, "duties") if duties else tabs
        return (*tabs, "riskdim") if riskdim else tabs
    return tuple(
        t
        for t in DETAIL_TABS_V3
        if (t != "duties" or duties)
        and (t != "riskdim" or riskdim)
        and (t not in systems_tabs.TAB_PERM or systems_tabs.may(me, systems_tabs.TAB_PERM[t]))
    )


def detail_view(
    ctx: Any, me: Any, system_id: str, tab: str, query: Mapping[str, str] | None = None
) -> dict[str, Any]:
    tabs = detail_tabs(ctx, me)
    v3 = bool(ctx.settings.console_nav_v3)
    if tab not in tabs:
        if tab in DETAIL_TABS_V3 and v3 and tab not in ("duties", "riskdim"):
            raise PermissionDenied(f"your role may not open the {tab} tab")
        raise ListingError("unknown tab")
    system = _need_visible(ctx, me, system_id)
    extra, counts = g1_tabs(ctx, system, tab)
    if tab == "tasks" and systems_workflow.is_on(ctx):  # WP-P1: the buttons of the tab
        extra["wf"] = systems_workflow.tab_data(ctx, me, system, extra)
    if systems_duties.is_on(ctx):  # WP-L3: the gap closure score is on every tab; the tab itself
        extra["duty_score"] = systems_duties.header(ctx, system)
        extra["rp_pack"] = systems_duties.pack_on(ctx)  # WP-L4: Regulator pack link in the header
        counts["duties"] = extra["duty_score"]["open"]
        if tab == "duties":
            if getattr(ctx.settings, "console_ux5", False):  # UX5 (G2): one group per framework
                extra.update(systems_duties.tab_data_ux5(ctx, me, system, query or {}))
            else:
                extra.update(systems_duties.tab_data(ctx, me, system, query or {}))
    if tab == "guardians":  # WP-G4: the smart guardian panel (SMART_GUARDIAN)
        from supervisor.console import smart_guardian_view

        extra.update(smart_guardian_view.panel_data(ctx, me, system))
    if tab == "riskdim":  # WP-C2: the eight rows (made on the first read)
        extra.update(systems_riskdim.tab_data(ctx, me, system))
        counts["riskdim"] = systems_riskdim.open_count(extra["rd_counts"])
    if v3 and tab in systems_tabs.BUILDERS:  # WP-UX4b
        gov = systems_tabs.BUILDERS[tab](ctx, system)
        extra.update(gov)
        n = systems_tabs.count_of(tab, gov)
        if n is not None:
            counts[tab] = n
    actions_on = bool(getattr(ctx.settings, "governance_actions_enabled", False))
    if "reports" in tabs and actions_on:  # WP-G5: the incidents of the system
        from supervisor.console.incidents_views import system_incidents

        found = system_incidents(ctx, str(system["system_id"]))
        if not v3:
            counts["reports"] = len(found)
        if tab == "reports":
            extra["incidents"] = found  # the G5 template (CONSOLE_NAV_V3 off)
            extra["rp_incidents"], extra["rp_incidents_na"] = found, ""  # the UX4b Reports tab
    elif tab == "reports":
        extra["rp_incidents"], extra["rp_incidents_na"] = None, "ux4b_na_incidents_flag"
    out = {
        "s": system,
        "tab": tab,
        "tabs": tabs,
        "tab_counts": {
            "overview": len(system["team"]),
            "components": len(system["components"]),
            **counts,
        },
        "json_text": json.dumps(system, sort_keys=True, indent=2, default=str),
        **extra,
    }
    if getattr(ctx.settings, "console_ux5", False):  # UX5 (G2): names for the components list
        out["ref_names"] = _ref_names(ctx, system)
    if tab == "rules":  # WP-G2
        out.update(_rules_data(ctx, me, system_id))
    elif tab == "classification":
        out.update(_classification_data(ctx, me, system_id))
    return out


def _can_edit(me: Any) -> bool:
    return getattr(me, "kind", "") == "user" and rbac.allowed(me.roles, "systems.edit")


def _rules_data(ctx: Any, me: Any, system_id: str) -> dict[str, Any]:
    """WP-G2 Rules tab: what the rules put on the system (active first), the guardian floor."""
    from supervisor.governance.rules import load_rules

    rows = ctx.rules.assignments(system_id, active_only=False)
    rows.sort(key=lambda r: (not r["active"],))  # stable: active rows first, kind order kept
    try:
        sha = load_rules(ctx.settings.assignment_rules_config).sha256
    except Exception:  # noqa: BLE001 - the tab still shows the saved rows
        sha = ""
    out_ux5: dict[str, Any] = {}
    if getattr(ctx.settings, "console_ux5", False):  # UX5 (G2): identical rows grouped by rule
        out_ux5["rule_groups"] = group_assignments(rows)
    return {
        **out_ux5,
        "assignments": rows,
        "floor": ctx.rules.guardian_floor(system_id),
        "rules_sha": sha,
        "can_edit": _can_edit(me),
    }


def _ref_names(ctx: Any, system: Mapping[str, Any]) -> dict[str, str]:
    """UX5: ``ref_id -> display name`` of the inventory nodes a system is built from."""
    names: dict[str, str] = {}
    for c in system["components"]:
        if c["ref_kind"] != "agent":
            row = ctx.state.get("inventory_node", {"node_id": c["ref_id"]})
            if row:
                names[str(c["ref_id"])] = str(row.get("display_name") or row.get("name") or "")
    for v in system["effective_risk"].get("via") or []:
        if v["ref_kind"] != "agent" and str(v["ref_id"]) not in names:
            row = ctx.state.get("inventory_node", {"node_id": v["ref_id"]})
            if row:
                names[str(v["ref_id"])] = str(row.get("display_name") or row.get("name") or "")
    return names


def group_assignments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """UX5: the assignment rows grouped by the rules that fired (same rules, same fields), with the
    count of obligations, guardians, ... per kind. Order: the first row of each group."""
    groups: dict[tuple[str, ...], dict[str, Any]] = {}
    for a in rows:
        key = tuple(sorted({str(r["rule"]) for r in a["rules"]}))
        g = groups.setdefault(
            key, {"rules": list(key), "fields": [], "kinds": {}, "n": 0, "active": 0, "items": []}
        )
        for r in a["rules"]:
            for f in r.get("fields") or []:
                if f not in g["fields"]:
                    g["fields"].append(f)
        g["n"] += 1
        g["active"] += 1 if a["active"] else 0
        g["kinds"][a["kind"]] = g["kinds"].get(a["kind"], 0) + 1
        g["items"].append({"kind": a["kind"], "ref_id": a["ref_id"], "active": bool(a["active"])})
    return list(groups.values())


def _classification_data(ctx: Any, me: Any, system_id: str) -> dict[str, Any]:
    """WP-G2 Classification tab: the open draft, the applied class, the history count."""
    data = ctx.classification.get(system_id)
    draft = data["draft"]
    return {
        "cls": data,
        "ai_pending": bool(draft and any(a["source"] == "ai_prefill" for a in draft["answers"])),
        "can_edit": _can_edit(me),
        # WP-P2 (phase 8): the least justification length when CONSOLE_STATE_ACTIONS is on
        "min_why": 20 if getattr(ctx.settings, "console_state_actions", False) else 0,
    }


def classification_changes(form: Mapping[str, str], draft: Mapping[str, Any]) -> dict[str, Any]:
    """The answers of the classification form that differ from the draft: question id ->
    ``{answer, justification}``. A field the person did not touch keeps its source."""
    changes: dict[str, Any] = {}
    for a in draft["answers"]:
        qid = a["id"]
        if f"a_{qid}" not in form:
            continue
        raw = form.get(f"a_{qid}", "")
        answer = raw if raw in ("yes", "no") else None
        why = (form.get(f"j_{qid}") or "").strip()
        if answer != a["answer"] or why != (a.get("justification") or ""):
            changes[qid] = {"answer": answer, "justification": why}
    return changes


def g1_tabs(ctx: Any, system: Mapping[str, Any], tab: str) -> tuple[dict[str, Any], dict[str, int]]:
    """WP-G1: data of the Tasks and Reviews tabs and their counts. Read only."""
    sid = str(system["system_id"])
    counts: dict[str, int] = {}
    extra: dict[str, Any] = {}
    reviews = ctx.reviews.list_reviews(sid)
    counts["reviews"] = len(reviews)
    if tab == "reviews":
        extra["reviews"] = reviews
    agents = [c["ref_id"] for c in system["components"] if c["ref_kind"] == "agent"]
    # WP-G3 review M1: tasks opened on the system itself (agent_id = system id), for example
    # "Confirm context" on a draft made by the workspace scan.
    own = ctx.tasks.list_tasks({"agent": sid})
    counts["tasks"] = len(agents) + (1 if own else 0)
    if tab == "tasks":
        extra["lifecycle"] = ctx.lifecycle.status(sid)
        extra["task_n"] = len(agents) + (1 if own else 0)
        extra["tk_off"] = not ctx.settings.controls_enabled
        summaries: list[dict[str, Any]] = []
        for agent_id in agents if not extra["tk_off"] else []:
            try:
                summaries.append(ctx.tasks.agent_summary(agent_id))
            except Exception:  # noqa: BLE001 - one agent without a list must not stop the tab
                summaries.append({"agent_id": agent_id, "generated": False, "tasks": []})
        if own:
            summaries.insert(
                0, {"agent_id": sid, "system_own": True, "generated": True, "tasks": own}
            )
        extra["task_agents"] = summaries
    return extra, counts


def agents_system_col(ctx: Any) -> bool:
    """WP-UX4b: the System column and the unlinked filter of Catalogues > Agents need both
    CONSOLE_NAV_V3 and GOVERNANCE_ENABLED (without them the page is the one it was)."""
    return bool(ctx.settings.console_nav_v3 and ctx.settings.governance_enabled)


def annotate_agents(ctx: Any, me: Any, cards: list[dict[str, Any]]) -> None:
    """Add ``systems`` to each agent card: the systems the caller may see that this agent is
    linked to (``[{system_id, name}]``), and ``systems_hidden`` when it is linked only to
    systems outside the caller's scope (shown as linked, never named)."""
    svc = ctx.systems
    scope = svc.scope_for(me)
    names = {r["system_id"]: str(r["name"]) for r in svc.state.query("ai_system")}
    linked: dict[str, list[str]] = {}
    for c in svc.state.query("system_component", {"ref_kind": "agent"}):
        if str(c["active"]).strip().lower() in ("1", "true"):
            linked.setdefault(str(c["ref_id"]).lower(), []).append(str(c["system_id"]))
    for card in cards:
        ids = sorted(set(linked.get(str(card["agent_id"]).lower(), [])))
        seen = [i for i in ids if i in scope and i in names]
        card["systems"] = [{"system_id": i, "name": names[i]} for i in seen]
        card["systems_hidden"] = bool(ids) and not seen
        if card["systems_hidden"]:
            card["systems"] = [{"system_id": "", "name": ""}]  # linked, not shown


def draft_from_form(form: Mapping[str, str], me: Any) -> dict[str, Any]:
    """The intake draft from the register form. Only the form fields; the service validates."""
    keys = (
        "name",
        "owner_team",
        "purpose",
        "business_owner",
        *REGISTER_CHOICES,
    )
    out: dict[str, Any] = {k: form[k] for k in keys if form.get(k, "") != ""}
    out["owner_user"] = form.get("owner_user") or str(me.user_id)
    for flag in ("money_movement", "credit_decision"):
        out[flag] = form.get(flag, "") in ("1", "true", "on")
    return out
