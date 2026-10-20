"""Agent detail page (WP-UX2): one page per agent with eight tabs.

Read models only; the lifecycle controls (pause, resume, quarantine, release) stay in the
route ``POST /console/agents/{id}/{action}`` with its RBAC and audit rows. A tab whose feature
flag is off is not shown and its URL answers HTTP 400 with the flag name (the Tools,
Inventory, Assurance and Compliance pattern). A tab the role may not read answers 403.
Every tab body is a partial (``_agent_tab_<name>.html``); ``?tab=`` renders the same body
inside the full page, so the page works without JS."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from supervisor.cases.service import PermissionDenied
from supervisor.console import (
    assurance_views,
    compliance_view,
    inventory_views,
    readmodels,
    tools_views,
)
from supervisor.core import rbac
from supervisor.core.errors import SupervisorError
from supervisor.inventory.api import InventoryInputError

TABS = ("overview", "policy", "tools", "inventory", "traces", "cases", "assurance", "compliance")
TRACE_LIMIT = 20  # traces shown on the Traces tab
CASE_LIMIT = 50
ASSURANCE_LIMIT = 50
# tab -> (Settings flag, permission, flag name for the message, how to use it without the console)
GATED: dict[str, tuple[str, str, str, str]] = {
    "tools": (
        "console_tools_enabled",
        "tools.view",
        "CONSOLE_TOOLS_ENABLED",
        "python -m supervisor.analytics.tools report",
    ),
    "inventory": (
        "inventory_enabled",
        "inventory.view",
        "INVENTORY_ENABLED",
        "python -m supervisor.jobs.inventory",
    ),
    "assurance": (
        "console_assurance_enabled",
        "console.view",
        "CONSOLE_ASSURANCE_ENABLED",
        "python -m supervisor.assurance run <pack> --target <target> --out <folder>",
    ),
    "compliance": (
        "console_compliance_enabled",
        "compliance.view",
        "CONSOLE_COMPLIANCE_ENABLED",
        "python -m supervisor.advisory.compliance --profile <file> --out <folder>",
    ),
}


class AgentDetailError(SupervisorError):
    """Unknown agent, unknown tab or a tab that is switched off (HTTP 400)."""


def can(me: Any, permission: str) -> bool:
    """True when ``me`` may use ``permission``: a person by role, any other principal only for
    the read-only views in ``rbac.NON_USER_OK`` (the same rule as ``needs()``)."""
    if getattr(me, "kind", "user") == "user":
        return rbac.allowed(me.roles, permission)
    return permission in rbac.NON_USER_OK


def visible_tabs(ctx: Any, me: Any) -> list[str]:
    """Tabs whose flag is on and that ``me`` may read, in page order."""
    out = []
    for tab in TABS:
        gate = GATED.get(tab)
        if gate is None:
            out.append(tab)
        elif getattr(ctx.settings, gate[0], False) and can(me, gate[1]):
            out.append(tab)
    return out


def check_tab(ctx: Any, me: Any, tab: str) -> str:
    """The tab name, or AgentDetailError (unknown / off) or PermissionDenied (role)."""
    if tab not in TABS:
        raise AgentDetailError("unknown agent tab")
    gate = GATED.get(tab)
    if gate is None:
        return tab
    flag, perm, name, cli = gate
    if not getattr(ctx.settings, flag, False):
        raise AgentDetailError(
            f"The {tab.capitalize()} tab is off ({name}=1 turns it on); use {cli}"
        )
    if not can(me, perm):
        raise PermissionDenied(f"your role may not open the {tab} tab")
    return tab


def card_of(ctx: Any, me: Any, agent_id: str) -> dict[str, Any]:
    """The agent card of ``agent_id`` (``readmodels.agent_cards``); AgentDetailError if the
    agent is not registered. Only this agent's card is built (a card costs several queries)."""
    for c in readmodels.agent_cards(ctx, me, only=agent_id):
        if c["agent_id"] == agent_id:
            return c
    raise AgentDetailError(f"agent {agent_id} is not registered")


def _ts(value: Any) -> dt.datetime | None:
    return value if isinstance(value, dt.datetime) else None


