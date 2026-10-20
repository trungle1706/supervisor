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
        return {"open": 2, "done": 5, "ratio": 0.5, "nested": {"x": 1}}


def test_absent_package_says_not_built(env: Env) -> None:
    r = env.svc.preview("payments", "regulator")
    s = r["sections"]["controls"]
    if s["reason"] != "not_built":  # a build that already has WP30: the flag is off by default
        assert s["reason"] == "flag_off" and s["ref"] == "CONTROLS_ENABLED"


def test_fake_package_flag_off_then_on(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    ctl = types.ModuleType("supervisor.controls")
    ctl.ControlService = _FakeControls  # type: ignore[attr-defined]
    tasks = types.ModuleType("supervisor.tasks")
    tasks.TaskService = _FakeTasks  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "supervisor.controls", ctl)
    monkeypatch.setitem(sys.modules, "supervisor.tasks", tasks)
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
    assert d["uncovered_risks_n"] == 2 and d["coverage"][0]["controls_n"] == 1
    assert d["tasks"] == {"open": 2, "done": 5}  # plain top-level values only, no float
    assert "secret.owner" not in env.texts(reg)
    assert internal["sections"]["controls"]["data"]["controls"][0]["owner"]
    assert cust["sections"]["controls"]["reason"] == "not_for_variant"
    text = render.plain_text(reg, "en")
    assert "never read working" in text
    assert "không bao giờ" in render.plain_text(reg, "vi")
