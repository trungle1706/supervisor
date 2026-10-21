"""Controls page and Agent tab (WP30, read-only): filter, sort, page and row drawer over the
control catalogue.

Read model over ``ControlService`` (``ctx.controls``). Nothing is written here: a control is
created and changed through ``/v1/controls`` (RBAC ``controls.edit``, two audit rows) or imported
with ``python -m supervisor.controls import``. Filters are checked against allow-lists or an id
pattern; a bad value is a ``ListingError`` (HTTP 400)."""

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
from supervisor.controls.model import (
    CONTROL_TYPES,
    EVIDENCE_STATUSES,
    IMPLEMENTERS,
    MAP_KINDS,
    STATUSES,
    check_id,
)
from supervisor.core.errors import NotFoundError

COLUMNS = ("control_id", "title", "owner", "review_date")
DRAWER_TABS = ("details", "map", "status")
PAGE_SIZE = 25
FILTERS = ("agent", "type", "implemented_by", "status", "owner", "q")


def parse_params(query: Mapping[str, str]) -> dict[str, str]:
    p = {
        "agent": ux3.ident(query, "agent"),
        "type": ux3.choice(query, "type", CONTROL_TYPES),
        "implemented_by": ux3.choice(query, "implemented_by", IMPLEMENTERS),
        "status": ux3.choice(query, "status", STATUSES),
        "owner": ux3.token(query, "owner"),
        "q": ux3.token(query, "q"),
        "sort": query.get("sort") or "",
        "dir": query.get("dir") or "",
        "page": query.get("page") or "",
    }
    parse_int(p["page"], "page", 1)
    return p


def _fits(r: Mapping[str, Any], p: Mapping[str, str]) -> bool:
    if p["agent"] and r["agents"] != ["*"] and p["agent"].lower() not in r["agents"]:
        return False
    if p["type"] and r["control_type"] != p["type"]:
        return False
    if p["implemented_by"] and r["implemented_by"] != p["implemented_by"]:
        return False
    if p["status"] and r["status"] != p["status"]:
        return False
    if p["owner"] and r["owner"] != p["owner"]:
        return False
    if p["q"]:
        hay = f"{r['control_id']} {r['title']} {r.get('objective') or ''}".lower()
        if p["q"].lower() not in hay:
            return False
    return True


def _ordered(rows: list[dict[str, Any]], p: Mapping[str, str]) -> tuple[list[Any], str, str]:
    col, direction = parse_sort(p["sort"], p["dir"], COLUMNS, "control_id", "asc")
    return sort_rows(rows, col, direction), col, direction


def list_view(ctx: Any, query: Mapping[str, str]) -> dict[str, Any]:
    p = parse_params(query)
    if p["agent"]:
        check_id(p["agent"], "agent")
    svc = ctx.controls
    everything = svc.list_controls()
    summary = svc.status_summary()
    for r in everything:
        r["st"] = summary.get(r["control_id"], dict.fromkeys(EVIDENCE_STATUSES, 0))
    shown_all = [r for r in everything if _fits(r, p)]
    shown, col, direction = _ordered(shown_all, p)
    page = paginate(shown, parse_int(p["page"], "page", 1), PAGE_SIZE)
    base = {k: p[k] for k in FILTERS}
    active = [r for r in everything if r["status"] == "active"]
    tiles = [
        {
            "label": "ct_tile_active",
            "n": len(active),
            "on": p["status"] == "active" and not p["implemented_by"],
            "qs": query_string(base, status="active", implemented_by=""),
        },
        {
            "label": "ct_tile_product",
            "n": sum(1 for r in active if r["implemented_by"] == "product"),
            "on": p["implemented_by"] == "product",
            "qs": query_string(base, status="active", implemented_by="product"),
        },
        {
            "label": "ct_tile_bank",
            "n": sum(1 for r in active if r["implemented_by"] == "bank"),
            "on": p["implemented_by"] == "bank",
            "qs": query_string(base, status="active", implemented_by="bank"),
        },
    ]
    agents = sorted({a for r in everything for a in r["agents"] if a != "*"})
    return {
        "page": page,
        "params": p,
        "sort_col": col,
        "sort_dir": direction,
        "tiles": tiles,
        "agent_opts": [(a, a) for a in agents],
        "type_opts": [(c, f"ct_type_{c}") for c in CONTROL_TYPES],
        "by_opts": [(c, f"ct_by_{c}") for c in IMPLEMENTERS],
        "owner_opts": [(o, o) for o in sorted({r["owner"] for r in everything})],
        "status_opts": [(s, f"rk_st_{s}") for s in STATUSES],
        "total_controls": len(everything),
        "failing_n": sum(1 for r in active if r["st"]["failing"]),
        "overdue_n": svc.counts()["review_overdue"],
        "uncovered": svc.uncovered_risks(),
        "base_qs": query_string(base),
        "list_qs": query_string({**base, "sort": col, "dir": direction}),
    }


def drawer_view(ctx: Any, control_id: str, tab: str, query: Mapping[str, str]) -> dict[str, Any]:
    if tab not in DRAWER_TABS:
        raise ListingError("unknown drawer tab")
    try:
        check_id(control_id)
        control = ctx.controls.get(control_id)
    except NotFoundError:
        raise ListingError(f"control {control_id[:64]} does not exist") from None
    p = parse_params(query)
    rows, _, _ = _ordered([r for r in ctx.controls.list_controls() if _fits(r, p)], p)
    ids = [r["control_id"] for r in rows]
    i = ids.index(control_id) if control_id in ids else -1
    return {
        "c": control,
        "tab": tab,
        "tabs": DRAWER_TABS,
        "prev_id": ids[i - 1] if i > 0 else None,
        "next_id": ids[i + 1] if 0 <= i < len(ids) - 1 else None,
        "qs": query_string({k: v for k, v in p.items() if k != "page" and v}),
        "map_groups": [(k, control["maps"][k]) for k in MAP_KINDS if k in control["maps"]],
        "json_text": json.dumps(control, sort_keys=True, indent=2, default=str),
    }


def agent_tab(ctx: Any, agent_id: str) -> dict[str, Any]:
    """Data of the Controls tab on the Agent page."""
    if not ctx.settings.controls_enabled:
        return {"ct_off": True}
    comp = ctx.controls.agent_compliance(agent_id)
    return {
        "ct_off": False,
        "ct": comp,
        "ct_obligations": ctx.controls.obligation_coverage(agent_id),
    }
