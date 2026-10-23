"""WP-P2: cross-check of the declared human_control with the define profile of linked agents.

The Decision 33 draft answers ``Q-PRE-APPROVAL`` from the declared field ``human_control``. A
person can declare ``pre_approval`` for a system whose code has no human gate in front of its
money or credit tools. When a linked agent has a define profile (``<DATA_DIR>/onboard/<agent>/
profile.json``, written by ``python -m supervisor.onboard`` or ``define``) the draft checks the
declaration against the code evidence:

* a linked agent with a money or credit tool and ``human_gate_in_code`` false: not confirmed;
* all such agents have the gate: confirmed, with the ``file:line`` evidence;
* no profile, or no money or credit tool: no opinion (the declared answer stays).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

MONEY_CLASSES = ("money", "credit")


MAX_BYTES = 2_000_000  # a profile is a few KB; never read an oversized file


def _load(path: Path) -> dict[str, Any] | None:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _ref(inventory: dict[str, Any] | None) -> str:
    for r in (inventory or {}).get("human_approval_refs") or []:
        if isinstance(r, dict) and r.get("file") and r.get("line"):
            return f"{str(r['file'])[:120]}:{int(r['line'])}"
    return "profile.json#decision33"


def check_pre_approval(data_dir: Path | str, agent_ids: Iterable[str]) -> tuple[str, str]:
    """(verdict, text). Verdict is ``no_profile``, ``confirmed`` or ``not_found``."""
    confirmed: list[str] = []
    missing: list[str] = []
    for agent_id in sorted(set(agent_ids)):
        folder = Path(data_dir) / "onboard" / agent_id
        profile = _load(folder / "profile.json")
        if profile is None:
            continue
        classes = profile.get("tool_risk_classes") or {}
        if not any(c in MONEY_CLASSES for c in classes.values()):
            continue
        d33 = profile.get("decision33") or {}
        if d33.get("human_gate_in_code") is True:
            confirmed.append(f"{agent_id} ({_ref(_load(folder / 'inventory.json'))})")
        else:
            missing.append(agent_id)
    if missing:
        return (
            "not_found",
            "unknown, a person confirms (declared, not found in code): the define profile of "
            + ", ".join(missing)
            + " shows no human gate in code for its money or credit tool",
        )
    if confirmed:
        return "confirmed", "human gate found in code: " + ", ".join(confirmed)
    return "no_profile", ""