def gate_24h(ctx: Any, agent_id: str, now: dt.datetime) -> dict[str, Any]:
    """Gate decisions of the last 24 hours for one agent: checked, blocked, paused, median ms."""
    since = now - dt.timedelta(hours=24)
    events = ctx.tables.query(
        "agent_event",
        {"agent_id": agent_id, "event_type": "gate_decision"},
        order_by=("-ts",),
        limit=readmodels.SCAN_CAP,
    )
    recent = [e for e in events if (_ts(e["ts"]) or since) >= since]
    ids = {e["event_id"] for e in recent}
    stops: dict[str, str] = {}
    for v in ctx.tables.query("verdict", {"agent_id": agent_id}, order_by=("-ts",), limit=2000):
        if v["advisory"] or v["action"] not in ("block", "pause") or v.get("event_id") not in ids:
            continue
        if stops.get(v["event_id"]) != "pause":
            stops[v["event_id"]] = v["action"]
    lat = [int(e["latency_ms"]) for e in recent if e.get("latency_ms") is not None]
    return {
        "checked": len(recent),
        "blocked": sum(1 for a in stops.values() if a == "block"),
        "paused": sum(1 for a in stops.values() if a == "pause"),
        "median_ms": readmodels.median(lat),
    }


def _overview(ctx: Any, me: Any, card: Mapping[str, Any], q: Mapping[str, str]) -> dict[str, Any]:
    now = ctx.clock.now()
    lane = f"agent:{card['agent_id']}"
    lanes = ctx.runtime.chain.heads()
    head = lanes.get(lane)
    raw = ctx.cases.list_cases(statuses=list(readmodels.OPEN_STATUSES), agent_id=card["agent_id"])
    return {
        "agents": [card],  # _agents_table.html renders the card and its one action
        "gate24": gate_24h(ctx, card["agent_id"], now),
        "lane": {
            "name": lane,
            "entries": (head.seq + 1) if head else 0,
            "verify": ctx.last_verify.get(lane),
        },
        "open_cases": readmodels.case_rows(ctx, raw[:5], now),
    }


def rules_in_scope(ctx: Any, agent_id: str) -> list[dict[str, Any]]:
    out = []
    for r in readmodels.rules_index(ctx).values():
        scope = r["expression"].get("agent_scope")
        if scope == "*" or agent_id in (scope or []):
            out.append(
                {
                    **r,
                    "scope_all": scope == "*",
                    "approvals": list(r["expression"].get("approvals") or []),
                }
            )
    return sorted(out, key=lambda r: r["rule_id"])


def _policy(ctx: Any, me: Any, card: Mapping[str, Any], q: Mapping[str, str]) -> dict[str, Any]:
    rules_all = readmodels.rules_index(ctx)
    classes = readmodels.tool_classes(ctx)
    allow = readmodels.allowed_tools(rules_all, card["agent_id"])
    try:
        cur = ctx.gateway.states.policy.current()
        policy = {"hash": cur.policy_hash, "version": cur.doc.policy_version}
    except Exception:  # noqa: BLE001 - no policy loaded: the tab still renders
        policy = {"hash": "", "version": None}
    return {
        "rules": rules_in_scope(ctx, card["agent_id"]),
        "policy": policy,
        "allow": [{"tool": t, "cls": classes.get(t)} for t in allow],
        "shadow": card["state"] == "SHADOW",
    }


def _tools(ctx: Any, me: Any, card: Mapping[str, Any], q: Mapping[str, str]) -> dict[str, Any]:
    data = tools_views.page(
        ctx,
        agent_id=card["agent_id"],
        days=q.get("days"),
        sort=q.get("sort", "default"),
        desc=q.get("dir") == "desc",
    )
    data["can_download"] = can(me, "tools.download")
    return data


def _inventory(ctx: Any, me: Any, card: Mapping[str, Any], q: Mapping[str, str]) -> dict[str, Any]:
    try:
        data = inventory_views.page(ctx, card["agent_id"])
    except InventoryInputError:
        return {"inv_missing": True}
    return {"inv_missing": False, "tree": data["tree"], "node_rows": data["node_rows"]}


def _case_by_event(ctx: Any, agent_id: str) -> dict[str, str]:
    """gate event id -> case id, from the case links of this agent's cases."""
    out: dict[str, str] = {}
    for c in ctx.cases.list_cases(agent_id=agent_id)[:CASE_LIMIT]:
        for link in ctx.cases.links(c["case_id"]):
            if link["source_kind"] == "gate":
                out.setdefault(link["source_ref"], c["case_id"])
    return out


