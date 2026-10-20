"""Agents list page (WP-UX1 proof of the list components): filter, sort, page and row drawer.

Pure functions over the agent cards from ``readmodels.agent_cards``. Filters are checked
against allow-lists (an unknown value is a ListingError, HTTP 400). The drawer has three
tabs: overview, policy, cases."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from supervisor.console import readmodels
from supervisor.console.listing import (
    ListingError,
    paginate,
    parse_int,
    parse_sort,
    query_string,
    sort_rows,
)

STATES = ("RUNNING", "SHADOW", "PAUSED", "QUARANTINED")
COLUMNS = ("agent_id", "state", "owner_team", "risk_tier", "coverage", "open_cases")
DRAWER_TABS = ("overview", "policy", "cases")
PAGE_SIZE = 10
_STATE_RANK = {"QUARANTINED": 0, "PAUSED": 1, "SHADOW": 2, "RUNNING": 3}
_TOKEN = re.compile(r"^[A-Za-z0-9_.:@ -]{0,64}$")
_KEYS = {
    "state": lambda a: _STATE_RANK.get(a["state"], 4),
    "coverage": lambda a: (a.get("coverage") or {}).get("bp"),
    "open_cases": lambda a: a.get("open_cases", 0),
}


def parse_params(query: Mapping[str, str]) -> dict[str, str]:
    """The list parameters in canonical form (empty string = not set). Raises ListingError."""
    q = (query.get("q") or "").strip()
    if not _TOKEN.match(q):
        raise ListingError("search text may hold letters, digits and . _ : @ - only (64 max)")
    state = query.get("state") or ""
    if state and state not in STATES:
        raise ListingError("unknown state filter")
    risk = query.get("risk") or ""
    if risk and not re.match(r"^[a-z_]{1,24}$", risk):
        raise ListingError("unknown risk filter")
    parse_int(query.get("page"), "page", 1)  # validates the text; paginate() checks the range
    return {
        "q": q,
        "state": state,
        "risk": risk,
        "sort": query.get("sort") or "",
        "dir": query.get("dir") or "",
        "page": query.get("page") or "",
    }


def _matches(a: Mapping[str, Any], p: Mapping[str, str]) -> bool:
    if p["state"] and a["state"] != p["state"]:
        return False
    if p["risk"] and a.get("risk_tier") != p["risk"]:
        return False
    if p["q"]:
        hay = f"{a['agent_id']} {a.get('name') or ''} {a.get('owner_team') or ''}".lower()
        if p["q"].lower() not in hay:
            return False
    return True


def _qs(p: Mapping[str, str], **override: str) -> str:
    """Filter query string (q, state, risk) with overrides; a tile click drops sort and page."""
    return query_string({k: p[k] for k in ("q", "state", "risk")}, **override)


def ordered(cards: list[dict[str, Any]], p: Mapping[str, str]) -> tuple[list[Any], str, str]:
    col, direction = parse_sort(p["sort"], p["dir"], COLUMNS, "state", "asc")
    rows = [a for a in cards if _matches(a, p)]
    rows = sort_rows(sorted(rows, key=lambda a: a["agent_id"]), col, direction, _KEYS)
    return rows, col, direction


def list_view(cards: list[dict[str, Any]], query: Mapping[str, str]) -> dict[str, Any]:
    """Data for ``agents.html`` / ``_agents_list.html``."""
    p = parse_params(query)
    rows, col, direction = ordered(cards, p)
    page = paginate(rows, parse_int(p["page"], "page", 1), PAGE_SIZE)
    counts = {s: sum(1 for a in cards if a["state"] == s) for s in STATES}
    base = {k: v for k, v in p.items() if k in ("q", "state", "risk")}
    tiles = [{"label": "all", "n": len(cards), "on": not p["state"], "qs": _qs(p, state="")}]
    tiles += [
        {"label": f"state_{s}", "n": counts[s], "on": p["state"] == s, "qs": _qs(p, state=s)}
        for s in STATES
    ]
    return {
        "tiles": tiles,
        "state_opts": [(s, f"state_{s}") for s in STATES],
        "risk_opts": [
            (r, r) for r in sorted({a.get("risk_tier") for a in cards if a.get("risk_tier")})
        ],
        "page": page,
        "params": p,
        "sort_col": col,
        "sort_dir": direction,
        "state_counts": counts,
        "base_qs": query_string(base),  # filters only
        "list_qs": query_string({**base, "sort": col, "dir": direction}),  # + sort, no page
    }


def drawer_view(
    ctx: Any, cards: list[dict[str, Any]], agent_id: str, tab: str, query: Mapping[str, str]
) -> dict[str, Any]:
    if tab not in DRAWER_TABS:
        raise ListingError("unknown drawer tab")
    card = next((a for a in cards if a["agent_id"] == agent_id), None)
    if card is None:
        raise ListingError(f"agent {agent_id} is not registered")
    p = parse_params(query)
    rows, _, _ = ordered(cards, p)
    ids = [a["agent_id"] for a in rows]
    i = ids.index(agent_id) if agent_id in ids else -1
    out: dict[str, Any] = {
        "a": card,
        "tab": tab,
        "tabs": DRAWER_TABS,
        "prev_id": ids[i - 1] if i > 0 else None,
        "next_id": ids[i + 1] if 0 <= i < len(ids) - 1 else None,
        "qs": query_string({k: v for k, v in p.items() if k != "page"}),
        "json_text": json.dumps(
            {
                "agent_id": card["agent_id"],
                "name": card.get("name"),
                "state": card["state"],
                "owner_team": card.get("owner_team"),
                "risk_tier": card.get("risk_tier"),
                "model_family": card.get("model_family"),
                "coverage_bp": (card.get("coverage") or {}).get("bp"),
                "open_cases": card.get("open_cases", 0),
            },
            sort_keys=True,
            indent=2,
        ),
    }
    if tab == "policy":
        out["rules"] = _rules_for(ctx, agent_id)
    elif tab == "cases":
        raw = ctx.cases.list_cases(statuses=list(readmodels.OPEN_STATUSES), agent_id=agent_id)
        out["cases"] = readmodels.case_rows(ctx, raw[:20], ctx.clock.now())
    return out


def _rules_for(ctx: Any, agent_id: str) -> list[dict[str, Any]]:
    rules = readmodels.rules_index(ctx)
    scoped = [
        r
        for r in rules.values()
        if r["expression"].get("agent_scope") == "*"
        or agent_id in (r["expression"].get("agent_scope") or [])
    ]
    return sorted(scoped, key=lambda r: r["rule_id"])
