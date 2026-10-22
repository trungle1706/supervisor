"""Autonomy level proposal (WP-G3): a segmentation dimension, deterministic, with evidence.

Levels, ordered: ``l0_rule_based`` (no model decides), ``l1_assistive`` (model writes text, a
person acts), ``l2_workflow_step`` (a fixed workflow calls a model for a step, the model calls
no tool), ``l3_tool_using_supervised`` (the model picks tools from a bounded set, a person
approves consequential actions), ``l4_autonomous_bounded`` (plans and executes multi-step work
end to end inside an authority boundary, a person monitors and can pause), ``l5_self_directed``
(sets sub-goals, spawns agents or changes its own tools).

Rules, first match wins; when the evidence is mixed the higher level is chosen and the ``why``
says so (docs/onboard.md, "Autonomy level proposal"). This is a proposal; a person confirms it.
Not the same as the WP16 ``profile.autonomy`` (L0 to L3), which is unchanged.
"""

from __future__ import annotations

import re
from typing import Any

from supervisor.onboard.discover import Discovery
from supervisor.onboard.models import Evidence
from supervisor.onboard.understand import _approval_refs, _has_side_effect

LEVELS: tuple[str, ...] = (
    "l0_rule_based",
    "l1_assistive",
    "l2_workflow_step",
    "l3_tool_using_supervised",
    "l4_autonomous_bounded",
    "l5_self_directed",
)
_SPAWN = re.compile(
    r"(?i)\b(spawn_?agents?|create_?sub_?agents?|sub_?agents?\s*=|AgentFactory|register_tool\(|"
    r"add_tool\(|self\.(?:system_)?prompt\s*(?:\+)?=|rewrite_?prompt|update_?own_?(?:prompt|tools))"
)
_INTERRUPT = re.compile(
    r"(?i)\binterrupt\s*\(|interrupt_before|interrupt_after|human_?in_?the_?loop|"
    r"HumanApproval|require_confirmation|confirm_before"
)
_LOOP = re.compile(
    r"(?i)create_react_agent|AgentExecutor|initialize_agent|plan_and_execute|PlanAndExecute|"
    r"\bplanner\b|StateGraph\(|\bwhile\s+(?:True|not\s+\w*done)\b|max_iterations|recursion_limit"
)
_BATCH = re.compile(
    r"(?i)dbutils\.widgets|def\s+\w*(?:batch|job|pipeline|handler)\w*\s*\(|@dlt\.|"
    r"\bforeachBatch\b|spark\.read|\bbatch_?size\b"
)


def _grep(disc: Discovery, rx: re.Pattern[str], limit: int = 3) -> list[Evidence]:
    out: list[Evidence] = []
    for f in sorted(disc.index.lines):
        if not f.endswith((".py", ".yaml", ".yml")):
            continue
        for i, line in enumerate(disc.index.lines[f], start=1):
            if not line.lstrip().startswith("#") and rx.search(line):
                out.append(disc.index.evidence(f, i))
                if len(out) >= limit:
                    return out
    return out


def _result(level: str, why: str, ev: list[Evidence], disc: Discovery) -> dict[str, Any]:
    if not ev:  # the proposal always points somewhere
        ev = [
            disc.index.evidence(
                disc.inventory.manifest_file or (sorted(disc.index.lines) or ["-"])[0], 1
            )
        ]
    return {
        "level": level,
        "why": why,
        "evidence": [e.model_dump(mode="json") for e in ev[:4]],
        "is_proposal": True,
    }


def propose_autonomy_level(disc: Discovery) -> dict[str, Any]:
    inv = disc.inventory
    spawn = _grep(disc, _SPAWN)
    if spawn:
        return _result(
            "l5_self_directed",
            "code spawns agents, creates tools at run time or rewrites its own prompt",
            spawn,
            disc,
        )
    calls = [c.evidence for c in inv.llm_calls]
    model_ev = calls or [e.evidence for e in inv.model_endpoints if e.evidence is not None]
    if not model_ev and not inv.model_id:
        return _result("l0_rule_based", "no model call found: no model decides", [], disc)
    tools = list(inv.tools)
    loop = _grep(disc, _LOOP)
    if not tools:
        batch = _grep(disc, _BATCH)
        routes = [e.evidence for e in inv.entrypoints if str(e.detail).startswith("route:")]
        # a ``__main__`` block alone does not make a job: a chat server has one too
        if batch:
            why = "a model call in a job or batch handler; no tool declared"
            if routes:
                why += " (also an HTTP entry point: the higher level is kept)"
            return _result("l2_workflow_step", why, batch + model_ev, disc)
        return _result(
            "l1_assistive",
            "a model call behind a chat or HTTP entry point; no tool declared",
            model_ev + routes,
            disc,
        )
    acting = [t for t in tools if _has_side_effect(t)]
    interrupt = _grep(disc, _INTERRUPT)
    approval = list(inv.human_approval_refs) + interrupt
    uncovered = [t.name for t in acting if not _approval_refs(inv, [t]) and not interrupt]
    if not acting:
        return _result(
            "l3_tool_using_supervised",
            "the model picks tools from a bounded set and every tool only reads: "
            "no consequential action to approve",
            [t.definition or t.manifest_entry for t in tools if t.definition or t.manifest_entry]
            + loop,
            disc,
        )
    if approval and not uncovered:
        return _result(
            "l3_tool_using_supervised",
            "tools with side effects are each behind a human approval or interrupt step in code",
            approval + loop,
            disc,
        )
    if approval:
        why = (
            "approval step found, but these tools with side effects have none: "
            + ", ".join(sorted(uncovered))
            + " (mixed evidence: the higher level is kept)"
        )
    elif loop:
        why = "a planner or loop calls tools with side effects and no approval step in code"
    else:
        why = "tools with side effects are called by the model with no approval step in code"
    ev = approval + loop + [t.definition for t in acting if t.definition is not None]
    return _result("l4_autonomous_bounded", why, ev or model_ev, disc)
