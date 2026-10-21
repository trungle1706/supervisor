"""Risks page (WP29, read-only): filter, sort, page and row drawer over the risk register.

Read model over ``RiskService`` (``ctx.risks``). Nothing is written here: a risk is created and
changed through ``/v1/risks`` (RBAC ``risks.edit``, two audit rows) or imported with
``python -m supervisor.risk import``. Filters are checked against allow-lists or an id pattern;
a bad value is a ``ListingError`` (HTTP 400). Bands are ILLUSTRATIVE until the bank sets them
and the page says so."""

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
from supervisor.risk.model import BANDS, CATEGORIES, LINK_KINDS, STATUSES, check_id

COLUMNS = ("risk_id", "title", "residual_score", "inherent_score", "review_date", "owner")
DRAWER_TABS = ("details", "links", "evidence")
PAGE_SIZE = 25
FILTERS = ("agent", "category", "band", "owner", "status", "q")
_KEYS = {
    "review_date": lambda r: r.get("review_date") or None,
}


def parse_params(query: Mapping[str, str]) -> dict[str, str]:
    p = {
        "agent": ux3.ident(query, "agent"),
        "category": ux3.choice(query, "category", CATEGORIES),
        "band": ux3.choice(query, "band", BANDS),
        "owner": ux3.token(query, "owner"),
        "status": ux3.choice(query, "status", STATUSES),
        "q": ux3.token(query, "q"),
        "sort": query.get("sort") or "",
        "dir": query.get("dir") or "",
        "page": query.get("page") or "",
    }
    parse_int(p["page"], "page", 1)
    return p


def _agent_ok(agent: str) -> None:
    if agent:
        check_id(agent, "agent")


def _ordered(rows: list[dict[str, Any]], p: Mapping[str, str]) -> tuple[list[Any], str, str]:
    col, direction = parse_sort(p["sort"], p["dir"], COLUMNS, "residual_score", "desc")
    # the service already orders by residual score; a stable sort by the chosen column follows
    return sort_rows(rows, col, direction, _KEYS), col, direction


def list_view(ctx: Any, query: Mapping[str, str]) -> dict[str, Any]:
    p = parse_params(query)
    _agent_ok(p["agent"])
    svc = ctx.risks
    everything = svc.list_risks()
    shown_all = [r for r in everything if _fits(r, p)]
    shown, col, direction = _ordered(shown_all, p)
    page = paginate(shown, parse_int(p["page"], "page", 1), PAGE_SIZE)
    base = {k: p[k] for k in FILTERS}
    active = [r for r in everything if r["status"] == "active"]
    tiles = [
        {
            "label": "rk_tile_active",
            "n": len(active),
            "on": p["status"] == "active" and not p["band"],
            "qs": query_string(base, status="active", band=""),
        },
        {
            "label": "rk_tile_critical",
            "n": sum(1 for r in active if r["residual_band"] == "critical"),
            "on": p["band"] == "critical",
            "qs": query_string(base, status="active", band="critical"),
        },
        {
            "label": "rk_tile_high",
            "n": sum(1 for r in active if r["residual_band"] == "high"),
            "on": p["band"] == "high",
            "qs": query_string(base, status="active", band="high"),
        },
    ]
    return {
        "page": page,
        "params": p,
        "sort_col": col,
        "sort_dir": direction,
        "tiles": tiles,
        "agent_opts": [(a, a) for a in sorted({a for r in everything for a in r["agents"]})],
        "category_opts": [(c, f"rk_cat_{c}") for c in CATEGORIES],
        "band_opts": [(b, b) for b in reversed(BANDS)],
        "owner_opts": [(o, o) for o in sorted({r["owner"] for r in everything})],
        "status_opts": [(s, f"rk_st_{s}") for s in STATUSES],
        "total_risks": len(everything),
        "overdue_n": sum(1 for r in active if r["review_overdue"]),
        "unproven_n": sum(1 for r in active if r["treatment"] == "mitigate" and not _proven(r)),
        "illustrative": svc.cfg.thresholds.illustrative,
        "thresholds": svc.cfg.thresholds,
        "base_qs": query_string(base),
        "list_qs": query_string({**base, "sort": col, "dir": direction}),
    }


def _proven(r: Mapping[str, Any]) -> bool:
    return r["evidence_state"] == "working"


def _fits(r: Mapping[str, Any], p: Mapping[str, str]) -> bool:
    if p["agent"] and p["agent"].lower() not in {a.lower() for a in r["agents"]}:
        return False
    if p["category"] and r["category"] != p["category"]:
        return False
    if p["band"] and r["residual_band"] != p["band"]:
        return False
    if p["owner"] and r["owner"] != p["owner"]:
        return False
    if p["status"] and r["status"] != p["status"]:
        return False
    if p["q"]:
        hay = f"{r['risk_id']} {r['title']} {r.get('description') or ''}".lower()
        if p["q"].lower() not in hay:
            return False
    return True


def drawer_view(ctx: Any, risk_id: str, tab: str, query: Mapping[str, str]) -> dict[str, Any]:
    if tab not in DRAWER_TABS:
        raise ListingError("unknown drawer tab")
    try:
        check_id(risk_id)
        risk = ctx.risks.get(risk_id)
    except NotFoundError:
        raise ListingError(f"risk {risk_id[:64]} does not exist") from None
    p = parse_params(query)
    rows, _, _ = _ordered([r for r in ctx.risks.list_risks() if _fits(r, p)], p)
    ids = [r["risk_id"] for r in rows]
    i = ids.index(risk_id) if risk_id in ids else -1
    groups = {k: [x["target"] for x in risk["links"] if x["kind"] == k] for k in LINK_KINDS}
    trend = list(reversed(risk["evidence"]))  # oldest first for reading left to right
    return {
        "r": risk,
        "tab": tab,
        "tabs": DRAWER_TABS,
        "prev_id": ids[i - 1] if i > 0 else None,
        "next_id": ids[i + 1] if 0 <= i < len(ids) - 1 else None,
        "qs": query_string({k: v for k, v in p.items() if k != "page" and v}),
        "link_groups": [(k, v) for k, v in groups.items() if v],
        "trend": trend,
        "illustrative": ctx.risks.cfg.thresholds.illustrative,
        "json_text": json.dumps(risk, sort_keys=True, indent=2, default=str),
    }


def agent_tab(ctx: Any, agent_id: str) -> dict[str, Any]:
    """Data of the Risks tab on the Agent page."""
    if not ctx.settings.risk_register_enabled:
        return {"rk_off": True}
    s = ctx.risks.agent_summary(agent_id)
    return {"rk_off": False, "rk": s}
