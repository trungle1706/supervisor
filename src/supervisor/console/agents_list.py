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


SYSTEM_FILTERS = ("linked", "unlinked")  # WP-UX4b: the System filter of Catalogues > Agents


def parse_params(query: Mapping[str, str], with_system: bool = False) -> dict[str, str]:
    """The list parameters in canonical form (empty string = not set). Raises ListingError.
    ``with_system`` (WP-UX4b, CONSOLE_NAV_V3 and GOVERNANCE_ENABLED) adds the ``system`` filter:
    ``linked`` or ``unlinked``; without it the parameter is ignored, as before."""
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
    out = {
        "q": q,
        "state": state,
        "risk": risk,
        "sort": query.get("sort") or "",
        "dir": query.get("dir") or "",
        "page": query.get("page") or "",
    }
    if with_system:
        system = query.get("system") or ""
        if system and system not in SYSTEM_FILTERS:
            raise ListingError("system must be linked or unlinked")
        out["system"] = system
    return out


def _matches(a: Mapping[str, Any], p: Mapping[str, str]) -> bool:
    if p["state"] and a["state"] != p["state"]:
        return False
    if p["risk"] and a.get("risk_tier") != p["risk"]:
        return False
    if p.get("system"):  # WP-UX4b: cards carry "systems" (a list) only when the filter is on
        if bool(a.get("systems")) != (p["system"] == "linked"):
            return False
    if p["q"]:
        hay = f"{a['agent_id']} {a.get('name') or ''} {a.get('owner_team') or ''}".lower()
        if p["q"].lower() not in hay:
            return False
    return True


def _qs(p: Mapping[str, str], **override: str) -> str:
    """Filter query string (q, state, risk) with overrides; a tile click drops sort and page."""
    return query_string({k: p[k] for k in ("q", "state", "risk", "system") if k in p}, **override)


def ordered(cards: list[dict[str, Any]], p: Mapping[str, str]) -> tuple[list[Any], str, str]:
    col, direction = parse_sort(p["sort"], p["dir"], COLUMNS, "state", "asc")
    rows = [a for a in cards if _matches(a, p)]
    rows = sort_rows(sorted(rows, key=lambda a: a["agent_id"]), col, direction, _KEYS)
    return rows, col, direction


def list_view(
    cards: list[dict[str, Any]], query: Mapping[str, str], with_system: bool = False
) -> dict[str, Any]:
    """Data for ``agents.html`` / ``_agents_list.html``."""
    p = parse_params(query, with_system)
    rows, col, direction = ordered(cards, p)
    page = paginate(rows, parse_int(p["page"], "page", 1), PAGE_SIZE)
    counts = {s: sum(1 for a in cards if a["state"] == s) for s in STATES}
    base = {k: v for k, v in p.items() if k in ("q", "state", "risk", "system")}
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


def order_rows(ctx: Any, me: Any, p: Mapping[str, str]) -> list[dict[str, Any]]:
    """The rows that order the drawer's previous / next links, without a full card per agent
    (a card costs several queries): only the fields the filters and sort keys read. A sort
    by coverage needs the coverage of every agent, so it takes the full cards."""
    col, _ = parse_sort(p["sort"], p["dir"], COLUMNS, "state", "asc")
    if col == "coverage":
        return readmodels.agent_cards(ctx, me)
    open_by: dict[str, int] = {}
    for c in readmodels.open_cases(ctx):
        open_by[c["agent_id"]] = open_by.get(c["agent_id"], 0) + 1
    states = ctx.gateway.states
    return [
        {
            **a,
            "state": states.get_state(a["agent_id"]) or a.get("gate_state"),
            "open_cases": open_by.get(a["agent_id"], 0),
        }
        for a in ctx.state.query("agent")
    ]


def drawer_view(
    ctx: Any,
    me: Any,
    agent_id: str,
    tab: str,
    query: Mapping[str, str],
    cards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Data for ``_agent_drawer.html``. ``cards`` (the list page has them already) avoids a
    second build; without it only the card of ``agent_id`` is built."""
    if tab not in DRAWER_TABS:
        raise ListingError("unknown drawer tab")
    p = parse_params(query)
    if cards is None:
        found = readmodels.agent_cards(ctx, me, only=agent_id)
        order = order_rows(ctx, me, p)
    else:
        found = [a for a in cards if a["agent_id"] == agent_id]
        order = cards
    if not found:
        raise ListingError(f"agent {agent_id} is not registered")
    card = found[0]
    rows, _, _ = ordered(order, p)
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
