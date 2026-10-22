"""WP-G1 console: the Tasks and Reviews tabs of the system page (EN and VI, scope, 400)."""

from __future__ import annotations

from typing import Any

import pytest

from supervisor.cases.service import SystemActor
from supervisor.console import i18n, systems_views

from .conftest import Console, draft, person

OWNER_USER = "payops-lead@example.invalid"
PAYOPS = "Payments Ops"
REVIEWER = "reviewer.an"
APPROVER = "approver.em"


def _system(c: Console, **over: Any) -> str:
    s = c.ctx.systems.register(draft(owner_user=REVIEWER, **over), REVIEWER)
    return str(s["system_id"])


def _tab(c: Console, sid: str, tab: str, lang: str = "en", user: str = REVIEWER) -> Any:
    return c.get(f"/console/systems/{sid}?tab={tab}&lang={lang}", user=user)


def test_tabs_are_listed_and_unknown_tab_is_400(on: Console) -> None:
    assert systems_views.DETAIL_TABS == ("overview", "components", "tasks", "reviews")
    sid = _system(on)
    html = on.get(f"/console/systems/{sid}?lang=en").text
    assert 'data-tab="tasks"' in html and 'data-tab="reviews"' in html
    assert ">Tasks" in html and ">Reviews" in html
    r = _tab(on, sid, "nope")
    assert r.status_code == 400


def test_reviews_tab_lists_reviews_and_the_count(on: Console) -> None:
    sid = _system(on)
    r = _tab(on, sid, "reviews")
    assert r.status_code == 200 and "No reviews yet." in r.text
    rv = on.ctx.reviews.create(
        sid,
        {
            "kind": "conformity",
            "title": "Conformity check <b>",
            "reviewer_user": "rev.an",
            "window_start": "2026-02-01T00:00:00Z",
            "reports": [{"kind": "note", "ref": "n"}],
        },
        "plan.er",
    )
    on.ctx.reviews.complete(sid, rv["review_id"], person("rev.an", "reviewer"))
    en = _tab(on, sid, "reviews").text
    assert "Conformity check &lt;b&gt;" in en and "<b>" not in en.split("system-reviews")[1]
    assert "Completed" in en and "locked" in en and "2026-02-01" in en
    assert "Conformity" in en and rv["review_id"] in en
    vi = _tab(on, sid, "reviews", lang="vi").text
    assert "Hoàn thành" in vi and "đã khóa" in vi and "Rà soát" in vi
    on.ctx.reviews.reopen(sid, rv["review_id"], person("rev.an", "reviewer"), "More evidence")
    assert "reopened 1x" in _tab(on, sid, "reviews").text


def test_tasks_tab_shows_the_stage_and_the_approvals(on: Console) -> None:
    sid = _system(on)
    life = on.ctx.lifecycle
    ap = life.request(sid, "deployment", REVIEWER)
    html = _tab(on, sid, "tasks").text
    assert "Stage of the system: Initiation" in html
    assert "Deployment, Operation" in html  # the stages that need an approval
    assert "Waiting" in html and REVIEWER in html
    life.decide(sid, ap["approval_id"], "approve", person(APPROVER, "approver"))
    life.move(sid, "deployment", REVIEWER)
    html = _tab(on, sid, "tasks").text
    assert "Stage of the system: Deployment" in html
    assert "Approved" in html and "used for the move" in html
    vi = _tab(on, sid, "tasks", lang="vi").text
    assert "Đã duyệt" in vi and "Triển khai" in vi
    assert "No agent is linked" in html


def test_tasks_tab_with_the_task_list_off_and_on(on: Console) -> None:
    sid = _system(on)
    on.ctx.systems.link(sid, "agent", "payments", REVIEWER)
    assert on.ctx.settings.controls_enabled is False
    assert "CONTROLS_ENABLED" in _tab(on, sid, "tasks").text
    on.ctx.settings.controls_enabled = True
    try:
        assert "No task list for this agent yet." in _tab(on, sid, "tasks").text
        on.ctx.systems.update_fields(sid, {"risk_level": "high"}, REVIEWER)
        on.ctx.tasks.generate("payments", SystemActor())
        html = _tab(on, sid, "tasks").text
        assert "INI-REGISTER" in html and "payments" in html
        assert "band high (system)" in html  # sized from the system, source shown
        assert ">Tasks" in html
    finally:
        on.ctx.settings.controls_enabled = False


def test_unspecified_level_says_initiation_only(on: Console) -> None:
    from .conftest import add_agent

    add_agent(on.runtime.adapters, "newbot", risk_tier="unknown")  # no level to inherit
    sid = _system(on)
    on.ctx.systems.link(sid, "agent", "newbot", REVIEWER)
    on.ctx.settings.controls_enabled = True
    try:
        on.ctx.tasks.generate("newbot", SystemActor())
        assert "Only the initiation tasks are shown" in _tab(on, sid, "tasks").text
    finally:
        on.ctx.settings.controls_enabled = False


@pytest.mark.parametrize("tab", ["tasks", "reviews"])
def test_scope_the_tabs_of_another_team_are_404_like(on: Console, tab: str) -> None:
    secret = _system(on, name="Secret", owner_team="risk-team")
    r = _tab(on, secret, tab, user=OWNER_USER)
    assert r.status_code in (400, 404)
    assert "Secret" not in r.text
    mine = on.ctx.systems.register(
        draft(name="Mine", owner_user=OWNER_USER, owner_team=PAYOPS), OWNER_USER
    )["system_id"]
    assert _tab(on, mine, tab, user=OWNER_USER).status_code == 200


def test_every_new_string_has_english_and_vietnamese() -> None:
    table = i18n.table()
    new = [
        k for k in table if k.startswith(("sy_tab_t", "sy_tab_r", "sy_ap_", "sy_rv_", "sy_tasks_"))
    ]
    new += ["sy_stage_now", "sy_stage_needs_approval"]
    assert len(new) >= 30
    for k in new:
        en, vi = table[k]
        assert en.strip() and vi.strip() and en != vi, k
