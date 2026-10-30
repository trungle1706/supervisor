"""UX5 agent factory helpers (CONSOLE_UX5, group G6): plain event log, step stages.

Pure functions; ``factory_view.editor_data`` calls them only when the flag is on."""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping, Sequence
from typing import Any

from supervisor.factory import caps

# Stage name key -> steps in it. A step not listed lands in the last stage.
STAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("u6_stage_define", ("template", "policy")),
    ("u6_stage_build", ("checklist", "tools", "instructions")),
    ("u6_stage_check", ("harness", "guardians", "preview")),
    ("u6_stage_test", ("golden", "gate")),
)

_RUN_ID = re.compile(r"\s*\bgate_[0-9a-f]{12,}\b")
_SIM = re.compile(r"^simulation (gate_[0-9a-f]+): (\{.*\})$")


def stages(steps: Sequence[str]) -> list[dict[str, Any]]:
    """The steps of this agent grouped in stages (a missing step is skipped)."""
    out: list[dict[str, Any]] = []
    placed: set[str] = set()
    for name, members in STAGES:
        mine = [s for s in steps if s in members]
        placed.update(mine)
        if mine:
            out.append({"name": name, "steps": mine})
    rest = [s for s in steps if s not in placed]
    if rest:
        if out:
            out[-1]["steps"].extend(rest)
        else:
            out.append({"name": "u6_stage_test", "steps": rest})
    return out


GOLDEN_MIN = caps.GOLDEN_MIN_CASES


def step_status(ed: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Per step: ``state`` (done, todo or warn) and a short ``note`` (a count or a verdict word).

    Pure read of the editor data: the definition, the lint result and the card of the agent."""
    defn = ed.get("defn") or {}
    agent = ed.get("agent") or {}
    n_check = len(defn.get("checklist") or [])
    n_ref = len(defn.get("policy_refs") or [])
    n_tool = len(defn.get("tools") or [])
    lint_err = sum(1 for i in ed.get("lint") or [] if i.get("severity") == "error")
    golden_n = int(agent.get("golden_size") or 0)
    last = agent.get("last_gate") or None
    out: dict[str, dict[str, str]] = {
        "template": {"state": "done" if defn.get("name") else "todo", "note": ""},
        "policy": {"state": "done" if n_ref else "todo", "note": str(n_ref)},
        "checklist": {"state": "done" if n_check else "todo", "note": str(n_check)},
        "tools": {"state": "done" if n_tool else "todo", "note": str(n_tool)},
        "instructions": {
            "state": "warn" if lint_err else ("done" if defn.get("instructions") else "todo"),
            "note": str(lint_err) if lint_err else "",
        },
        "harness": {"state": "done", "note": ""},
        "guardians": {"state": "done", "note": str(len(defn.get("guardians") or []))},
        "preview": {"state": "none", "note": ""},
        "golden": {
            "state": "done" if golden_n >= GOLDEN_MIN else "todo",
            "note": f"{golden_n}/{GOLDEN_MIN}",
        },
    }
    if last:
        verdict = str(last.get("verdict") or "")
        state = "done" if verdict == "pass" else ("warn" if verdict == "fail" else "todo")
        out["gate"] = {"state": state, "note": verdict.replace("_", " ")}
    else:
        out["gate"] = {"state": "todo", "note": ""}
    return out


def next_step(status: Mapping[str, Mapping[str, str]], steps: Sequence[str]) -> str:
    """The first step (in page order) that is not done; empty when all are done."""
    for s in steps:
        if status.get(s, {}).get("state") in ("todo", "warn"):
            return s
    return ""


def event_rows(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One plain row per event. Simulation re-marks of one run fold into one row (the newest
    counts win, ``n`` = how many marks). ``events`` are newest first."""
    out: list[dict[str, Any]] = []
    sim_seen: dict[str, dict[str, Any]] = {}
    for e in events:
        kind = str(e.get("kind") or "")
        detail = str(e.get("detail") or "")
        m = _SIM.match(detail)
        if m:
            run = m.group(1)
            if run in sim_seen:
                sim_seen[run]["n"] += 1
                continue
            try:
                counts = ast.literal_eval(m.group(2))
            except (ValueError, SyntaxError):
                counts = {}
            row = {
                "kind": "simulation",
                "actor": e.get("actor_ref"),
                "counts": counts if isinstance(counts, dict) else {},
                "n": 1,
                "text": "",
            }
            sim_seen[run] = row
            out.append(row)
            continue
        out.append(
            {
                "kind": kind,
                "actor": e.get("actor_ref"),
                "text": _RUN_ID.sub("", detail).strip(" ;:"),
                "counts": {},
                "n": 1,
            }
        )
    return out
