"""UX5 agent factory helpers (CONSOLE_UX5, group G6): plain event log, step stages.

Pure functions; ``factory_view.editor_data`` calls them only when the flag is on."""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping, Sequence
from typing import Any

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
