"""Description and recommended action of a system or an agent (WP-N1, plan section 1.3).

``recommend`` takes plain facts and returns the first rule that matches. The first two ingredients
come from ``supervisor.console.systems_overview.next_action`` (the open required task, the stage
approval that waits); the other rules read the facts the caller gathered. Pure: no query here.

Rule order (the first match wins):

1. an overdue required task            -> ``finish_task`` (text: the task title)
2. a stage approval that waits for me  -> ``approve_stage``
3. Decision 33 class unclassified      -> ``classify``
4. a guardian below the floor          -> ``switch_on`` (text: the feature slug)
5. gate SHADOW for over 7 days, no open case -> ``request_running``
6. an open case                        -> ``triage_case``
7. any other open required task        -> ``finish_task``
8. else                                -> ``none``

Each result is ``{key, arg, href}``; ``key`` maps to the i18n key ``ov4_na_<key>``.

The My agents page (WP-N2) uses the row-oriented form of the same rules: ``prefetch`` once, then
``recommended_action(ctx, agent_card, system_row, pre)`` per row, which returns
``{key, text_key, href, args}`` (``text_key`` an i18n key, ``args`` its format values). A card of
kind ``policy_only`` or ``candidate`` gets the Register action; a failed read leaves a rule out."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from supervisor.console.systems_overview import next_action as first_task_or_stage

SHADOW_DAYS = 7
RULES: tuple[str, ...] = (
    "finish_task_overdue",
    "approve_stage",
    "classify",
    "switch_on",
    "request_running",
    "triage_case",
    "finish_task",
    "none",
)


def _result(key: str, arg: str = "", href: str = "") -> dict[str, str]:
    return {"key": key, "arg": arg, "href": href}


def shadow_days(created_at: Any, now: dt.datetime) -> int | None:
    """Days since the agent row was created. The gate keeps no timestamp of a state change, so the
    age of the row is the nearest honest figure (see docs/triage.md)."""
    if not isinstance(created_at, dt.datetime):
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=dt.UTC)
    return max(0, (now - created_at).days)


def recommend(
    *,
    system: Mapping[str, Any] | None,
    agents: list[str],
    tasks: list[dict[str, Any]],
    waiting: Mapping[str, dict[str, Any]],
    can_decide: bool,
    below_floor: list[str],
    shadow_agents: list[str],
    open_cases: int,
    owner_id: str | None = None,
) -> dict[str, str]:
    """The first matching rule. ``system`` is the ``ai_system`` row, or None for an agent that is
    on no system (rules 2 and 3 then skip). ``below_floor`` lists feature slugs that are not
    effective though the floor holds them; ``shadow_agents`` the agents in SHADOW for more than
    ``SHADOW_DAYS`` days."""
    sid = str(system["system_id"]) if system else (owner_id or "")
    nxt = first_task_or_stage(sid, agents, tasks, waiting) if sid else None
    task_href = "/console/tasks"
    if nxt and nxt["kind"] == "task" and nxt["overdue"]:
        return _result("finish_task_overdue", nxt["text"], task_href)
    if system and can_decide and waiting.get(sid):
        return _result("approve_stage", "", f"/console/systems/{sid}")
    if system and str(system.get("decision33_class") or "unclassified") == "unclassified":
        return _result("classify", "", f"/console/systems/{sid}?tab=classification")
    if below_floor:
        return _result("switch_on", below_floor[0], f"/console/systems/{sid}?tab=guardians")
    if shadow_agents and not open_cases:
        return _result("request_running", shadow_agents[0], f"/console/agents/{shadow_agents[0]}")
    if open_cases:
        return _result("triage_case", str(open_cases), "/console/cases")
    if nxt and nxt["kind"] == "task":
        return _result("finish_task", nxt["text"], task_href)
    return _result("none")


def describe_system(row: Mapping[str, Any]) -> str:
    """The purpose of the system (one line). Empty when the intake has none."""
    return " ".join(str(row.get("purpose") or "").split())[:240]


def describe_agent(card: Mapping[str, Any]) -> str:
    """One sentence built from the registry row and the card: name, model family, host type, tool
    count, risk tier. English; the console uses the same ingredients for Vietnamese."""
    name = str(card.get("name") or card.get("agent_id") or "")
    bits = [
        f"model family {card['model_family']}" if card.get("model_family") else "",
        f"hosted as {card['host_type']}" if card.get("host_type") else "",
        f"{card['tools_n']} tools" if card.get("tools_n") is not None else "",
        f"risk tier {card['risk_tier']}" if card.get("risk_tier") else "",
    ]
    rest = ", ".join(b for b in bits if b)
    return f"Agent {name}" + (f": {rest}." if rest else ".")


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
