"""My agents (WP-N2): the inventory of the agents in scope, and the Register tab of the Agent page.

Read only. Three kinds of row:

* ``registered``: a row in table ``agent`` (``readmodels.agent_cards``);
* ``policy_only``: the gate knows the id from the policy ``agents:`` section but there is no row;
* ``candidate``: an unmanaged workspace item that may become an AI system (an app, an agent
  serving endpoint or a Genie space; needs ``INVENTORY_ENABLED``). It has no owner, so it shows
  in scope ``all`` only. No workspace URL or id is put in a row, only the node id and the name.

Filters are allow-lists (a bad value is a ``ListingError``, HTTP 400)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from supervisor.console import agent_guardians, overview_v3, readmodels
from supervisor.console.listing import (
    ListingError,
    paginate,
    parse_int,
    parse_sort,
    query_string,
    sort_rows,
)
from supervisor.governance import next_action

KINDS = ("registered", "policy_only", "candidate")
STATES = ("RUNNING", "SHADOW", "PAUSED", "QUARANTINED")
STATE_FILTERS = (*STATES, "stopped")  # stopped = PAUSED or QUARANTINED
COVERS = ("full", "below_floor", "none")
COLUMNS = ("agent", "kind", "state", "autonomy", "risk", "guardian", "last", "cases")
PAGE_SIZE = 10
SCOPES = overview_v3.SCOPES
_STATE_RANK = {"QUARANTINED": 0, "PAUSED": 1, "SHADOW": 2, "RUNNING": 3}
_RISK_RANK = {
    "unspecified": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
    "prohibited": 5,
}
_TOKEN = re.compile(r"^[A-Za-z0-9_.:@ -]{0,64}$")
_RISK = re.compile(r"^[a-z_]{1,24}$")
CANDIDATE_KINDS = ("system", "model_endpoint", "genie_space")


def _ts_key(r: Mapping[str, Any]) -> Any:
    ts = r.get("last")
    return ts.timestamp() if ts is not None else None


_KEYS = {
    "agent": lambda r: str(r["name"] or r["agent_id"]).lower(),
    "kind": lambda r: KINDS.index(r["kind"]),
    "state": lambda r: _STATE_RANK.get(r["state"]) if r["state"] else None,
    "autonomy": lambda r: r["autonomy"] or None,
    "risk": lambda r: _RISK_RANK.get(str(r["risk"]), 0) if r["risk"] else None,
    "guardian": lambda r: r["guard"]["on"] if r.get("guard") else None,
    "last": _ts_key,
    "cases": lambda r: int(r["open_cases"]),
}


def parse_params(query: Mapping[str, str]) -> dict[str, str]:
    q = (query.get("q") or "").strip()
    if not _TOKEN.match(q):
        raise ListingError("search text may hold letters, digits and . _ : @ - only (64 max)")
    kind = query.get("kind") or ""
    if kind and kind not in KINDS:
        raise ListingError("kind must be registered, policy_only or candidate")
    state = query.get("state") or ""
    if state and state not in STATE_FILTERS:
        raise ListingError("unknown state filter")
    risk = query.get("risk") or ""
    if risk and not _RISK.match(risk):
        raise ListingError("unknown risk filter")
    cover = query.get("cover") or ""
    if cover and cover not in COVERS:
        raise ListingError("cover must be full, below_floor or none")
    scope = query.get("scope") or ""
    if scope and scope not in SCOPES:
        raise overview_v3.ScopeError("scope must be my, team or all")
    parse_int(query.get("page"), "page", 1)
    return {
        "q": q,
        "kind": kind,
        "state": state,
        "risk": risk,
        "cover": cover,
        "scope": scope,
        "sort": query.get("sort") or "",
        "dir": query.get("dir") or "",
        "page": query.get("page") or "",
    }


# ---------------------------------------------------------------------------------- the rows


def _systems_by_agent(ctx: Any, me: Any) -> dict[str, list[dict[str, Any]]]:
    """Lower-case agent id -> the AI systems (visible to ``me``) it is linked to."""
    if not getattr(ctx.settings, "governance_enabled", False):
        return {}
    try:
        from supervisor.console import systems_overview

        rows = {
            r["system_id"]: r
            for r in ctx.systems.list_systems(ctx.systems.scope_for(me), {})
            if r["status"] != "archived"
        }
        comps = systems_overview.components_by_system(ctx)
    except Exception:  # noqa: BLE001 - the Systems columns are a convenience
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for sid, items in comps.items():
        if sid not in rows:
            continue
        for c in items:
            if c["ref_kind"] == "agent":
                out.setdefault(str(c["ref_id"]).lower(), []).append(rows[sid])
    return out


def _policy_cards(ctx: Any, registered: set[str]) -> list[dict[str, Any]]:
    """Cards for agents the gate knows from the policy file and that have no registry row."""
    try:
        doc = ctx.gateway.states.policy.current().doc
    except Exception:  # noqa: BLE001 - no policy loaded: no policy-only agents
        return []
    out = []
    for aid, m in sorted(doc.agents.items()):
        if aid in registered:
            continue
        out.append(policy_card(ctx, aid, m))
    return out


def policy_card(ctx: Any, agent_id: str, manifest: Any = None) -> dict[str, Any]:
    """A card-shaped dict for an agent only the policy file knows (``registered: false``)."""
    if manifest is None:
        manifest = ctx.gateway.states.policy.current().doc.agents.get(agent_id)
    try:
        state = ctx.gateway.states.get_state(agent_id) or manifest.initial_state
    except Exception:  # noqa: BLE001
        state = manifest.initial_state
    return {
        "agent_id": agent_id,
        "name": manifest.name,
        "owner_user": manifest.owner_user,
        "owner_team": manifest.owner_team,
        "risk_tier": manifest.risk_tier,
        "model_family": manifest.model_family,
        "host_type": manifest.host_type,
        "plug_point": manifest.plug_point,
        "initial_state": manifest.initial_state,
        "state": state,
        "kind": "policy_only",
        "cause": None,
        "pending": [],
        "d33": {"cls": None, "source": None},
        "judge": {"mock": False},
        "open_cases": 0,
        "tools_n": 0,
    }


def _candidates(ctx: Any) -> list[dict[str, Any]]:
    if not getattr(ctx.settings, "inventory_enabled", False):
        return []
    linked = {
        str(c["ref_id"])
        for c in ctx.state.query("system_component")
        if c["ref_kind"] in ("inventory_node", "node")
    }
    out = []
    for kind in CANDIDATE_KINDS:
        for n in ctx.state.query("inventory_node", {"kind": kind, "status": "unmanaged"}):
            attrs = readmodels.jloads(n.get("attrs"), {})
            wk = attrs.get("workspace_kind")
            if kind == "system" and wk != "app":
                continue
            if kind == "model_endpoint" and not attrs.get("agent_endpoint"):
                continue
            if n["node_id"] in linked:
                continue
            out.append(
                {
                    "agent_id": str(n["node_id"]),
                    "node_id": str(n["node_id"]),
                    "name": str(n.get("display_name") or n.get("name") or n["node_id"]),
                    "kind": "candidate",
                    "node_kind": kind,
                    "state": None,
                    "pending": [],
                    "owner_user": None,
                    "owner_team": None,
                    "risk_tier": n.get("own_risk"),
                    "d33": {"cls": None, "source": None},
                    "open_cases": 0,
                }
            )
    return sorted(out, key=lambda c: (c["node_kind"], c["name"]))


def _state_since(ctx: Any, card: Mapping[str, Any]) -> Any:
    cause = card.get("cause")
    if cause and cause.get("at") is not None:
        return cause["at"]
    aid = card["agent_id"]
    times = [r["created_at"] for r in ctx.state.query("gate_control", {"agent_id": aid})]
    if times:
        return max(times)
    return card.get("created_at")


def _last_activity(ctx: Any, agent_id: str) -> Any:
    rows = ctx.tables.query("agent_event", {"agent_id": agent_id}, order_by=("-ts",), limit=1)
    return rows[0]["ts"] if rows else None


def build_rows(ctx: Any, me: Any, scope_raw: str | None) -> tuple[str, list[dict[str, Any]]]:
    """(scope, rows) for the agents in scope with every column filled."""
    cards = readmodels.agent_cards(ctx, me)
    registered = {c["agent_id"] for c in cards}
    pool = [{**c, "kind": "registered"} for c in cards] + _policy_cards(ctx, registered)
    scope = overview_v3.parse_scope(scope_raw, pool, me)
    scoped = overview_v3.in_scope(pool, me, scope)
    by_sys = _systems_by_agent(ctx, me)
    env = agent_guardians.Env(ctx)
    all_systems = {s["system_id"]: s for items in by_sys.values() for s in items}
    pre = next_action.prefetch(ctx, me, list(all_systems.values()))
    rows = []
    items = list(scoped) + (_candidates(ctx) if scope == "all" else [])
    for c in items:
        aid = c["agent_id"]
        candidate = c["kind"] == "candidate"
        systems = [] if candidate else by_sys.get(aid.lower(), [])
        sysrow = systems[0] if systems else None
        guard = None if candidate else agent_guardians.summary(ctx, aid, env)
        card = {**c, "guard": guard}
        if c.get("state") == "SHADOW" and c["kind"] == "registered":
            card["state_since"] = _state_since(ctx, c)
        action = next_action.recommended_action(ctx, card, sysrow, pre)
        rows.append(
            {
                "agent_id": aid,
                "node_id": c.get("node_id"),
                "node_kind": c.get("node_kind"),
                "name": c.get("name") or aid,
                "kind": c["kind"],
                "state": c.get("state"),
                "pending": c.get("pending") or [],
                "cause": c.get("cause"),
                "systems": [{"system_id": s["system_id"], "name": s["name"]} for s in systems],
                "autonomy": (sysrow or {}).get("autonomy_level"),
                "risk": (sysrow or {}).get("effective_risk_level") or c.get("risk_tier"),
                "guard": guard,
                "last": None if candidate else _last_activity(ctx, aid),
                "open_cases": int(c.get("open_cases") or 0),
                "action": action,
            }
        )
    return scope, rows


def _matches(r: Mapping[str, Any], p: Mapping[str, str]) -> bool:
    if p["kind"] and r["kind"] != p["kind"]:
        return False
    if p["state"]:
        want = ("PAUSED", "QUARANTINED") if p["state"] == "stopped" else (p["state"],)
        if r["state"] not in want:
            return False
    if p["risk"] and r["risk"] != p["risk"]:
        return False
    if p["cover"] and (r["guard"] or {}).get("cover") != p["cover"]:
        return False
    if p["q"]:
        sys_names = " ".join(s["name"] for s in r["systems"])
        hay = f"{r['agent_id']} {r['name']} {sys_names}".lower()
        if p["q"].lower() not in hay:
            return False
    return True


def _qs(p: Mapping[str, str], **override: str) -> str:
    base = {k: p[k] for k in ("q", "kind", "state", "risk", "cover", "scope")}
    return query_string(base, **override)


def list_view(ctx: Any, me: Any, query: Mapping[str, str]) -> dict[str, Any]:
    """Data for ``my_agents.html`` / ``_my_agents_list.html``."""
    p = parse_params(query)
    scope, everyone = build_rows(ctx, me, p["scope"])
    p = {**p, "scope": scope}
    col, direction = parse_sort(p["sort"], p["dir"], COLUMNS, "state", "asc")
    rows = [r for r in everyone if _matches(r, p)]
    rows = sort_rows(sorted(rows, key=lambda r: str(r["agent_id"])), col, direction, _KEYS)
    page = paginate(rows, parse_int(p["page"], "page", 1), PAGE_SIZE)
    n_state = {s: sum(1 for r in everyone if r["state"] == s) for s in STATES}
    below = sum(1 for r in everyone if (r["guard"] or {}).get("cover") == "below_floor")
    clear = {"state": "", "cover": ""}
    tiles = [
        {"label": "mya_tile_total", "n": len(everyone), "on": not (p["state"] or p["cover"]),
         "qs": _qs(p, **clear)},
        {"label": "mya_tile_running", "n": n_state["RUNNING"], "on": p["state"] == "RUNNING",
         "qs": _qs(p, state="RUNNING", cover="")},
        {"label": "mya_tile_shadow", "n": n_state["SHADOW"], "on": p["state"] == "SHADOW",
         "qs": _qs(p, state="SHADOW", cover="")},
        {"label": "mya_tile_stopped", "n": n_state["PAUSED"] + n_state["QUARANTINED"],
         "on": p["state"] == "stopped", "qs": _qs(p, state="stopped", cover="")},
        {"label": "mya_tile_below", "n": below, "on": p["cover"] == "below_floor",
         "qs": _qs(p, state="", cover="below_floor")},
    ]  # fmt: skip
    base = {k: v for k, v in p.items() if k in ("q", "kind", "state", "risk", "cover", "scope")}
    return {
        "tiles": tiles,
        "params": p,
        "scope": scope,
        "scopes": SCOPES,
        "page": page,
        "sort_col": col,
        "sort_dir": direction,
        "kind_opts": [(k, f"mya_kind_{k}") for k in KINDS],
        "state_opts": [*((s, f"state_{s}") for s in STATES), ("stopped", "mya_tile_stopped")],
        "risk_opts": [(r, r) for r in sorted({r["risk"] for r in everyone if r["risk"]})],
        "cover_opts": [(c, f"mya_cover_{c}") for c in COVERS],
        "base_qs": query_string(base),
        "list_qs": query_string({**base, "sort": col, "dir": direction}),
        "total_all": len(everyone),
        "sys_links": bool(getattr(ctx.settings, "console_systems_enabled", False)),
    }


# ----------------------------------------------------------------------------- Register tab

INTAKE_FIELDS = (
    "system_type",
    "org_role",
    "user_segment",
    "personal_data",
    "money_movement",
    "credit_decision",
    "human_control",
)


def register_tab(ctx: Any, me: Any, card: Mapping[str, Any]) -> dict[str, Any]:
    """Data for ``_agent_tab_register.html``."""
    aid = str(card["agent_id"])
    policy_only = card.get("kind") == "policy_only"
    systems = [] if policy_only else _systems_by_agent(ctx, me).get(aid.lower(), [])
    sysrow = systems[0] if systems else None
    env = agent_guardians.Env(ctx)
    guard = agent_guardians.summary(ctx, aid, env)
    full = {**card, "guard": guard}
    if card.get("state") == "SHADOW" and not policy_only:
        full["state_since"] = _state_since(ctx, card)
    pre = next_action.prefetch(ctx, me, systems)
    action = next_action.recommended_action(ctx, full, sysrow, pre)
    since = None if policy_only else _state_since(ctx, card)
    return {
        "policy_only": policy_only,
        "reg": {
            "agent_id": aid,
            "name": card.get("name"),
            "owner_user": card.get("owner_user"),
            "owner_team": card.get("owner_team"),
            "risk_tier": card.get("risk_tier"),
            "host_type": card.get("host_type"),
            "plug_point": card.get("plug_point"),
            "model_family": card.get("model_family"),
            "state": card.get("state"),
            "since": since,
            "initial_state": card.get("initial_state"),
        },
        "sys": sysrow,
        "sys_more": [s for s in systems[1:]],
        "intake": [(f, sysrow.get(f)) for f in INTAKE_FIELDS] if sysrow else [],
        "description": _description(card, sysrow),
        "assess": _assessment(card, sysrow),
        "action": action,
        "register_href": f"/console/systems/new?agent={aid}",
    }


def _description(card: Mapping[str, Any], sysrow: Mapping[str, Any] | None) -> dict[str, Any]:
    purpose = str((sysrow or {}).get("purpose") or "").strip()
    if purpose:
        return {"text": purpose, "key": None, "args": {}}
    return {
        "text": None,
        "key": "mya_desc_built",
        "args": {
            "name": card.get("name") or card["agent_id"],
            "family": card.get("model_family") or "-",
            "host": card.get("host_type") or "-",
            "tools": int(card.get("tools_n") or 0),
            "tier": card.get("risk_tier") or "-",
        },
    }


def _assessment(card: Mapping[str, Any], sysrow: Mapping[str, Any] | None) -> dict[str, Any]:
    d33 = card.get("d33") or {}
    cls = (sysrow or {}).get("decision33_class") or d33.get("cls")
    source = "system" if (sysrow or {}).get("decision33_class") else d33.get("source")
    return {
        "d33": cls,
        "d33_source": source,
        "risk": (sysrow or {}).get("effective_risk_level") or card.get("risk_tier"),
        "risk_source": (sysrow or {}).get("effective_risk_source")
        or ("agent_tier" if card.get("risk_tier") else None),
        # the readiness score of the register wizard is not stored anywhere: omitted
    }
