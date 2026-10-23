"""WP-P2: the Decision 33 draft checks the declared human_control against the define profile."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from supervisor.adapters.factory import Adapters
from supervisor.governance.classification import ClassificationService
from supervisor.governance.profile_check import check_pre_approval
from supervisor.governance.systems import SystemService
from supervisor.onboard.define import define_artifact

from .conftest import ListSink, add_agent, draft

CS = Path(__file__).resolve().parents[1] / "onboard" / "data" / "artifact_cs_agent"


def _system(gsvc: SystemService, gadapters: Adapters, agent: str) -> str:
    add_agent(gadapters, agent)
    s = gsvc.register(draft(money_movement=True, human_control="pre_approval"), "owner.lan")
    gsvc.link(s["system_id"], "agent", agent, "owner.lan")
    return str(s["system_id"])


def _q(out: dict[str, Any], qid: str = "Q-PRE-APPROVAL") -> dict[str, Any]:
    return next(a for a in out["answers"] if a["id"] == qid)


def _onboard_dir(a: Adapters, agent: str) -> Path:
    return Path(a.settings.data_dir) / "onboard" / agent


def test_gate_found_in_code_keeps_yes_with_the_evidence_ref(
    gsvc: SystemService, gadapters: Adapters, sink: ListSink
) -> None:
    sid = _system(gsvc, gadapters, "cs_agent")
    define_artifact(CS, _onboard_dir(gadapters, "cs_agent"), agent_id="cs_agent")
    out = ClassificationService.from_adapters(gadapters, evidence=sink).draft(sid, "owner.lan")
    a = _q(out)
    assert a["answer"] == "yes" and a["source"] == "rules"
    assert "agent.py:" in a["justification"]  # file:line of interrupt_before


def test_declared_but_not_found_in_code_goes_back_to_a_person(
    gsvc: SystemService, gadapters: Adapters, sink: ListSink
) -> None:
    sid = _system(gsvc, gadapters, "no_gate")
    folder = _onboard_dir(gadapters, "no_gate")
    folder.mkdir(parents=True)
    profile = {
        "tool_risk_classes": {"waive_fee": "money"},
        "decision33": {"human_gate_in_code": False},
    }
    (folder / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    svc = ClassificationService.from_adapters(gadapters, evidence=sink)
    out = svc.draft(sid, "owner.lan")
    a = _q(out)
    assert a["answer"] is None and a["source"] == "person"
    assert "unknown, a person confirms (declared, not found in code)" in a["justification"]
    assert out["outcome"] == "unclassified"


def test_no_profile_or_no_money_tool_changes_nothing(
    gsvc: SystemService, gadapters: Adapters, sink: ListSink, tmp_path: Path
) -> None:
    sid = _system(gsvc, gadapters, "plain")
    out = ClassificationService.from_adapters(gadapters, evidence=sink).draft(sid, "owner.lan")
    assert _q(out)["answer"] == "yes" and "code" not in _q(out)["justification"]
    assert check_pre_approval(tmp_path, ["x"]) == ("no_profile", "")
    folder = tmp_path / "onboard" / "r"
    folder.mkdir(parents=True)
    (folder / "profile.json").write_text(
        json.dumps({"tool_risk_classes": {"a": "read_only"}, "decision33": {}}), encoding="utf-8"
    )
    assert check_pre_approval(tmp_path, ["r"])[0] == "no_profile"


def test_oversized_profile_is_ignored(tmp_path: Path) -> None:
    folder = tmp_path / "onboard" / "big"
    folder.mkdir(parents=True)
    pad = " " * 2_100_000
    (folder / "profile.json").write_text(
        json.dumps({"tool_risk_classes": {"a": "money"}, "decision33": {}}) + pad, encoding="utf-8"
    )
    assert check_pre_approval(tmp_path, ["big"])[0] == "no_profile"
