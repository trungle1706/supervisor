"""WP30 review: route probes for /v1/controls and /v1/tasks (bank security reviewer view).

Viewer writes are 403 and audited as denied; 20+ bad bodies are 400, never 500; the approver
closes a high-level move and an approver task through POST /v1/tasks/{id}/approve; the first
line cannot close a second-line task; overdue required tasks open one real case each, once; the
dev-header laptop posture (one person at the keyboard can pick two user ids) is documented and
the same identity is refused."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.inventory.service import InventoryService
from tests.conftest import REPO_ROOT

from .conftest import Console

STARTERS = REPO_ROOT / "config" / "controls"
RISKS = REPO_ROOT / "config" / "risks"


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
    assert console.ctx.controls.import_path(STARTERS, "t", source="starter").errors == []
    return console


def _post(c: Console, url: str, body: Any, user: str = "reviewer.an") -> Any:
    return c.client.post(url, json=body, headers={"X-Dev-User": user})


def _raw(c: Console, url: str, data: bytes, user: str = "admin.chi") -> Any:
    return c.client.post(
        url, content=data, headers={"X-Dev-User": user, "Content-Type": "application/json"}
    )


def _tasks(c: Console, agent: str = "payments") -> dict[str, dict[str, Any]]:
    return {t["template_id"]: t for t in c.get(f"/v1/tasks/agents/{agent}").json()["tasks"]}


def test_viewer_writes_are_403_and_audited(on: Console) -> None:
    c = on
    assert _post(c, "/v1/tasks/agents/payments/generate", {}).status_code == 200
    tid = _tasks(c)["INI-REGISTER"]["task_id"]
    for url, body in (
        ("/v1/tasks/agents/payments/generate", {}),
        (f"/v1/tasks/{tid}/done", {}),
        (f"/v1/tasks/{tid}/start", {}),
        (f"/v1/tasks/{tid}/waive", {"reason": "x"}),
        (f"/v1/tasks/{tid}/waive/approve", {}),
        (f"/v1/tasks/{tid}/approve", {}),
        ("/v1/tasks", {"agent_id": "payments", "title": "t"}),
        ("/v1/controls/CTL-PAY-LIMIT", {"owner": "x"}),
        ("/v1/controls/CTL-PAY-LIMIT/maps", {"kind": "document", "target": "d"}),
    ):
        assert _post(c, url, body, user="viewer.hoa").status_code == 403, url
    denied = [
        x
        for x in c.ctx.tables.query("console_action")
        if x["outcome"] == "denied" and x["path"].startswith(("/v1/tasks", "/v1/controls"))
    ]
    assert len(denied) >= 9


BAD_BODIES: list[tuple[str, bytes]] = [
    ("/v1/controls", b"not json"),
    ("/v1/controls", b"[1, 2]"),
    ("/v1/controls", b'{"control_id": 7}'),
    ("/v1/controls", b'{"control_id": "CTL-Z", "title": ["a"]}'),
    ("/v1/controls", b'{"control_id": "CTL-Z", "maps": "rule"}'),
    ("/v1/controls", b'{"control_id": "CTL-Z", "maps": [{"kind": "rule"}]}'),
    (
        "/v1/controls",
        b'{"control_id": "CTL-Z", "title": "t", "objective": "o", "control_type": "preventive",'
        b' "implemented_by": "product", "owner": "o", "status": "active", "review_date": "x"}',
    ),
    ("/v1/controls/CTL-PAY-LIMIT", b'{"row_version": true}'),
    ("/v1/controls/CTL-PAY-LIMIT", b'{"row_version": "1"}'),
    ("/v1/controls/CTL-PAY-LIMIT", b'{"control_id": "CTL-OTHER"}'),
    ("/v1/controls/CTL-PAY-LIMIT", b'{"agents": "payments"}'),
    ("/v1/controls/CTL-PAY-LIMIT", b'{"status": "done"}'),
    ("/v1/controls/CTL-PAY-LIMIT", b'{"review_date": 20270101}'),
    ("/v1/controls/CTL-PAY-LIMIT/maps", b'{"kind": "rule", "target": ["PAY-02"]}'),
    ("/v1/controls/CTL-PAY-LIMIT/maps", b'{"kind": "sql", "target": "x"}'),
    ("/v1/controls/CTL-PAY-LIMIT/maps", b'{"kind": "rule", "target": "PAY-02", "action": 1}'),
    ("/v1/tasks", b'{"agent_id": "payments", "title": 5}'),
    ("/v1/tasks", b'{"agent_id": "payments", "title": "t", "due_days": "7"}'),
    ("/v1/tasks", b'{"agent_id": "payments", "title": "t", "owner_role": "boss"}'),
    ("/v1/tasks", b'{"agent_id": "bad id!", "title": "t"}'),
    ("/v1/tasks/{tid}/done", b'{"evidence_ref": 12}'),
    ("/v1/tasks/{tid}/done", b'{"evidence_ref": "bad ref with spaces"}'),
    ("/v1/tasks/{tid}/waive", b'{"reason": 3}'),
    ("/v1/tasks/{tid}/waive", b'{"reason": "' + b"x" * 1200 + b'"}'),
    ("/v1/tasks/{tid}/approve", b"{"),
    ("/v1/tasks/bad%20id/done", b"{}"),
]


def test_bad_bodies_are_400_never_500(on: Console) -> None:
    c = on
    _post(c, "/v1/tasks/agents/payments/generate", {})
    tid = _tasks(c)["INI-PURPOSE"]["task_id"]
    assert len(BAD_BODIES) >= 20
    for url, data in BAD_BODIES:
        r = _raw(c, url.replace("{tid}", tid), data)
        assert r.status_code == 400, (url, data[:60], r.status_code, r.text[:200])


def test_approver_closes_the_move_and_the_first_line_cannot(on: Console) -> None:
    c = on
    _post(c, "/v1/tasks/agents/payments/generate", {})
    t = _tasks(c)
    level = c.get("/v1/tasks/agents/payments").json()["level"]
    for tid in [x["task_id"] for x in t.values() if x["kind"] != "move"]:
        r = _post(c, f"/v1/tasks/{tid}/done", {"evidence_ref": "doc-1"}, user="admin.chi")
        assert r.status_code == 200, r.text
    move = next(x for x in t.values() if x["kind"] == "move")
    if level in ("high", "critical"):
        r = _post(c, f"/v1/tasks/{move['task_id']}/done", {})  # a reviewer
        assert r.status_code == 400 and "approver" in r.json()["error"]
    r = _post(c, f"/v1/tasks/{move['task_id']}/approve", {}, user="approver.em")
    assert r.status_code == 200 and r.json()["status"] == "done", r.text
    # /approve is only for moves and approver tasks
    design = _tasks(c)
    owner_task = next(
        x for x in design.values() if x["stage"] == "design" and x["owner_role"] == "owner"
    )
    r = _post(c, f"/v1/tasks/{owner_task['task_id']}/approve", {}, user="approver.em")
    assert r.status_code == 400 and "/done" in r.json()["error"]


def test_overdue_required_tasks_open_one_real_case_each_once(on: Console) -> None:
    c = on
    _post(c, "/v1/tasks/agents/payments/generate", {})
    svc = c.ctx.tasks
    later = c.ctx.clock.now() + dt.timedelta(days=90)
    svc.clock = SimpleNamespace(now=lambda: later)
    first = svc.run_due(c.ctx.cases)
    assert first["overdue"] >= 2 and first["cases_opened"] == first["overdue"]
    again = svc.run_due(c.ctx.cases)
    assert again["cases_opened"] == 0
    links = c.ctx.tables.query("case_link", {"source_kind": "task"})
    assert len(links) == first["cases_opened"]
    assert len({x["source_ref"] for x in links}) == len(links)


def test_dev_header_posture_and_same_identity(on: Console) -> None:
    """Dev-header mode (laptop, ADR D04) is not a real identity: one person at the keyboard can
    ask as one user id and answer as another. That is the accepted laptop posture and is
    documented in docs/controls.md; the App uses SSO. The same identity is always refused."""
    c = on
    _post(c, "/v1/tasks/agents/payments/generate", {})
    t = _tasks(c)
    a, b = t["INI-REGISTER"]["task_id"], t["INI-PURPOSE"]["task_id"]
    ask = _post(c, f"/v1/tasks/{a}/waive", {"reason": "pilot"}, user="admin.chi")
    assert ask.status_code == 200
    same = _post(c, f"/v1/tasks/{a}/waive/approve", {}, user="admin.chi")
    assert same.status_code == 400 and "different person" in same.json()["error"]
    assert _post(c, f"/v1/tasks/{b}/waive", {"reason": "pilot"}).status_code == 200
    other = _post(c, f"/v1/tasks/{b}/waive/approve", {}, user="approver.em")
    assert other.status_code == 200 and other.json()["status"] == "waived"
    assert "dev_header" in (REPO_ROOT / "docs" / "controls.md").read_text(encoding="utf-8")
