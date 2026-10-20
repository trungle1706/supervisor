"""Audit log page (WP-UX3, read-only): the ``console_action`` rows (WP18).

Who did what in the console: actor, permission, target, outcome, and the SHA-256 of the target
row before and after. ``detail`` is a fixed short note by design (an error class name or a
denial code), never text a user typed, so the page shows it as is. The table is append-only; this
module only reads it. Equality filters (actor, permission, outcome) go to the store, the rest is
applied in Python over the newest ``SCAN_CAP`` rows."""

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
from supervisor.console.readmodels import SCAN_CAP, jloads
from supervisor.core import rbac

OUTCOMES = ("attempted", "ok", "denied", "error")
COLUMNS = ("ts", "actor", "permission", "target", "outcome")
PAGE_SIZE = 25
FILTERS = ("actor", "permission", "outcome", "target", "range")
_OUTCOME_RANK = {"error": 0, "denied": 1, "ok": 2, "attempted": 3}


def parse_params(query: Mapping[str, str]) -> dict[str, str]:
    perm = ux3.ident(query, "permission")
    p = {
        "actor": ux3.ident(query, "actor"),
        "permission": perm,
        "outcome": ux3.choice(query, "outcome", OUTCOMES),
        "target": ux3.token(query, "target"),
        "range": ux3.choice(query, "range", ux3.RANGES),
        "sort": query.get("sort") or "",
        "dir": query.get("dir") or "",
        "page": query.get("page") or "",
    }
    parse_int(p["page"], "page", 1)
    return p


def _row(r: Mapping[str, Any]) -> dict[str, Any]:
    kind, tid = r.get("target_kind"), r.get("target_id")
    return {
        "action_id": r["action_id"],
        "ts": r["ts"],
        "actor": r["actor"],
        "actor_kind": r["actor_kind"],
        "auth_method": r["auth_method"],
        "roles": jloads(r.get("roles"), []) if not isinstance(r.get("roles"), list) else r["roles"],
        "permission": r["permission"],
        "method": r["method"],
        "path": r["path"],
        "target": f"{kind}:{tid}" if kind and tid else (kind or ""),
        "target_kind": kind,
        "target_id": tid,
        "outcome": r["outcome"],
        "before_hash": r.get("before_hash"),
        "after_hash": r.get("after_hash"),
        "detail": r.get("detail"),
        "request_id": r["request_id"],
    }


def rows_for(ctx: Any, p: Mapping[str, str]) -> list[dict[str, Any]]:
    where: dict[str, Any] = {}
    for key, col in (("actor", "actor"), ("permission", "permission"), ("outcome", "outcome")):
        if p[key]:
            where[col] = p[key]
    rows = ctx.tables.query("console_action", where, order_by=("-ts",), limit=SCAN_CAP)
    start = ux3.range_start(ctx.clock.now(), p["range"])
    out = []
    for raw in rows:
        if start is not None and raw["ts"] < start:
            continue
        row = _row(raw)
        if p["target"] and p["target"].lower() not in row["target"].lower():
            continue
        out.append(row)
    return out


def ordered(rows: list[dict[str, Any]], p: Mapping[str, str]) -> tuple[list[Any], str, str]:
    col, direction = parse_sort(p["sort"], p["dir"], COLUMNS, "ts", "desc")
    return (
        sort_rows(rows, col, direction, {"outcome": lambda r: _OUTCOME_RANK.get(r["outcome"], 4)}),
        col,
        direction,
    )


def list_view(ctx: Any, query: Mapping[str, str]) -> dict[str, Any]:
    p = parse_params(query)
    rows = rows_for(ctx, p)
    shown, col, direction = ordered(rows, p)
    page = paginate(shown, parse_int(p["page"], "page", 1), PAGE_SIZE)
    base = {k: p[k] for k in FILTERS}
    actors = sorted({r["actor"] for r in rows})
    return {
        "page": page,
        "params": p,
        "sort_col": col,
        "sort_dir": direction,
        "actor_opts": [(a, a) for a in actors],
        "permission_opts": [(k, k) for k in sorted(rbac.PERMISSIONS)],
        "outcome_opts": [(o, f"outcome_{o}") for o in OUTCOMES],
        "range_opts": [(k, f"range_{k}") for k in ux3.RANGES],
        "capped": len(rows) >= SCAN_CAP,
        "base_qs": query_string(base),
        "list_qs": query_string({**base, "sort": col, "dir": direction}),
    }


def drawer_view(ctx: Any, action_id: str, query: Mapping[str, str]) -> dict[str, Any]:
    found = ctx.tables.query("console_action", {"action_id": action_id})
    if not found:
        raise ListingError(f"audit row {action_id} not found")
    row = _row(found[0])
    same = [
        _row(r)
        for r in ctx.tables.query(
            "console_action", {"request_id": row["request_id"]}, order_by=("ts",)
        )
    ]
    p = parse_params(query)
    ids = [r["action_id"] for r in ordered(rows_for(ctx, p), p)[0]]
    i = ids.index(action_id) if action_id in ids else -1
    doc = {k: v for k, v in row.items() if k != "target"}
    return {
        "r": row,
        "same_request": same,
        "changed": bool(
            row["before_hash"] and row["after_hash"] and row["before_hash"] != row["after_hash"]
        ),
        "prev_id": ids[i - 1] if i > 0 else None,
        "next_id": ids[i + 1] if 0 <= i < len(ids) - 1 else None,
        "qs": query_string({k: v for k, v in p.items() if k != "page" and v}),
        "json_text": json.dumps(doc, sort_keys=True, indent=2, default=str),
    }
