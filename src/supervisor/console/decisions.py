"""Gate decisions page (WP-UX3): every allow, log, alert, block and pause the gate made.

A read model over ``agent_event`` (event_type ``gate_decision``), the tier-0 ``verdict`` rows
that share its ``event_id`` (the rule hits), ``case_link`` (the case a stop opened) and
``chain_entry`` (the evidence position). Only equality filters go to the store (agent, tool);
the rest is applied in Python over the newest ``CONSOLE_SCAN_CAP`` rows, so the page works the
same on SQLite and on Delta. Nothing is written. Arguments are never shown: the event holds a keyed
HMAC of the arguments and hashed key values only (R2)."""

from __future__ import annotations

import datetime as dt
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
from supervisor.console.readmodels import jloads, rules_index

ACTIONS = ("allow", "log", "alert", "block", "pause")
_RANK = {"pause": 0, "block": 1, "alert": 2, "log": 3, "allow": 4}
COLUMNS = ("ts", "agent_id", "tool", "action", "rule_id", "latency_us")
DRAWER_TABS = ("details", "rules", "evidence")
PAGE_SIZE = 25
FILTERS = ("agent", "action", "rule", "tool", "range", "trace")
_KEYS = {
    "action": lambda r: _RANK.get(r["action"], 5),
    "latency_us": lambda r: r.get("latency_us"),
}


def parse_params(query: Mapping[str, str]) -> dict[str, str]:
    p = {
        "agent": ux3.ident(query, "agent"),
        "action": ux3.choice(query, "action", ACTIONS),
        "rule": ux3.ident(query, "rule"),
        "tool": ux3.ident(query, "tool"),
        "range": ux3.choice(query, "range", ux3.RANGES),
        "trace": ux3.token(query, "trace"),
        "sort": query.get("sort") or "",
        "dir": query.get("dir") or "",
        "page": query.get("page") or "",
    }
    parse_int(p["page"], "page", 1)
    return p


def _action_of(event: Mapping[str, Any]) -> str:
    cls = event.get("classification")
    if cls in ACTIONS:
        return str(cls)
    return "allow" if event.get("status") == "allowed" else "block"


def _verdicts_by_event(ctx: Any, agent: str) -> dict[str, list[dict[str, Any]]]:
    """Tier-0 verdict rows by event id. One query per action so a burst of allow rows never
    crowds the stops out of the scan."""
    out: dict[str, list[dict[str, Any]]] = {}
    for action in ACTIONS:
        where: dict[str, Any] = {"tier": 0, "action": action}
        if agent:
            where["agent_id"] = agent
        for v in ctx.tables.query("verdict", where, order_by=("-ts",), limit=ux3.scan_cap(ctx)):
            if v.get("event_id"):
                out.setdefault(str(v["event_id"]), []).append(v)
    return out


