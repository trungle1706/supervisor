"""WP30: /v1/controls and /v1/tasks routes (RBAC, audit, errors), the Controls and Tasks pages, the
drawers and the Agent tabs. Both flags are off by default. Viewer reads; reviewer, owner and admin
edit; a waiver needs an approver or admin who is a different person."""

from __future__ import annotations

from typing import Any

import pytest

from supervisor.inventory.service import InventoryService
from tests.conftest import REPO_ROOT

from .conftest import Console

STARTERS = REPO_ROOT / "config" / "controls"
RISKS = REPO_ROOT / "config" / "risks"
HX = {"HX-Request": "true"}


@pytest.fixture
def on(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    s = console.ctx.settings
    for flag in (
        "controls_enabled",
        "console_controls_enabled",
        "risk_register_enabled",
        "inventory_enabled",
    ):
        monkeypatch.setattr(s, flag, True)
    InventoryService.from_adapters(console.runtime.adapters).fill_manifests()
    assert console.ctx.risks.import_path(RISKS, "t", source="starter").errors == []
    res = console.ctx.controls.import_path(STARTERS, "t", source="starter")
    assert res.errors == [], res.errors
    return console


def _post(c: Console, url: str, body: Any, user: str = "reviewer.an") -> Any:
    return c.client.post(url, json=body, headers={"X-Dev-User": user})


def test_off_by_default(console: Console) -> None:
    s = console.ctx.settings
    assert s.controls_enabled is False and s.console_controls_enabled is False
    for url in ("/v1/controls", "/v1/controls/CTL-X", "/v1/tasks", "/v1/tasks/agents/payments"):
        r = console.get(url)
        assert r.status_code == 400 and "CONTROLS_ENABLED" in r.json()["error"], url
    for page in ("controls", "tasks"):
        r = console.get(f"/console/{page}")
        assert r.status_code == 400 and "CONSOLE_CONTROLS_ENABLED" in r.text
        assert f"/console/{page}" not in console.get("/console/").text
    assert console.get("/console/agents/payments/tab/controls", headers=HX).status_code == 400


def test_list_get_and_agent_views(on: Console) -> None:
    c = on
    body = c.get("/v1/controls", user="viewer.hoa").json()
    assert body["count"] == 29
    one = c.get("/v1/controls/CTL-PAY-LIMIT", user="viewer.hoa").json()
    assert one["agents"] == ["payments"] and "PAY-02" in one["maps"]["rule"]
    assert c.get("/v1/controls?type=preventive&agent=payments").json()["count"] >= 5
    comp = c.get("/v1/controls/agents/payments").json()
    assert comp["in_scope"] > 5 and comp["compliance_bp"] == 0
    assert comp["bank_in_scope"] == 3 and comp["obligations"]
    # the risk register sees the control through a link
    links = c.get("/v1/risks/RSK-PAY-001").json()["links"]
    assert {"kind": "control", "target": "CTL-PAY-LIMIT"} in links


def test_bad_input_is_400_and_unknown_is_404(on: Console) -> None:
    c = on
    assert c.get("/v1/controls/CTL-NOPE").status_code == 404
    assert c.get("/v1/controls/bad%20id%3Cscript%3E").status_code == 400
    assert c.get("/v1/controls?type=magic").status_code == 400
    assert c.get("/v1/controls?nope=1").status_code == 400
    assert _post(c, "/v1/controls", {"title": "x"}).status_code == 400
    assert _post(c, "/v1/controls/CTL-NOPE", {"owner": "x"}).status_code == 404
    bad_map = {"kind": "rule", "target": "PAY-777"}
    assert _post(c, "/v1/controls/CTL-PAY-LIMIT/maps", bad_map).status_code == 400
    assert c.get("/v1/tasks/tsk_nope").status_code == 404
    assert c.get("/v1/tasks?stage=nope").status_code == 400
    assert _post(c, "/v1/tasks/tsk_nope/done", {}).status_code == 404


def test_rbac_and_audit_on_control_edit(on: Console) -> None:
    c = on
    new = {
        "control_id": "CTL-NEW",
        "title": "New",
        "objective": "O",
        "control_type": "detective",
        "implemented_by": "bank",
        "owner": "ops",
        "status": "draft",
    }
    assert _post(c, "/v1/controls", new, user="viewer.hoa").status_code == 403
    r = _post(c, "/v1/controls", new)
    assert r.status_code == 201 and r.json()["control_id"] == "CTL-NEW"
    r = _post(c, "/v1/controls/CTL-NEW/maps", {"kind": "document", "target": "doc-1"})
    assert r.status_code == 200 and r.json()["added"] is True
    rows = [
        x
        for x in c.ctx.tables.query("console_action", order_by=("ts",))
        if x["permission"] == "controls.edit"
    ]
    assert {x["outcome"] for x in rows} >= {"attempted", "ok", "denied"}
    chained = c.ctx.tables.query("chain_entry", {"record_type": "control_change"})
    assert chained


def test_task_flow_and_two_person_waiver(on: Console) -> None:
    c = on
    r = _post(c, "/v1/tasks/agents/payments/generate", {})
    assert r.status_code == 200 and r.json()["created_n"] > 3
    summary = c.get("/v1/tasks/agents/payments").json()
    assert summary["stage"] == "initiation" and summary["required_open"] > 0
    tid = next(t["task_id"] for t in summary["tasks"] if t["template_id"] == "INI-REGISTER")
    assert _post(c, f"/v1/tasks/{tid}/waive", {"reason": ""}).status_code == 400
    ask = _post(c, f"/v1/tasks/{tid}/waive", {"reason": "pilot"}, user="reviewer.binh")
    assert ask.status_code == 200
    # a reviewer without the approver role is refused; the person who asked cannot answer
    assert _post(c, f"/v1/tasks/{tid}/waive/approve", {}, user="reviewer.an").status_code == 403
    same = _post(c, f"/v1/tasks/{tid}/waive/approve", {}, user="reviewer.binh")
    assert same.status_code == 400 and "different person" in same.json()["error"]
    r = _post(c, f"/v1/tasks/{tid}/waive/approve", {}, user="approver.em")
    assert r.status_code == 200 and r.json()["status"] == "waived"
    # a move with an open required task is refused with 400
    move = next(t["task_id"] for t in summary["tasks"] if t["kind"] == "move")
    r = _post(c, f"/v1/tasks/{move}/done", {})
    assert r.status_code == 400 and "refused" in r.json()["error"]
    assert c.get(f"/v1/tasks/{tid}").json()["events"]


def test_pages_drawers_and_tabs(on: Console) -> None:
    c = on
    _post(c, "/v1/tasks/agents/payments/generate", {})
    for url in (
        "/console/controls",
        "/console/controls?drawer=CTL-PAY-LIMIT&dtab=map",
        "/console/controls/CTL-PAY-LIMIT/drawer?tab=status",
        "/console/controls/rows?type=preventive",
        "/console/tasks",
        "/console/tasks/rows?stage=initiation",
        "/console/agents/payments/tab/controls",
        "/console/agents/payments/tab/tasks",
    ):
        r = c.get(url, headers=HX)
        assert r.status_code == 200, (url, r.text[:200])
    page = c.get("/console/controls").text
    assert "CTL-PAY-LIMIT" in page and "/console/controls" in c.get("/console/").text
    assert "INI-REGISTER" in c.get("/console/tasks").text
    tid = c.ctx.tasks.rows_of("payments")[0]["task_id"]
    assert c.get(f"/console/tasks/{tid}/drawer?tab=history", headers=HX).status_code == 200
    assert c.get("/console/controls?type=magic").status_code == 400
    assert c.get("/console/controls/CTL-NOPE/drawer", headers=HX).status_code == 400


def test_tab_without_a_task_list(on: Console) -> None:
    r = on.get("/console/agents/payments/tab/tasks", headers=HX)
    assert r.status_code == 200 and "supervisor.tasks generate" in r.text


def test_tasks_csv_route(on: Console) -> None:
    c = on
    _post(c, "/v1/tasks/agents/payments/generate", {})
    r = c.get("/v1/tasks/export.csv", user="viewer.hoa")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.text.splitlines()[0].startswith("task_id,agent_id") and r.text.isascii()
    assert r.headers["x-rows-truncated"] == "false"
    capped = c.get("/v1/tasks/export.csv?limit=2")
    assert len(capped.text.splitlines()) == 3 and capped.headers["x-rows-truncated"] == "true"
    assert c.get("/v1/tasks/export.csv?limit=0").status_code == 400
    assert c.get("/v1/tasks/export.csv?agent=bad%20id").status_code == 400
