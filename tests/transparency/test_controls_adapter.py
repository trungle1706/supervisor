"""WP31 optional adapter for WP30 (controls and tasks): absent package, flag off, fake package."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from supervisor.transparency import render
from supervisor.transparency.harness import Env


class _FakeControls:
    @classmethod
    def from_adapters(cls, _a: Any) -> _FakeControls:
        return cls()

    def agent_compliance(self, agent_id: str) -> dict[str, Any]:
        return {
            "in_scope": 3,
            "working": 1,
            "failing": 0,
            "no_data": 2,
            "compliance_bp": 3333,
            "product_in_scope": 2,
            "product_working": 1,
            "product_bp": 5000,
            "bank_in_scope": 1,
            "controls": [
                {
                    "control_id": "CTL-1",
                    "title": "Single limit",
                    "control_type": "preventive",
                    "implemented_by": "product",
                    "owner": "secret.owner@example.invalid",
                    "status": "working",
                    "reason": "controls_working",
                    "stale": False,
                }
            ],
        }

    def obligation_coverage(self, agent_id: str) -> list[dict[str, Any]]:
        return [{"obligation": "VN-QD33-2026-PL4.1-01", "status": "working", "controls": ["CTL-1"]}]

    def uncovered_risks(self) -> list[str]:
        return ["RSK-1", "RSK-2"]


class _FakeTasks:
    @classmethod
    def from_adapters(cls, _a: Any) -> _FakeTasks:
        return cls()

    def agent_summary(self, agent_id: str) -> dict[str, Any]:
        # the shape of TaskService.agent_summary on branch wp30-controls (subset)
        return {
            "agent_id": agent_id,
            "d33_class": "high_risk",
            "band": "high",
            "stage": "initiation",
            "generated": True,
            "level": "high",
            "counts": {"open": 2, "done": 5},
            "required_open": 2,
            "required_total": 7,
            "stage_done_bp": 2857,
            "overdue": 0,
            "next_stage": None,
            "ratio": 0.5,
            "tasks": [{"id": "T-1", "owner": "secret.owner@example.invalid"}],
        }


def test_absent_package_says_not_built(env: Env) -> None:
    r = env.svc.preview("payments", "regulator")
    s = r["sections"]["controls"]
    if s["reason"] != "not_built":  # a build that already has WP30: the flag is off by default
        assert s["reason"] == "flag_off" and s["ref"] == "CONTROLS_ENABLED"


def test_fake_package_flag_off_then_on(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    # WP30 exports the services from ``.service`` modules, not from the packages
    ctl = types.ModuleType("supervisor.controls")
    ctl_svc = types.ModuleType("supervisor.controls.service")
    ctl_svc.ControlService = _FakeControls  # type: ignore[attr-defined]
    tasks = types.ModuleType("supervisor.tasks")
    tasks_svc = types.ModuleType("supervisor.tasks.service")
    tasks_svc.TaskService = _FakeTasks  # type: ignore[attr-defined]
    for name, mod in (
        ("supervisor.controls", ctl),
        ("supervisor.controls.service", ctl_svc),
        ("supervisor.tasks", tasks),
        ("supervisor.tasks.service", tasks_svc),
    ):
        monkeypatch.setitem(sys.modules, name, mod)
    off = env.svc.preview("payments", "regulator")["sections"]["controls"]
    assert (off["available"], off["reason"], off["ref"]) == (False, "flag_off", "CONTROLS_ENABLED")
    env.settings.__dict__["controls_enabled"] = True
    try:
        reg = env.svc.preview("payments", "regulator")
        internal = env.svc.preview("payments", "internal")
        cust = env.svc.preview("payments", "customer")
    finally:
        env.settings.__dict__.pop("controls_enabled", None)
    d = reg["sections"]["controls"]["data"]
    assert d["compliance_bp"] == 3333 and d["product_bp"] == 5000 and d["bank_note"] is True
    assert d["controls"][0]["control_id"] == "CTL-1" and "owner" not in d["controls"][0]
    # RSK-1 and RSK-2 are not risks payments reaches: the count is per agent
    assert d["uncovered_risks_n"] == 0 and d["coverage"][0]["controls_n"] == 1
    assert d["tasks"] == {
        "stage": "initiation",
        "generated": True,
        "level": "high",
        "required_open": 2,
        "required_total": 7,
        "stage_done_bp": 2857,
        "overdue": 0,
        "next_stage": None,
        "counts_done": 5,
        "counts_open": 2,
    }  # named fields only: no float, no task rows, no agent id
    assert "secret.owner" not in env.texts(reg)
    assert internal["sections"]["controls"]["data"]["controls"][0]["owner"]
    assert cust["sections"]["controls"]["reason"] == "not_for_variant"
    text = render.plain_text(reg, "en")
    assert "never read working" in text
    assert "không bao giờ" in render.plain_text(reg, "vi")


def test_flag_off_imports_nothing(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """With CONTROLS_ENABLED off the service modules are never imported."""
    from supervisor.transparency import controls_adapter

    seen: list[str] = []
    real = controls_adapter.importlib.import_module

    def spy(name: str, *a: Any) -> Any:
        seen.append(name)
        return real(name, *a)

    monkeypatch.setitem(sys.modules, "supervisor.controls", types.ModuleType("supervisor.controls"))
    monkeypatch.setattr(controls_adapter.importlib, "import_module", spy)
    s = env.svc.preview("payments", "regulator")["sections"]["controls"]
    assert s["reason"] == "flag_off" and not [n for n in seen if "controls" in n or "tasks" in n]


def test_package_without_service_module_is_not_built(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A package with no ``.service`` (or no ControlService) never breaks the report."""
    monkeypatch.setitem(sys.modules, "supervisor.controls", types.ModuleType("supervisor.controls"))
    monkeypatch.setitem(sys.modules, "supervisor.controls.service", None)
    env.settings.__dict__["controls_enabled"] = True
    try:
        s = env.svc.preview("payments", "regulator")["sections"]["controls"]
    finally:
        env.settings.__dict__.pop("controls_enabled", None)
    assert (s["available"], s["reason"]) == (False, "not_built")


def test_uncovered_risks_are_counted_for_this_agent(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    mine = sorted(r["risk_id"] for r in env.svc.facts.risk_summary("payments")["risks"])
    assert mine, "the starter register gives payments risks"

    class _Ctl(_FakeControls):
        def uncovered_risks(self) -> list[str]:
            return [mine[0], "RSK-OTHER-AGENT"]

    ctl_svc = types.ModuleType("supervisor.controls.service")
    ctl_svc.ControlService = _Ctl  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "supervisor.controls", types.ModuleType("supervisor.controls"))
    monkeypatch.setitem(sys.modules, "supervisor.controls.service", ctl_svc)
    monkeypatch.setitem(sys.modules, "supervisor.tasks.service", None)
    env.settings.__dict__["controls_enabled"] = True
    try:
        d = env.svc.preview("payments", "regulator")["sections"]["controls"]["data"]
    finally:
        env.settings.__dict__.pop("controls_enabled", None)
    assert d["uncovered_risks_n"] == 1 and d["tasks"] == {}
