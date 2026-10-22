"""WP-G1 task sizing by the risk level of the system an agent is linked to."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.cases.service import SystemActor
from supervisor.governance.systems import SystemService
from supervisor.tasks import model as tm
from supervisor.tasks.service import TaskService

from .conftest import ListSink, add_agent, draft


def _tasks(adapters: Adapters, sink: ListSink, governance: bool = True) -> TaskService:
    adapters.settings.governance_enabled = governance
    return TaskService.from_adapters(adapters, evidence=sink)


def _linked(adapters: Adapters, svc: SystemService, level: str, agent: str = "a1") -> str:
    add_agent(adapters, agent, risk_tier="low")
    s = svc.register(draft(), "owner.lan")
    svc.link(s["system_id"], "agent", agent, "owner.lan")
    if level != "unspecified":
        svc.update_fields(s["system_id"], {"risk_level": level}, "owner.lan")
    return str(s["system_id"])


def test_unlinked_agent_is_sized_as_before_with_the_flag_on_or_off(
    adapters: Adapters, sink: ListSink
) -> None:
    add_agent(adapters, "u1", risk_tier="medium", decision33_class="high_risk")
    add_agent(adapters, "u2", risk_tier="low")
    add_agent(adapters, "u3", risk_tier="critical")
    add_agent(adapters, "u4", risk_tier="unknown")
    off = _tasks(adapters, sink, governance=False)
    before = {a: off.agent_inputs(a) for a in ("u1", "u2", "u3", "u4")}
    on = _tasks(adapters, sink, governance=True)
    after = {a: on.agent_inputs(a) for a in ("u1", "u2", "u3", "u4")}
    assert before == after  # the same dict, key for key
    assert set(before["u1"]) == {
        "agent_id",
        "d33_class",
        "band",
        "band_source",
        "level",
        "gate_state",
    }
    assert before["u1"]["band"] == "medium" and before["u1"]["level"] == "high"
    assert before["u4"]["band"] == "high" and before["u4"]["band_source"] == "default"


@pytest.mark.parametrize(
    ("system_level", "band", "level"),
    [("low", "low", "medium"), ("medium", "medium", "medium"), ("high", "high", "high")]
    + [("prohibited", "critical", "critical")],
)
def test_linked_agent_takes_the_level_of_its_system_and_the_d33_floor(
    adapters: Adapters, svc: SystemService, sink: ListSink, system_level: str, band: str, level: str
) -> None:
    _linked(adapters, svc, system_level)  # decision33_class None: unclassified, floor medium
    inp = _tasks(adapters, sink).agent_inputs("a1")
    assert inp["band"] == band and inp["band_source"] == "system"
    assert inp["level"] == level and inp["system_level"] == system_level


def test_the_floor_of_a_high_risk_class_beats_a_low_system(
    adapters: Adapters, svc: SystemService, sink: ListSink
) -> None:
    add_agent(adapters, "a1", decision33_class="high_risk")
    s = svc.register(draft(), "owner.lan")
    svc.link(s["system_id"], "agent", "a1", "owner.lan")
    svc.update_fields(s["system_id"], {"risk_level": "low"}, "owner.lan")
    assert _tasks(adapters, sink).agent_inputs("a1")["level"] == "high"


def test_inherited_level_of_the_system_counts(
    adapters: Adapters, svc: SystemService, sink: ListSink
) -> None:
    add_agent(adapters, "a1", risk_tier="high", decision33_class="not_high_risk")
    s = svc.register(draft(), "owner.lan")
    svc.link(s["system_id"], "agent", "a1", "owner.lan")  # manual level stays unspecified
    inp = _tasks(adapters, sink).agent_inputs("a1")
    assert inp["system_level"] == "high" and inp["level"] == "high"


def test_unspecified_system_gives_the_initiation_set_only(
    adapters: Adapters, svc: SystemService, sink: ListSink
) -> None:
    add_agent(adapters, "a1", risk_tier="unknown", decision33_class="not_high_risk")
    s = svc.register(draft(), "owner.lan")
    svc.link(s["system_id"], "agent", "a1", "owner.lan")
    tasks = _tasks(adapters, sink)
    out = tasks.generate("a1", SystemActor())
    assert out["created_n"] > 0
    summary = tasks.agent_summary("a1")
    assert summary["next_stage"] is None
    assert {t["stage"] for t in summary["tasks"]} == {"initiation"}
    assert not [t for t in summary["tasks"] if t["kind"] == "move"]
    # a person sets the level: the move to the next stage appears, nothing is removed
    svc.update_fields(s["system_id"], {"risk_level": "medium"}, "owner.lan")
    tasks.generate("a1", SystemActor())
    again = tasks.agent_summary("a1")
    assert again["next_stage"] == "design"
    assert [t for t in again["tasks"] if t["kind"] == "move"]
    assert {t["task_id"] for t in summary["tasks"]} <= {t["task_id"] for t in again["tasks"]}


def test_the_list_never_gets_lighter_when_the_system_level_goes_down(
    adapters: Adapters, svc: SystemService, sink: ListSink
) -> None:
    sid = _linked(adapters, svc, "high")
    tasks = _tasks(adapters, sink)
    tasks.generate("a1", SystemActor())
    n = len(tasks.rows_of("a1"))
    level = tasks.agent_summary("a1")["level"]
    svc.update_fields(sid, {"risk_level": "low"}, "owner.lan")
    tasks.generate("a1", SystemActor())
    assert len(tasks.rows_of("a1")) >= n
    assert tm.LEVEL_RANK[tasks.agent_summary("a1")["level"]] >= tm.LEVEL_RANK[level]


def test_archived_system_does_not_size_the_agent(
    adapters: Adapters, svc: SystemService, sink: ListSink
) -> None:
    sid = _linked(adapters, svc, "high")
    svc.archive(sid, "owner.lan")
    inp = _tasks(adapters, sink).agent_inputs("a1")
    assert inp["band_source"] == "risk_tier"


def test_two_systems_the_higher_level_wins(
    adapters: Adapters, svc: SystemService, sink: ListSink
) -> None:
    _linked(adapters, svc, "low")
    s2 = svc.register(draft(name="Second system"), "owner.lan")
    svc.link(s2["system_id"], "agent", "a1", "owner.lan")
    svc.update_fields(s2["system_id"], {"risk_level": "high"}, "owner.lan")
    inp = _tasks(adapters, sink).agent_inputs("a1")
    assert inp["system_level"] == "high" and len(inp["system_ids"].split(",")) == 2


# --------------------------------------------------------------- template keys on the system scale


def _doc(**over: Any) -> dict[str, Any]:
    t = {"id": "X-1", "stage": "design", "title": "A task", **over}
    return {"templates": [t]}


def test_template_keys_on_the_system_scale_mean_the_same() -> None:
    old = tm.parse_config(_doc(min_level="high", required_from="critical"))
    new = tm.parse_config(_doc(min_risk_level="high", required_from_level="prohibited"))
    assert dataclasses.asdict(old.templates[0]) == dataclasses.asdict(new.templates[0])
    assert new.templates[0].min_level == "high" and new.templates[0].required_from == "critical"


@pytest.mark.parametrize(
    "bad",
    [
        {
            "min_risk_level": "critical"
        },  # critical is the task scale; the system scale has prohibited
        {"required_from_level": "unspecified"},
        {"min_level": "low", "min_risk_level": "low"},
        {"required_from": "low", "required_from_level": "low"},
    ],
)
def test_bad_template_keys_are_refused(bad: dict[str, str]) -> None:
    with pytest.raises(tm.TaskError):
        tm.parse_config(_doc(**bad))


def test_the_shipped_file_has_the_stage_policy_and_parses(tmp_path: Path) -> None:
    from supervisor.governance import stages

    assert stages.load_policy() == {
        **{s: False for s in stages.DEFAULT_APPROVAL},
        "deployment": True,
        "operation": True,
    }
    assert stages.parse_policy({}) == stages.DEFAULT_APPROVAL
    assert stages.parse_policy({"stages": {"design": {"approval": True}}})["design"] is True
    for bad in ({"stages": []}, {"stages": {"x": {"approval": True}}}, {"stages": {"design": 1}}):
        with pytest.raises(Exception, match="stages"):
            stages.parse_policy(bad)
