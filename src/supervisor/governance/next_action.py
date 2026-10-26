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

Each result is ``{key, arg, href}``; ``key`` maps to the i18n key ``ov4_na_<key>``."""

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
