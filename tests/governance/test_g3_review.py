"""WP-G3 review M1: the "Confirm context" task of a scan draft is visible on the system Tasks
tab, and an overdue system task opens no case on a made-up agent lane."""

from __future__ import annotations

from typing import Any

from supervisor.inventory.autoregister import GovernanceConfig, _open_task

from .conftest import Console, draft

REVIEWER = "reviewer.an"


def _draft_with_only_a_node_link(c: Console) -> str:
    s = c.ctx.systems.register(draft(owner_user=REVIEWER), REVIEWER)
    sid = str(s["system_id"])
    now = c.ctx.clock.now()
    c.ctx.state.insert(
        "inventory_node",
        {
            "node_id": "inv_0123456789abcdef",
            "kind": "genie_space",
            "name": "lending analytics",
            "display_name": "Lending analytics",
            "status": "unmanaged",
            "own_risk": None,
            "risk_source": "none",
            "decision33_class": None,
            "attrs": {"workspace_kind": "genie_space"},
            "evidence": [{"source": "workspace_scan", "ref": "workspace:genie-space/x"}],
            "first_seen": now,
            "last_seen": now,
        },
    )
    c.ctx.systems.link(sid, "node", "inv_0123456789abcdef", REVIEWER, source="workspace_scan")
    _open_task(c.ctx.tasks, sid, GovernanceConfig())
    return sid


def test_tasks_tab_shows_the_task_of_a_draft_with_only_a_node_link(on: Console) -> None:
    sid = _draft_with_only_a_node_link(on)
    r = on.get(f"/console/systems/{sid}?tab=tasks&lang=en", user=REVIEWER)
    assert r.status_code == 200
    assert "SYS-CONFIRM-CONTEXT" in r.text and "Confirm context" in r.text
    assert "system-own-tasks" in r.text
    detail = on.get(f"/console/systems/{sid}?lang=en", user=REVIEWER).text
    assert 'data-tab="tasks"' in detail


def test_overdue_system_task_opens_no_case_and_writes_one_notice(
    on: Console, monkeypatch: Any
) -> None:
    sid = _draft_with_only_a_node_link(on)
    tasks = on.ctx.tasks
    monkeypatch.setattr(tasks, "overdue", lambda row, now=None: True)
    before = len(on.ctx.cases.list_cases())
    first = tasks.run_due(on.ctx.cases)
    assert first["overdue"] == 1 and first["cases_opened"] == 0
    assert len(on.ctx.cases.list_cases()) == before
    notices = [e for e in tasks.events() if e["agent_id"] == sid and e["action"] == "overdue"]
    assert len(notices) == 1
    tasks.run_due(on.ctx.cases)  # a second sweep writes no second notice
    again = [e for e in tasks.events() if e["agent_id"] == sid and e["action"] == "overdue"]
    assert len(again) == 1