def _hits(vs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rule hits (a verdict with a rule id, not advisory), decisive first."""
    hits = [v for v in vs if v.get("rule_id") and not v.get("advisory")]
    return sorted(hits, key=lambda v: (_RANK.get(v["action"], 5), str(v["rule_id"])))


def _row(
    e: Mapping[str, Any], vs: list[dict[str, Any]], cases: Mapping[str, str]
) -> dict[str, Any]:
    hits = _hits(vs)
    lat = e.get("latency_us")
    if lat is None and e.get("latency_ms") is not None:
        lat = int(e["latency_ms"]) * 1000
    return {
        "event_id": e["event_id"],
        "ts": e["ts"],
        "agent_id": e["agent_id"],
        "tool": e.get("tool_name") or "-",
        "action": _action_of(e),
        "rule_id": hits[0]["rule_id"] if hits else None,
        "rule_ids": [h["rule_id"] for h in hits],
        "latency_us": lat,
        "case_id": cases.get(str(e["event_id"])),
        "trace_id": e.get("trace_id"),
    }


def _case_links(ctx: Any) -> dict[str, str]:
    return {
        str(r["source_ref"]): str(r["case_id"])
        for r in ctx.tables.query("case_link", {"source_kind": "gate"})
    }


def rows_for(ctx: Any, p: Mapping[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """All decision rows that match the filters except the action (so the tiles can count
    them), plus the option lists for the filter bar."""
    where: dict[str, Any] = {"event_type": "gate_decision"}
    if p["agent"]:
        where["agent_id"] = p["agent"]
    events = ctx.tables.query("agent_event", where, order_by=("-ts",), limit=ux3.scan_cap(ctx))
    start = ux3.range_start(ctx.clock.now(), p["range"])
    if start is not None:
        events = [e for e in events if e["ts"] >= start]
    verdicts = _verdicts_by_event(ctx, p["agent"])
    cases = _case_links(ctx)
    rows = [_row(e, verdicts.get(str(e["event_id"]), []), cases) for e in events]
    opts = {
        "tools": sorted({r["tool"] for r in rows if r["tool"] != "-"}),
        "rules": sorted({rid for r in rows for rid in r["rule_ids"]} | set(rules_index(ctx))),
    }
    out = []
    for r in rows:
        if p["tool"] and r["tool"] != p["tool"]:
            continue
        if p["rule"] and p["rule"] not in r["rule_ids"]:
            continue
        if p["trace"] and p["trace"] not in str(r["trace_id"] or ""):
            continue
        out.append(r)
    return out, opts


def _qs(p: Mapping[str, str], **override: str) -> str:
    return query_string({k: p[k] for k in FILTERS}, **override)


def ordered(rows: list[dict[str, Any]], p: Mapping[str, str]) -> tuple[list[Any], str, str]:
    col, direction = parse_sort(p["sort"], p["dir"], COLUMNS, "ts", "desc")
    shown = [r for r in rows if not p["action"] or r["action"] == p["action"]]
    keys = {**_KEYS, "ts": lambda r: r["ts"], "agent_id": lambda r: r["agent_id"]}
    return sort_rows(shown, col, direction, keys), col, direction


def v2_on(ctx: Any) -> bool:
    """WP39: CONSOLE_DECISIONS_V2 (default off): verdict v2 list, filters and drawer."""
    return bool(getattr(ctx.settings, "console_decisions_v2", False))


def list_view(ctx: Any, query: Mapping[str, str]) -> dict[str, Any]:
    if v2_on(ctx):
        from supervisor.console import decisions_v2

        return decisions_v2.list_view(ctx, query)
    p = parse_params(query)
    rows, opts = rows_for(ctx, p)
    shown, col, direction = ordered(rows, p)
    page = paginate(shown, parse_int(p["page"], "page", 1), PAGE_SIZE)
    counts = {a: sum(1 for r in rows if r["action"] == a) for a in ACTIONS}
    tiles = [{"label": "all", "n": len(rows), "on": not p["action"], "qs": _qs(p, action="")}]
    tiles += [
        {"label": f"act_{a}", "n": counts[a], "on": p["action"] == a, "qs": _qs(p, action=a)}
        for a in ("allow", "block", "pause", "alert")
    ]
    agents = sorted(a["agent_id"] for a in ctx.state.query("agent"))
    base = {k: p[k] for k in FILTERS}
    return {
        "tiles": tiles,
        "page": page,
        "params": p,
        "sort_col": col,
        "sort_dir": direction,
        "agent_opts": [(a, a) for a in agents],
        "action_opts": [(a, f"act_{a}") for a in ACTIONS],
        "rule_opts": [(r, r) for r in opts["rules"]],
        "tool_opts": [(t, t) for t in opts["tools"]],
        "range_opts": [(k, f"range_{k}") for k in ux3.RANGES],
        "capped": len(rows) >= ux3.scan_cap(ctx),
        "base_qs": query_string(base),
        "list_qs": query_string({**base, "sort": col, "dir": direction}),
    }


def _chain(ctx: Any, event_id: str) -> dict[str, Any] | None:
    rows = ctx.tables.query("chain_entry", {"record_ref": event_id, "record_type": "gate_decision"})
    if not rows:
        return None
    r = rows[0]
    return {
        "lane": r["lane"],
        "seq": int(r["seq"]),
        "entry_hash": r["entry_hash"],
        "payload_hash": r["payload_hash"],
        "ts": r["ts"],
    }


def drawer_view(ctx: Any, event_id: str, tab: str, query: Mapping[str, str]) -> dict[str, Any]:
    if v2_on(ctx):
        from supervisor.console import decisions_v2

        return decisions_v2.drawer_view(
            ctx, event_id, tab if tab != "details" else "request", query
        )
    if tab not in DRAWER_TABS:
        raise ListingError("unknown drawer tab")
    events = ctx.tables.query("agent_event", {"event_id": event_id, "event_type": "gate_decision"})
    if not events:
        raise ListingError(f"gate decision {event_id} not found")
    e = events[0]
    vs = ctx.tables.query("verdict", {"event_id": event_id}, order_by=("ts",))
    cases = _case_links(ctx)
    row = _row(e, [v for v in vs if int(v["tier"]) == 0], cases)
    hits = _hits([v for v in vs if int(v["tier"]) == 0])
    rules = rules_index(ctx)
    rule_rows = [
        {
            "rule_id": h["rule_id"],
            "action": h["action"],
            "label": h.get("label"),
            "severity": (rules.get(h["rule_id"]) or {}).get("severity"),
            "text": (rules.get(h["rule_id"]) or {}).get("description")
            or (h.get("rationale_masked") or ""),
            "regulation_ref": (rules.get(h["rule_id"]) or {}).get("regulation_ref"),
        }
        for h in hits
    ]
    chain = _chain(ctx, event_id)
    # WP38 review: an observe-mode decision shows what it would have done (verdict label).
    observed = next(
        (
            f"{str(h['label'])[len('observe_would_') :]} {h['rule_id']}"
            for h in hits
            if str(h.get("label") or "").startswith("observe_would_")
        ),
        None,
    )
    keys = jloads(e.get("args_masked"), {})
    p = parse_params(query)
    rows, _ = rows_for(ctx, p)
    ids = [r["event_id"] for r in ordered(rows, p)[0]]
    i = ids.index(event_id) if event_id in ids else -1
    reason = next((h.get("rationale_masked") for h in hits), None) or (
        vs[0].get("rationale_masked") if vs else None
    )
    doc = {
        "event_id": event_id,
        "ts": e["ts"].isoformat() if isinstance(e["ts"], dt.datetime) else str(e["ts"]),
        "agent_id": e["agent_id"],
        "agent_version": e.get("agent_version"),
        "caller_agent_id": e.get("caller_agent_id"),
        "tool": e.get("tool_name"),
        "action": row["action"],
        "status": e.get("status"),
        "rule_id": row["rule_id"],
        "rule_hits": [{"rule_id": r["rule_id"], "action": r["action"]} for r in rule_rows],
        "reason": reason,
        "latency_us": row["latency_us"],
        "args_hash": e.get("args_hash"),
        "arg_keys": sorted(keys.get("keys", {})) if isinstance(keys, dict) else [],
        "amount_minor": e.get("amount_minor"),
        "currency": e.get("currency"),
        "trace_id": e.get("trace_id"),
        "span_id": e.get("span_id"),
        "capture_level": e.get("capture_level"),
        "case_id": row["case_id"],
        "chain": {k: chain[k] for k in ("lane", "seq", "entry_hash")} if chain else None,
    }
    if observed is not None:
        doc["observed_decision"] = observed
    return {
        "e": e,
        "row": row,
        "tab": tab,
        "tabs": DRAWER_TABS,
        "rules": rule_rows,
        "chain": chain,
        "reason": reason,
        "observed": observed,
        "arg_keys": doc["arg_keys"],
        "prev_id": ids[i - 1] if i > 0 else None,
        "next_id": ids[i + 1] if 0 <= i < len(ids) - 1 else None,
        "qs": query_string({k: v for k, v in p.items() if k != "page" and v}),
        "traces_on": bool(ctx.settings.console_traces_enabled),
        "json_text": json.dumps(doc, sort_keys=True, indent=2, default=str),
    }
