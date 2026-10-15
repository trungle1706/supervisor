"""WP16: the corpus tuning keeps the demo agents' Discover + Understand results unchanged.

The snapshots in ``snapshots/demo_<agent>.json`` were taken before any WP16 analyser change.
Fields added later (new keys) are allowed; every key in the snapshot must keep its value.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from supervisor.onboard.discover import Discovery
from supervisor.onboard.models import AgentProfile
from tests.onboard.conftest import AGENT_IDS

SNAPSHOTS = Path(__file__).parent / "snapshots"


def _diff(old: Any, new: Any, path: str, out: list[str]) -> None:
    if isinstance(old, dict):
        if not isinstance(new, dict):
            out.append(f"{path}: type changed")
            return
        for k, v in old.items():
            if k not in new:
                out.append(f"{path}.{k}: missing")
            else:
                _diff(v, new[k], f"{path}.{k}", out)
    elif isinstance(old, list):
        if not isinstance(new, list) or len(old) != len(new):
            out.append(f"{path}: list changed ({len(old)} -> {len(new) if new else 0})")
            return
        for i, (a, b) in enumerate(zip(old, new, strict=True)):
            _diff(a, b, f"{path}[{i}]", out)
    elif old != new:
        out.append(f"{path}: {old!r} -> {new!r}")


@pytest.mark.parametrize("agent", AGENT_IDS)
def test_demo_agent_results_unchanged(
    agent: str, discoveries: dict[str, Discovery], profiles: dict[str, AgentProfile]
) -> None:
    snap = json.loads((SNAPSHOTS / f"demo_{agent}.json").read_text(encoding="utf-8"))
    now = {
        "inventory": discoveries[agent].inventory.model_dump(mode="json"),
        "profile": profiles[agent].model_dump(mode="json"),
    }
    out: list[str] = []
    _diff(snap, now, agent, out)
    assert out == [], "\n".join(out[:40])