def trace_rows(ctx: Any, agent_id: str, limit: int = TRACE_LIMIT) -> list[dict[str, Any]]:
    """Newest traces of one agent: events, gate decisions, stops and the case (if any)."""
    events = ctx.tables.query("agent_event", {"agent_id": agent_id}, order_by=("-ts",), limit=2000)
    order: list[str] = []
    groups: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        tid = e.get("trace_id")
        if not tid:
            continue
        if tid not in groups:
            if len(order) >= limit:
                continue
            order.append(tid)
            groups[tid] = []
        groups[tid].append(e)
    stops: dict[str, str] = {}
    for v in ctx.tables.query("verdict", {"agent_id": agent_id}, order_by=("-ts",), limit=2000):
        if not v["advisory"] and v["action"] in ("block", "pause") and v.get("trace_id") in groups:
            if stops.get(v["trace_id"]) != "pause":
                stops[v["trace_id"]] = v["action"]
    by_event = _case_by_event(ctx, agent_id)
    rows = []
    for tid in order:
        evs = groups[tid]
        gate = [e for e in evs if e["event_type"] == "gate_decision"]
        case_id = next((by_event[e["event_id"]] for e in gate if e["event_id"] in by_event), None)
        rows.append(
            {
                "trace_id": tid,
                "ts": max(e["ts"] for e in evs),
                "events": len(evs),
                "gate": len(gate),
                "stop": stops.get(tid),
                "tools": sorted({e["tool_name"] for e in evs if e.get("tool_name")})[:4],
                "case_id": case_id,
            }
        )
    return rows


def traces_page_exists() -> bool:
    """True when WP-UX3 has registered a Traces viewer route (``/console/traces/{...}``)."""
    from supervisor.console.routes import router

    return any(str(getattr(r, "path", "")).startswith("/console/traces/") for r in router.routes)


def _traces(ctx: Any, me: Any, card: Mapping[str, Any], q: Mapping[str, str]) -> dict[str, Any]:
    # link to the viewer only when it is registered AND switched on (flag off = HTTP 400 there)
    viewer = traces_page_exists() and bool(getattr(ctx.settings, "console_traces_enabled", False))
    return {"traces": trace_rows(ctx, card["agent_id"]), "traces_page": viewer}


def _cases(ctx: Any, me: Any, card: Mapping[str, Any], q: Mapping[str, str]) -> dict[str, Any]:
    raw = ctx.cases.list_cases(agent_id=card["agent_id"])
    return {
        "items": readmodels.case_rows(ctx, raw[:CASE_LIMIT], ctx.clock.now()),
        "cases_total": len(raw),
        "cases_cap": CASE_LIMIT,
    }


def _assurance(ctx: Any, me: Any, card: Mapping[str, Any], q: Mapping[str, str]) -> dict[str, Any]:
    return {
        "results": assurance_views.agent_results(
            ctx.tables, card["agent_id"], limit=ASSURANCE_LIMIT
        )
    }


def _compliance(ctx: Any, me: Any, card: Mapping[str, Any], q: Mapping[str, str]) -> dict[str, Any]:
    try:
        m = compliance_view.matrix_for(ctx.settings, card["agent_id"])
    except compliance_view.ComplianceInputError:
        return {"cmp": None}
    return {
        "cmp": compliance_view.card(card["agent_id"], m),
        "cmp_statuses": compliance_view.STATUSES,
    }


_BUILDERS = {
    "overview": _overview,
    "policy": _policy,
    "tools": _tools,
    "inventory": _inventory,
    "traces": _traces,
    "cases": _cases,
    "assurance": _assurance,
    "compliance": _compliance,
}


def tab_data(
    ctx: Any, me: Any, card: Mapping[str, Any], tab: str, query: Mapping[str, str]
) -> dict[str, Any]:
    """Template variables of one tab body (after ``check_tab``)."""
    return _BUILDERS[tab](ctx, me, card, query)


def counts(card: Mapping[str, Any]) -> dict[str, int]:
    """Numbers on the tab labels (only the ones the card already knows)."""
    return {"policy": card.get("rules_n", 0), "cases": card.get("open_cases", 0)}
