"""Read model for the Tools screen (WP22): usage per agent and tool, the least-privilege
suggestion and the diff download. Read only; the diff is built in memory and never applied."""

from __future__ import annotations

import re
from datetime import UTC, date
from typing import Any

from supervisor.analytics import tools, tools_suggest
from supervisor.config import Settings
from supervisor.core.errors import SupervisorError

_ID = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
# sort key -> (column title key is in the template; value getter)
SORTS = ("default", "tool", "risk", "status", "calls", "blocks", "pauses", "errors", "p95", "last")
STATUS_PILL = {"unused": "bad", "undeclared": "warn", "exception": "neutral", "used": "ok"}


class ToolsInputError(SupervisorError):
    """Bad agent id, sort key or window (HTTP 400)."""


def check_agent(agent_id: str | None) -> str | None:
    if agent_id in (None, ""):
        return None
    if not _ID.match(agent_id):
        raise ToolsInputError("invalid agent id")
    return agent_id


def check_days(days: str | int | None, settings: Settings) -> int:
    if days in (None, ""):
        return settings.tool_analytics_window_days
    try:
        n = int(days)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ToolsInputError("days must be a whole number") from exc
    if not 1 <= n <= 366:
        raise ToolsInputError("days must be between 1 and 366")
    return n


def _sort_key(name: str) -> Any:
    risk_rank = tools._risk_rank
    return {
        "tool": lambda r: r["tool"],
        "risk": lambda r: (risk_rank(r["risk_class"]), r["tool"]),
        "status": lambda r: (r["status_rank"], r["tool"]),
        "calls": lambda r: r["calls"],
        "blocks": lambda r: r["blocks"],
        "pauses": lambda r: r["pauses"],
        "errors": lambda r: r["errors"],
        "p95": lambda r: -1 if r["p95_us"] is None else r["p95_us"],
        "last": lambda r: r["last_seen_text"],
    }[name]


def page(
    ctx: Any,
    *,
    agent_id: str | None = None,
    days: str | int | None = None,
    sort: str = "default",
    desc: bool = False,
    lenient_agent: bool = False,
) -> dict[str, Any]:
    """Data for ``tools.html``: one block per agent, one screen each. With ``lenient_agent`` (the
    Agent page tab, WP41 D27) an agent that is not in the policy gives an empty page with
    ``unknown_agent`` set, not an error: a gate-only agent has no onboarding record yet."""
    agent_id = check_agent(agent_id)
    days_n = check_days(days, ctx.settings)
    if sort not in SORTS:
        raise ToolsInputError("unknown sort column")
    as_of = ctx.clock.now().astimezone(UTC).date()
    start, end = tools.window_bounds(as_of, days_n)
    try:
        sug = tools_suggest.build_all(
            ctx.state, ctx.settings, as_of=as_of, days=days_n, agent_id=agent_id
        )
    except tools.AnalyticsError as exc:
        if not (lenient_agent and str(exc).startswith("unknown agent")):
            raise ToolsInputError(str(exc)) from exc
        sug = []
    summary = {
        (r["agent_id"], r["tool_name"]): r
        for r in tools.summarise(
            tools.load_daily(ctx.state, agent_id=agent_id, start=start, end=end)
        )
    }
    order = {"unused": 0, "undeclared": 1, "exception": 2, "used": 3}
    agents = []
    for s in sug:
        rows = []
        for e in [*s["tools"], *s["undeclared"]]:
            m = summary.get((s["agent_id"], e["tool"]), {})
            last = e["last_seen"]
            rows.append(
                {
                    "tool": e["tool"],
                    "risk_class": e["risk_class"],
                    "status": e["status"],
                    "status_rank": order[e["status"]],
                    "pill": STATUS_PILL[e["status"]],
                    "calls": e["calls"],
                    "allows": e["allows"],
                    "blocks": e["blocks"],
                    "pauses": e["pauses"],
                    "errors": m.get("errors", 0),
                    "p50_us": m.get("p50_us"),
                    "p95_us": m.get("p95_us"),
                    "users_max": m.get("users_max", 0),
                    "last_seen_text": last.strftime("%Y-%m-%d") if last else "-",
                    "exception": e["exception"],
                }
            )
        if sort != "default":
            rows.sort(key=_sort_key(sort), reverse=desc)
        agents.append({**s, "rows": rows, "has_diff": bool(s["diff"])})
    return {
        "agents": agents,
        "agent_id": agent_id or "",
        "days": days_n,
        "window_from": start.isoformat(),
        "window_to": end.isoformat(),
        "sort": sort,
        "desc": desc,
        "sorts": SORTS,
        "unknown_agent": bool(lenient_agent and agent_id and not agents),
    }


def diff_download(ctx: Any, agent_id: str, days: str | int | None = None) -> tuple[str, str]:
    """(file name, unified diff text) for one agent. Built in memory; 400 when empty."""
    agent_id = check_agent(agent_id) or ""
    if not agent_id:
        raise ToolsInputError("agent id is required")
    days_n = check_days(days, ctx.settings)
    as_of: date = ctx.clock.now().astimezone(UTC).date()
    try:
        (s,) = tools_suggest.build_all(
            ctx.state, ctx.settings, as_of=as_of, days=days_n, agent_id=agent_id
        )
    except tools.AnalyticsError as exc:
        raise ToolsInputError(str(exc)) from exc
    if not s["diff"]:
        raise ToolsInputError(
            "nothing to change for this agent (no unused tool, or not enough data)"
        )
    return f"least_privilege_{as_of.isoformat()}_{agent_id}.diff", s["diff"]
