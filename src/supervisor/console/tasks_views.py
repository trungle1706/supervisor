"""Tasks page and Agent tab (WP30, read-only): filter, sort, page and row drawer over the task
list. Read model over ``TaskService`` (``ctx.tasks``). Tasks are changed through ``/v1/tasks``
(RBAC ``tasks.edit`` and ``tasks.approve``, two audit rows) or ``python -m supervisor.tasks``."""

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
from supervisor.core.errors import NotFoundError
from supervisor.tasks.model import STAGES, STATUSES, check_id

COLUMNS = ("agent_id", "stage", "template_id", "status", "due_at")
DRAWER_TABS = ("details", "history")
PAGE_SIZE = 25
FILTERS = ("agent", "stage", "status", "required", "q")


def parse_params(query: Mapping[str, str]) -> dict[str, str]:
    p = {
        "agent": ux3.ident(query, "agent"),
        "stage": ux3.choice(query, "stage", STAGES),
        "status": ux3.choice(query, "status", STATUSES),
        "required": ux3.choice(query, "required", ("true", "false")),
        "q": ux3.token(query, "q"),
        "sort": query.get("sort") or "",
        "dir": query.get("dir") or "",
        "page": query.get("page") or "",
    }
    parse_int(p["page"], "page", 1)
    return p


def _fits(r: Mapping[str, Any], p: Mapping[str, str]) -> bool:
    if p["agent"] and r["agent_id"].lower() != p["agent"].lower():
        return False
    if p["stage"] and r["stage"] != p["stage"]:
        return False
    if p["status"] and r["status"] != p["status"]:
        return False
    if p["required"] and str(r["required"]).lower() != p["required"]:
        return False
    if p["q"] and p["q"].lower() not in f"{r['task_id']} {r['template_id']} {r['title']}".lower():
        return False
    return True


def list_view(ctx: Any, query: Mapping[str, str]) -> dict[str, Any]:
    p = parse_params(query)
    if p["agent"]:
        check_id(p["agent"], "agent")
    svc = ctx.tasks
    everything = svc.list_tasks()
    ux5_on = bool(getattr(ctx.settings, "console_ux5", False))
    names: dict[str, str] = {}
    if ux5_on:  # UX5 (G2): the duty tasks belong to the Duties tab; the agent column shows names
        everything = [r for r in everything if not str(r["template_id"]).startswith("DUTY-")]
        names = {str(x["system_id"]): str(x["name"]) for x in ctx.state.query("ai_system")}
        if not any(k in query for k in ("required", "agent", "stage", "status", "q", "page")):
            p["required"] = "true"  # default view: required tasks
            p["status"] = "open"
    if ux5_on and p["q"]:  # the search also matches the system name
        needle = p["q"].lower()
        shown_all = [
            r
            for r in everything
            if _fits(r, {**p, "q": ""})
            and (
                needle in f"{r['task_id']} {r['template_id']} {r['title']}".lower()
                or needle in names.get(str(r["agent_id"]), "").lower()
            )
        ]
    else:
        shown_all = [r for r in everything if _fits(r, p)]
    col, direction = parse_sort(p["sort"], p["dir"], COLUMNS, "agent_id", "asc")
    shown = sort_rows(shown_all, col, direction)
    page = paginate(shown, parse_int(p["page"], "page", 1), PAGE_SIZE)
    base = {k: p[k] for k in FILTERS}
    open_req = [r for r in everything if r["required"] and r["status"] in ("open", "in_progress")]
    tiles = [
        {
            "label": "tk_tile_open_required",
            "n": len(open_req),
            "on": p["required"] == "true" and not p["status"],
            "qs": query_string(base, required="true", status=""),
        },
        {
            "label": "tk_tile_overdue",
            "n": sum(1 for r in open_req if r["overdue"]),
            "on": False,
            "qs": query_string(base, required="true", status=""),
        },
        {
            "label": "tk_tile_waiver",
            "n": sum(1 for r in everything if r["waive_pending"]),
            "on": False,
            "qs": query_string(base, status=""),
        },
    ]
    return {
        "page": page,
        "params": p,
        "sort_col": col,
        "sort_dir": direction,
        "tiles": tiles,
        "agent_opts": [(a, a) for a in sorted({r["agent_id"] for r in everything})],
        "stage_opts": [(s, f"tk_stage_{s}") for s in STAGES],
        "status_opts": [(s, f"tk_st_{s}") for s in STATUSES],
        "total_tasks": len(everything),
        "task_names": names,
        "illustrative": svc.cfg.illustrative,
        "base_qs": query_string(base),
        "list_qs": query_string({**base, "sort": col, "dir": direction}),
    }


def drawer_view(ctx: Any, task_id: str, tab: str, query: Mapping[str, str]) -> dict[str, Any]:
    if tab not in DRAWER_TABS:
        raise ListingError("unknown drawer tab")
    try:
        check_id(task_id)
        task = ctx.tasks.get(task_id)
    except NotFoundError:
        raise ListingError(f"task {task_id[:64]} does not exist") from None
    p = parse_params(query)
    ids = [r["task_id"] for r in ctx.tasks.list_tasks() if _fits(r, p)]
    i = ids.index(task_id) if task_id in ids else -1
    return {
        "t": task,
        "tab": tab,
        "tabs": DRAWER_TABS,
        "prev_id": ids[i - 1] if i > 0 else None,
        "next_id": ids[i + 1] if 0 <= i < len(ids) - 1 else None,
        "qs": query_string({k: v for k, v in p.items() if k != "page" and v}),
        "json_text": json.dumps(task, sort_keys=True, indent=2, default=str),
    }


def agent_tab(ctx: Any, agent_id: str) -> dict[str, Any]:
    """Data of the Tasks tab on the Agent page."""
    if not ctx.settings.controls_enabled:
        return {"tk_off": True}
    return {"tk_off": False, "tk": ctx.tasks.agent_summary(agent_id), "stages": STAGES}
