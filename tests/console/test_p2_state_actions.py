"""WP-P2 (phase 8): Request and Approve RUNNING on the agent page (CONSOLE_STATE_ACTIONS).

Off path first (no panel, the routes answer 400 with the flag name). Then the two-person rule with
the synthetic identities of config/users.yaml and policies/baseline.yaml: ``reviewer.an`` and
``reviewer.binh`` are policy reviewers, ``payops-lead@example.invalid`` owns ``payments``,
``approver.em`` holds the approver role only (allowed to use the button, not to approve)."""

from __future__ import annotations

import datetime as dt
import re

import pytest

from supervisor.console import agent_guardians

from .conftest import Console

OWNER = "payops-lead@example.invalid"
HX = {"HX-Request": "true"}


@pytest.fixture
def sa(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(console.ctx.settings, "console_state_actions", True)
    console.ctx.gateway.states.set_mode("payments", "SHADOW", "admin.chi")
    return console


def _card(html: str) -> str:
    return html.split('data-agent="payments"', 1)[1].split("</article>", 1)[0]


def _state(c: Console) -> str:
    return str(c.ctx.state.get("agent", {"agent_id": "payments"})["gate_state"])


# ------------------------------------------------------------------------------ off path


def test_flag_is_off_by_default(console: Console) -> None:
    assert console.ctx.settings.console_state_actions is False


def test_off_no_panel_and_routes_answer_400_with_the_flag_name(console: Console) -> None:
    console.ctx.gateway.states.set_mode("payments", "SHADOW", "admin.chi")
    page = console.get("/console/agents/payments")
    assert page.status_code == 200 and 'data-section="mode"' not in page.text
    for step in ("request", "approve"):
        r = console.post(f"/console/agents/payments/running/{step}", {"reason": "go live"})
        assert r.status_code == 400 and "CONSOLE_STATE_ACTIONS=1" in r.text
    assert _state(console) == "SHADOW"
    assert console.ctx.gateway.states.pending_mode("payments") == []


def test_off_pause_and_resume_still_work(console: Console) -> None:
    r = console.post("/console/agents/payments/pause", {"reason": "x"})
    assert r.status_code == 200 and "by reviewer.an" in r.text


# --------------------------------------------------------------------------------- on


def test_panel_shows_request_button_and_the_would_block_count(sa: Console) -> None:
    html = sa.get("/console/agents/payments").text
    card = _card(html)
    assert 'data-section="mode"' in card and "/payments/running/request" in card
    assert "/payments/running/approve" not in card
    assert 'data-num="would_block_7d">0<' in card
    # one shadow would-block verdict on a gate decision of the last 7 days: count 1
    now = sa.ctx.clock.now()
    event = sa.ctx.tables.query(
        "agent_event", {"agent_id": "payments", "event_type": "gate_decision"}, limit=1
    )[0]
    sa.ctx.tables.append(
        "verdict",
        [
            {
                "verdict_id": "vp2-1",
                "event_id": event["event_id"],
                "ts": now,
                "agent_id": "payments",
                "tier": 0,
                "checker_id": "gate:tier0a",
                "is_mock": False,
                "advisory": False,
                "label": "shadow_would_block",
                "action": "log",
                "rule_id": "PAY-02",
            }
        ],
    )
    expected = agent_guardians._gate_results(sa.ctx, "payments", now - dt.timedelta(days=7))
    assert expected["would_block"] == 1
    card = _card(sa.get("/console/agents/payments").text)
    assert 'data-num="would_block_7d">1<' in card and "last 7 days" in card


def test_running_agent_has_no_panel(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_state_actions", True)
    assert _state(console) == "RUNNING"
    assert 'data-section="mode"' not in console.get("/console/agents/payments").text


def test_reason_is_required(sa: Console) -> None:
    r = sa.post("/console/agents/payments/running/request", {"reason": "   "})
    assert r.status_code == 400 and "reason_required" in r.text
    assert sa.ctx.gateway.states.pending_mode("payments") == []


def test_request_then_approve_by_the_owner(sa: Console) -> None:
    r = sa.post("/console/agents/payments/running/request", {"reason": "7 days clean"})
    assert r.status_code == 200 and "RUNNING requested" in r.text
    card = _card(r.text)  # the HTMX fragment is the agent card, no full page
    assert "<html" not in r.text and 'data-mode-pending="1"' in card
    assert "RUNNING requested by reviewer.an" in card and "7 days clean" in card
    assert "/payments/running/approve" not in card  # the requester sees no approve button
    assert "different person" in card
    assert _state(sa) == "SHADOW"
    # the owner sees the approve button
    owner_card = _card(sa.get("/console/agents/payments", user=OWNER).text)
    assert "/payments/running/approve" in owner_card
    r = sa.post("/console/agents/payments/running/approve", {"reason": "checked"}, user=OWNER)
    assert r.status_code == 200 and "RUNNING approved; the state is now RUNNING" in r.text
    assert _state(sa) == "RUNNING"
    assert 'data-section="mode"' not in _card(r.text)


def test_request_then_approve_by_a_policy_reviewer(sa: Console) -> None:
    assert (
        sa.post(
            "/console/agents/payments/running/request", {"reason": "go"}, user=OWNER
        ).status_code
        == 200
    )
    r = sa.post("/console/agents/payments/running/approve", {"reason": "ok"}, user="reviewer.binh")
    assert r.status_code == 200 and _state(sa) == "RUNNING"


def test_the_requester_cannot_approve_same_person(sa: Console) -> None:
    sa.post("/console/agents/payments/running/request", {"reason": "go"})
    r = sa.post("/console/agents/payments/running/approve", {"reason": "me again"})
    assert r.status_code == 400 and "same_person" in r.text
    assert _state(sa) == "SHADOW"
    assert len(sa.ctx.gateway.states.pending_mode("payments")) == 1


def test_a_person_outside_owner_and_reviewers_cannot_approve(sa: Console) -> None:
    sa.post("/console/agents/payments/running/request", {"reason": "go"})
    r = sa.post("/console/agents/payments/running/approve", {"reason": "ok"}, user="approver.em")
    assert r.status_code == 400 and "needs the agent owner or a reviewer" in r.text
    card = _card(sa.get("/console/agents/payments", user="approver.em").text)
    assert "/payments/running/approve" not in card and "Only the agent owner" in card
    assert _state(sa) == "SHADOW"


def test_approve_without_a_request_and_a_second_request(sa: Console) -> None:
    r = sa.post("/console/agents/payments/running/approve", {"reason": "ok"}, user=OWNER)
    assert r.status_code == 400 and "no_request" in r.text
    sa.post("/console/agents/payments/running/request", {"reason": "go"})
    r = sa.post(
        "/console/agents/payments/running/request", {"reason": "again"}, user="reviewer.binh"
    )
    assert r.status_code == 400 and "request_pending" in r.text
    assert _state(sa) == "SHADOW"


def test_roles_unknown_step_and_non_htmx(sa: Console) -> None:
    r = sa.post("/console/agents/payments/running/request", {"reason": "go"}, user="viewer.hoa")
    assert r.status_code == 403
    r = sa.post("/console/agents/payments/running/launch", {"reason": "go"})
    assert r.status_code == 400
    r = sa.post("/console/agents/payments/running/request", {"reason": "go"}, htmx=False)
    assert r.status_code == 400
    r = sa.post("/console/agents/nope/running/request", {"reason": "go"})
    assert r.status_code == 400 and "not registered" in r.text
    assert sa.ctx.gateway.states.pending_mode("payments") == []


def test_a_pause_voids_the_pending_request(sa: Console) -> None:
    sa.post("/console/agents/payments/running/request", {"reason": "go"})
    assert sa.post("/console/agents/payments/pause", {"reason": "x"}).status_code == 200
    r = sa.post("/console/agents/payments/running/approve", {"reason": "ok"}, user=OWNER)
    assert r.status_code == 400  # the agent is PAUSED now; nothing waits
    assert _state(sa) == "PAUSED"


def test_two_audit_rows_per_step_and_a_chain_record(sa: Console) -> None:
    before = len(sa.ctx.tables.query("console_action"))
    sa.post("/console/agents/payments/running/request", {"reason": "go"})
    rows = sa.ctx.tables.query("console_action", order_by=("ts",))[before:]
    assert len(rows) == 2 and {r["permission"] for r in rows} == {"agent.mode"}
    assert [r["outcome"] for r in rows] == ["attempted", "ok"]
    sa.post("/console/agents/payments/running/approve", {"reason": "go"})  # same person: refused
    rows = sa.ctx.tables.query("console_action", order_by=("ts",))[before + 2 :]
    assert [r["outcome"] for r in rows] == ["attempted", "error"]


def test_fragment_matches_the_page_card(sa: Console) -> None:
    sa.post("/console/agents/payments/running/request", {"reason": "go"})
    page = _card(sa.get("/console/agents/payments").text)
    tab = sa.get("/console/agents/payments/tab/overview", headers=HX).text
    for needle in ('data-mode-pending="1"', "RUNNING requested by reviewer.an"):
        assert needle in page and needle in tab
    assert re.search(r'data-agent="payments" data-state="SHADOW"', tab)
