"""Global search box (WP-UX1): agents, cases and traces that match a short text.

Read-only. Agents and cases match by substring on id and name; a trace matches by exact trace
id (no fuzzy index, no free-text scan of events), and only from ``TRACE_MIN`` characters: the
box searches on each keystroke and a trace lookup is one SQL call (on Delta, no index). At most
``LIMIT`` hits per kind."""

from __future__ import annotations

import re
from typing import Any

from supervisor.console.listing import ListingError

LIMIT = 5
MAX_LEN = 64
TRACE_MIN = 8  # shorter text cannot be a trace id worth a lookup
_Q = re.compile(r"^[A-Za-z0-9_.:@ -]+$")


def clean(raw: str | None) -> str:
    q = (raw or "").strip()
    if len(q) > MAX_LEN or (q and not _Q.match(q)):
        raise ListingError("search text may hold letters, digits and . _ : @ - only (64 max)")
    return q


def run(ctx: Any, raw: str | None) -> dict[str, Any]:
    q = clean(raw)
    out: dict[str, Any] = {"q": q, "agents": [], "cases": [], "traces": []}
    if len(q) < 2:
        return out
    low = q.lower()
    for a in sorted(ctx.state.query("agent"), key=lambda r: r["agent_id"]):
        if low in f"{a['agent_id']} {a.get('name') or ''}".lower():
            out["agents"].append({"agent_id": a["agent_id"], "name": a.get("name") or ""})
            if len(out["agents"]) >= LIMIT:
                break
    for c in ctx.cases.list_cases():
        if low in c["case_id"].lower() or low in str(c.get("summary") or "").lower():
            out["cases"].append(
                {
                    "case_id": c["case_id"],
                    "agent_id": c["agent_id"],
                    "severity": c["severity"],
                    "status": c["status"],
                }
            )
            if len(out["cases"]) >= LIMIT:
                break
    if len(q) >= TRACE_MIN and " " not in q:
        seen: set[str] = set()
        for e in ctx.tables.query("agent_event", {"trace_id": q}, limit=50):
            if e["agent_id"] not in seen:
                seen.add(e["agent_id"])
                out["traces"].append({"trace_id": q, "agent_id": e["agent_id"]})
    return out
