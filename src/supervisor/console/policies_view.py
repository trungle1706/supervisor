"""Policies page (WP-UX3, read-only): the deployed policy versions and the rules in force.

Read model over the ``rule`` table (the deployed policy; ADR D11). The special ``_manifest`` row
holds the tool risk classes and the agent list; it is shown as the tool table, not as a rule.
Policies change through Git and a pull request, never from the console, so there is no write
here and no form."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import yaml

from supervisor.console import ux3
from supervisor.console.listing import (
    ListingError,
    paginate,
    parse_int,
    parse_sort,
    query_string,
    sort_rows,
)
from supervisor.console.readmodels import jloads
from supervisor.gateway.policy import MANIFEST_RULE_ID, SEVERITY_RANK

ACTIONS = ("log", "alert", "block", "pause")
SEVERITIES = tuple(SEVERITY_RANK)
RISKS = ("money", "credit", "pii_export", "read_only")
COLUMNS = ("rule_id", "action", "severity", "fail_mode", "risk_class", "version")
DRAWER_TABS = ("details", "yaml", "versions")
PAGE_SIZE = 25
_ACTION_RANK = {"pause": 0, "block": 1, "alert": 2, "log": 3}
_KEYS = {
    "action": lambda r: _ACTION_RANK.get(r["action"], 4),
    "severity": lambda r: -SEVERITY_RANK.get(r["severity"], -1),
}


def parse_params(query: Mapping[str, str]) -> dict[str, str]:
    p = {
        "agent": ux3.ident(query, "agent"),
        "action": ux3.choice(query, "action", ACTIONS),
        "severity": ux3.choice(query, "severity", SEVERITIES),
        "risk": ux3.choice(query, "risk", RISKS),
        "q": ux3.token(query, "q"),
        "sort": query.get("sort") or "",
        "dir": query.get("dir") or "",
        "page": query.get("page") or "",
    }
    parse_int(p["page"], "page", 1)
    return p


def _tool_classes(rows: list[dict[str, Any]]) -> dict[str, str]:
    for r in rows:
        if r["rule_id"] == MANIFEST_RULE_ID and r.get("effective_to") is None:
            expr = jloads(r.get("expression"), {})
            return dict(expr.get("tools") or {}) if isinstance(expr, dict) else {}
    return {}


def _risk_of(expr: Mapping[str, Any], classes: Mapping[str, str]) -> str | None:
    """Risk class of the tools a rule is about: the class when all its tools share one,
    ``mixed`` when they differ, None when the tool is not in the policy table."""
    when = expr.get("when") or {}
    tool = when.get("tool") if isinstance(when, dict) else None
    if tool is None:
        return None
    if isinstance(tool, dict):
        value = tool.get("value")
        names = value if isinstance(value, list) else [value]
    else:
        names = [tool]
    found = {classes[n] for n in names if isinstance(n, str) and n in classes}
    if not found:
        return None
    return found.pop() if len(found) == 1 else "mixed"


def _scope(row: Mapping[str, Any]) -> list[str]:
    raw = str(row.get("agent_scope") or "*")
    return ["*"] if raw == "*" else [a for a in raw.split(",") if a]


def _rule(row: Mapping[str, Any], classes: Mapping[str, str]) -> dict[str, Any]:
    expr = jloads(row.get("expression"), {})
    expr = expr if isinstance(expr, dict) else {}
    return {
        "rule_id": row["rule_id"],
        "version": int(row["version"]),
        "scope": _scope(row),
        "action": row["action"],
        "severity": row["severity"],
        "fail_mode": row.get("fail_mode"),
        "risk_class": expr.get("risk_class") or _risk_of(expr, classes),
        "description": expr.get("description") or "",
        "regulation_ref": row.get("regulation_ref"),
        "owner": row.get("owner"),
        "approvals": [a for a in (row.get("approved_by_1"), row.get("approved_by_2")) if a],
        "policy_hash": row.get("policy_hash"),
        "git_sha": row.get("git_sha"),
        "effective_from": row.get("effective_from"),
        "effective_to": row.get("effective_to"),
        "expression": expr,
    }


def _snapshot(ctx: Any) -> tuple[list[dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    rows = ctx.state.query("rule")
    classes = _tool_classes(rows)
    rules = [
        _rule(r, classes)
        for r in rows
        if r["rule_id"] != MANIFEST_RULE_ID and r.get("effective_to") is None
    ]
    versions: dict[str, dict[str, Any]] = {}
    for r in rows:
        v = versions.setdefault(
            str(r["policy_hash"]),
            {
                "policy_hash": r["policy_hash"],
                "rules_n": 0,
                "from": r["effective_from"],
                "git_sha": r.get("git_sha"),
                "active": False,
            },
        )
        if r["rule_id"] != MANIFEST_RULE_ID:
            v["rules_n"] += 1
        if r["effective_from"] < v["from"]:
            v["from"] = r["effective_from"]
        v["active"] = v["active"] or r.get("effective_to") is None
    ordered = sorted(versions.values(), key=lambda v: v["from"], reverse=True)
    return rules, classes, ordered


def _matches(r: Mapping[str, Any], p: Mapping[str, str]) -> bool:
    if p["agent"] and "*" not in r["scope"] and p["agent"] not in r["scope"]:
        return False
    if p["action"] and r["action"] != p["action"]:
        return False
    if p["severity"] and r["severity"] != p["severity"]:
        return False
    if p["risk"] and r["risk_class"] != p["risk"]:
        return False
    if p["q"]:
        hay = f"{r['rule_id']} {r['description']} {r['regulation_ref'] or ''}".lower()
        if p["q"].lower() not in hay:
            return False
    return True


def ordered(rules: list[dict[str, Any]], p: Mapping[str, str]) -> tuple[list[Any], str, str]:
    col, direction = parse_sort(p["sort"], p["dir"], COLUMNS, "rule_id", "asc")
    rows = sorted((r for r in rules if _matches(r, p)), key=lambda r: r["rule_id"])
    return sort_rows(rows, col, direction, _KEYS), col, direction


def list_view(ctx: Any, query: Mapping[str, str]) -> dict[str, Any]:
    p = parse_params(query)
    rules, classes, versions = _snapshot(ctx)
    shown, col, direction = ordered(rules, p)
    page = paginate(shown, parse_int(p["page"], "page", 1), PAGE_SIZE)
    agents = sorted(a["agent_id"] for a in ctx.state.query("agent"))
    base = {k: p[k] for k in ("agent", "action", "severity", "risk", "q")}
    return {
        "page": page,
        "params": p,
        "sort_col": col,
        "sort_dir": direction,
        "versions": versions,
        "tools": sorted(classes.items()),
        "agent_opts": [(a, a) for a in agents],
        "action_opts": [(a, f"act_{a}") for a in ACTIONS],
        "severity_opts": [(s, s) for s in SEVERITIES],
        "risk_opts": [(r, r) for r in RISKS],
        "total_rules": len(rules),
        "base_qs": query_string(base),
        "list_qs": query_string({**base, "sort": col, "dir": direction}),
    }


def _capabilities(risk: str | None) -> list[dict[str, str]]:
    """Gate-rule capabilities of the catalogue that apply to this risk class (the manifests
    the Onboarding Agent picks from). Only names and file paths are shown."""
    from supervisor.catalogue.loader import MANIFEST_DIR, load_catalogue

    try:
        cat = load_catalogue()
    except Exception:  # noqa: BLE001 - the catalogue link is a convenience, never a page failure
        return []
    out = []
    for m in cat.manifests.values():
        if m.kind == "gate_rule" and (risk in (None, "mixed") or risk in m.applies_to):
            out.append({"id": m.id, "name": m.name, "file": f"{MANIFEST_DIR.name}/{m.id}.yaml"})
    return sorted(out, key=lambda c: c["id"])


def drawer_view(ctx: Any, rule_id: str, tab: str, query: Mapping[str, str]) -> dict[str, Any]:
    if tab not in DRAWER_TABS:
        raise ListingError("unknown drawer tab")
    rules, classes, _ = _snapshot(ctx)
    rule = next((r for r in rules if r["rule_id"] == rule_id), None)
    if rule is None:
        raise ListingError(f"rule {rule_id} is not deployed")
    p = parse_params(query)
    ids = [r["rule_id"] for r in ordered(rules, p)[0]]
    i = ids.index(rule_id) if rule_id in ids else -1
    out: dict[str, Any] = {
        "r": rule,
        "tab": tab,
        "tabs": DRAWER_TABS,
        "prev_id": ids[i - 1] if i > 0 else None,
        "next_id": ids[i + 1] if 0 <= i < len(ids) - 1 else None,
        "qs": query_string({k: v for k, v in p.items() if k != "page" and v}),
        "decisions_on": bool(ctx.settings.console_decisions_enabled),
        "yaml_text": yaml.safe_dump(
            rule["expression"], sort_keys=False, allow_unicode=True, default_flow_style=False
        ),
        "json_text": json.dumps(
            {k: v for k, v in rule.items() if k != "expression"}
            | {"expression": rule["expression"]},
            sort_keys=True,
            indent=2,
            default=str,
        ),
        "capabilities": _capabilities(rule["risk_class"]),
    }
    if tab == "versions":
        rows = [_rule(r, classes) for r in ctx.state.query("rule", {"rule_id": rule_id})]
        out["history"] = sorted(rows, key=lambda r: r["version"], reverse=True)
    return out
