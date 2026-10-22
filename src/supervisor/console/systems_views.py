"""Systems pages (WP-G0): list with filter bar and row drawer, and the system detail page.

Read models over ``SystemService`` (``ctx.systems``). The list shows only the systems in the
caller's scope (``scope_for``). Filters are checked against allow-lists; a bad value is a
``ListingError`` (HTTP 400). A system outside the scope is reported as not existing."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from supervisor.console import ux3
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
DETAIL_TABS = ("overview", "components", "tasks", "reviews")  # tasks, reviews: WP-G1
PAGE_SIZE = 25
FILTERS = ("q", "status", "owner_team", "lifecycle_stage", "risk", "system_type")
REGISTER_CHOICES = {
    "system_type": gm.SYSTEM_TYPES,
    "org_role": gm.ORG_ROLES,
    "user_segment": gm.USER_SEGMENTS,
    "personal_data": gm.PERSONAL_DATA,
    "human_control": gm.HUMAN_CONTROLS,
}


def parse_params(query: Mapping[str, str]) -> dict[str, str]:
    p = {
        "q": ux3.token(query, "q"),
        "status": ux3.choice(query, "status", gm.STATUSES),
        "owner_team": ux3.token(query, "owner_team"),
        "lifecycle_stage": ux3.choice(query, "lifecycle_stage", gm.LIFECYCLE_STAGES),
        "risk": ux3.choice(query, "risk", gm.RISK_LEVELS),
        "system_type": ux3.choice(query, "system_type", gm.SYSTEM_TYPES),
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
    return svc.list_systems(svc.scope_for(me), filters)


def list_view(ctx: Any, me: Any, query: Mapping[str, str]) -> dict[str, Any]:
    p = parse_params(query)
    svc = ctx.systems
    everything = svc.list_systems(svc.scope_for(me), {})
    shown_all = _rows(ctx, me, p)
    shown, col, direction = _ordered(shown_all, p)
    page = paginate(shown, parse_int(p["page"], "page", 1), PAGE_SIZE)
    base = {k: p[k] for k in FILTERS}
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


def detail_view(ctx: Any, me: Any, system_id: str, tab: str) -> dict[str, Any]:
    if tab not in DETAIL_TABS:
        raise ListingError("unknown tab")
    system = _need_visible(ctx, me, system_id)
    extra, counts = g1_tabs(ctx, system, tab)
    return {
        "s": system,
        "tab": tab,
        "tabs": DETAIL_TABS,
        "tab_counts": {
            "overview": len(system["team"]),
            "components": len(system["components"]),
            **counts,
        },
        "json_text": json.dumps(system, sort_keys=True, indent=2, default=str),
        **extra,
    }


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
    counts["tasks"] = len(agents)
    if tab == "tasks":
        extra["lifecycle"] = ctx.lifecycle.status(sid)
        extra["task_n"] = len(agents)
        extra["tk_off"] = not ctx.settings.controls_enabled
        summaries: list[dict[str, Any]] = []
        for agent_id in agents if not extra["tk_off"] else []:
            try:
                summaries.append(ctx.tasks.agent_summary(agent_id))
            except Exception:  # noqa: BLE001 - one agent without a list must not stop the tab
                summaries.append({"agent_id": agent_id, "generated": False, "tasks": []})
        extra["task_agents"] = summaries
    return extra, counts


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
