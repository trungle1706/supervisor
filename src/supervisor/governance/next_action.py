"""Recommended next action for an agent (WP-N2; the same rule list as WP-N1, section 1.3).

First match wins:

1. an overdue required task of the agent or of its AI system  -> "Finish task <title>"
2. a stage approval of its system that waits for this person  -> "Approve stage"
3. Decision 33 class not set                                  -> "Classify (Decision 33)"
4. a guardian feature of the floor is not effective           -> "Switch on <slug>"
5. gate SHADOW for more than 7 days and no open case          -> "Request RUNNING"
6. an open case                                               -> "Triage case"
7. otherwise                                                  -> "No action"

Read only. ``recommended_action(ctx, agent_card, system_row)`` returns
``{key, text_key, href, args}``; ``text_key`` is an i18n key and ``args`` its format values.
A caller that builds many rows calls :func:`prefetch` once and passes the result as ``pre`` so
the task list is read once, not once per row. A card of kind ``policy_only`` or ``candidate``
gets the Register action. A failed read leaves that rule out; the function does not raise.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

SHADOW_DAYS = 7


def prefetch(
    ctx: Any, me: Any = None, systems: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Data the rules share between rows: open required tasks and the stage approvals that wait
    for ``me`` (by system id)."""
    tasks: list[dict[str, Any]] = []
    if getattr(ctx.settings, "controls_enabled", False):
        try:
            tasks = [
                t
                for t in ctx.tasks.list_tasks()
                if t["required"] and t["status"] in ("open", "in_progress")
            ]
        except Exception:  # noqa: BLE001 - a convenience read, never a page failure
            tasks = []
    stages: dict[str, dict[str, Any]] = {}
    if me is not None and systems:
        try:
            from supervisor.console import systems_overview

            for item in systems_overview.stage_approvals(ctx, me, systems):
                stages.setdefault(str(item["href"]).rsplit("/", 1)[-1], item)
        except Exception:  # noqa: BLE001
            stages = {}
    return {"tasks": tasks, "stages": stages}


def _since_days(card: Mapping[str, Any], now: dt.datetime) -> int | None:
    since = card.get("state_since")
    return (now - since).days if isinstance(since, dt.datetime) else None


def _act(key: str, text_key: str, href: str, **args: Any) -> dict[str, Any]:
    return {"key": key, "text_key": text_key, "href": href, "args": args}


def recommended_action(
    ctx: Any,
    agent_card: Mapping[str, Any],
    system_row: Mapping[str, Any] | None,
    pre: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    aid = str(agent_card["agent_id"])
    kind = agent_card.get("kind") or "registered"
    if kind == "policy_only":
        return _act("register", "mya_ra_register", f"/console/agents/{aid}?tab=register")
    if kind == "candidate":
        node = agent_card.get("node_id", "")
        return _act("register", "mya_ra_register", f"/console/systems/new?from={node}")
    pre = pre if pre is not None else prefetch(ctx)
    sid = str(system_row["system_id"]) if system_row else None
    ids = {aid} | ({sid} if sid else set())
    overdue = [t for t in pre.get("tasks", []) if t["agent_id"] in ids and t.get("overdue")]
    if overdue:
        first = sorted(overdue, key=lambda t: (str(t.get("due_at") or "9"), t["task_id"]))[0]
        return _act("task", "mya_ra_task", "/console/tasks", title=str(first["title"]))
    stage = (pre.get("stages") or {}).get(sid or "")
    if stage:
        return _act(
            "stage",
            "mya_ra_stage",
            f"/console/systems/{sid}",
            frm=str(stage["from_stage"]),
            to=str(stage["to_stage"]),
        )
    d33 = (agent_card.get("d33") or {}).get("cls") or agent_card.get("decision33_class")
    if not d33 and not (system_row or {}).get("decision33_class"):
        href = f"/console/systems/{sid}" if sid else f"/console/agents/{aid}?tab=register"
        return _act("classify", "mya_ra_classify", href)
    below = list((agent_card.get("guard") or {}).get("below") or [])
    if below:
        href = f"/console/agents/{aid}?tab=guardians"
        return _act("guardian", "mya_ra_guardian", href, slug=below[0])
    open_n = int(agent_card.get("open_cases") or 0)
    if agent_card.get("state") == "SHADOW" and not open_n:
        days = _since_days(agent_card, ctx.clock.now())
        if days is not None and days > SHADOW_DAYS:
            return _act("running", "mya_ra_running", f"/console/agents/{aid}", days=days)
    if open_n:
        return _act("case", "mya_ra_case", f"/console/cases?agent={aid}", n=open_n)
    return _act("none", "mya_ra_none", "")
