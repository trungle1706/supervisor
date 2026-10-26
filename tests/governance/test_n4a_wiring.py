"""WP-N4a: wiring fixes after the UX test of the merged phase 7 packages (Register links, candidate
leaves the list, Save for later, blank draft, guardian reason, single escape, live pending)."""

# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
from __future__ import annotations

import re
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from supervisor.app import app
from supervisor.console import my_agents, overview_v4
from supervisor.governance import next_action
from supervisor.governance.register_v2 import links
from supervisor.governance.register_v2 import service as rs

from .conftest import Console, draft, on, restore_app  # noqa: F401
from .test_n1_overview import fill
from .test_n1_triage import golden_graph
from .test_n3_register import ME, S1, S2, _me, new, rows, step

# ------------------------------------------------------------------ H5 links


@pytest.mark.parametrize("flag", [True, False])
def test_link_helpers_follow_the_flag(flag: bool) -> None:
    s = SimpleNamespace(
        console_register_v2=flag, governance_enabled=True, console_systems_enabled=True
    )
    base = "/console/register/new" if flag else "/console/systems/new"
    assert links.candidate_href(s, "inv_a b&c") == f"{base}?from=inv_a%20b%26c"
    assert links.agent_href(s, "a/b") == f"{base}?agent=a%2Fb"


@pytest.mark.parametrize("flag", [True, False])
def test_next_action_register_hrefs(flag: bool) -> None:
    s = SimpleNamespace(
        console_register_v2=flag, governance_enabled=True, console_systems_enabled=True
    )
    ctx = SimpleNamespace(settings=s)
    cand = next_action.recommended_action(
        ctx, {"agent_id": "n", "kind": "candidate", "node_id": "inv_x"}, None, {}
    )
    pol = next_action.recommended_action(ctx, {"agent_id": "g1", "kind": "policy_only"}, None, {})
    if flag:
        assert cand["href"] == "/console/register/new?from=inv_x"
        assert pol["href"] == "/console/register/new?agent=g1"
    else:
        assert cand["href"] == "/console/systems/new?from=inv_x"
        assert pol["href"] == "/console/agents/g1?tab=register"


FLAGS = (
    "console_nav_v3",
    "console_overview_v4",
    "inventory_enabled",
    "controls_enabled",
    "console_my_agents",
)


@pytest.fixture
def v4(on: Console, monkeypatch: pytest.MonkeyPatch) -> Iterator[Console]:
    from supervisor.console.candidates_routes import api_router, router

    for f in FLAGS:
        monkeypatch.setattr(on.ctx.settings, f, True)
    saved = list(app.router.routes)
    lifespan = app.router.lifespan_context
    app.include_router(router)
    app.include_router(api_router)
    fill(on, golden_graph())
    try:
        yield on
    finally:
        restore_app(app, saved, lifespan)


def first_node(c: Console) -> str:
    return str((overview_v4.load_candidates(c.ctx) or [])[0]["node_id"])


def candidate_ids(c: Console) -> set[str]:
    return {r["node_id"] for r in overview_v4.load_candidates(c.ctx) or []}


@pytest.mark.parametrize("flag", [True, False])
def test_candidate_pages_register_links(
    v4: Console, monkeypatch: pytest.MonkeyPatch, flag: bool
) -> None:
    for f in ("console_register_v2", "agents_api_enabled"):
        monkeypatch.setattr(v4.ctx.settings, f, flag)
    base = "/console/register/new" if flag else "/console/systems/new"
    other = "/console/systems/new" if flag else "/console/register/new"
    node = first_node(v4)
    for url in (
        "/console/candidates?lang=en",
        "/console/?lang=en",
        f"/console/candidates/{node}/drawer?lang=en",
        f"/console/candidates?drawer={node}&lang=en",
        "/console/my/agents?scope=all&lang=en",
    ):
        html = v4.get(url).text
        assert f'href="{base}?from=' in html, url
        assert f'href="{other}?from=' not in html, url


# ------------------------------------------------------------------ H5b


def test_candidate_leaves_after_v2_submit(v4: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    for f in ("console_register_v2", "agents_api_enabled"):
        monkeypatch.setattr(v4.ctx.settings, f, True)
    node = first_node(v4)
    did = new(v4, f"?from={node}")
    for n, form in ((1, {**S1, "name": "N4a from scan"}), (2, S2), (3, {}), (4, {})):
        assert step(v4, did, n, form).status_code == 200
    assert step(v4, did, 5, {"bind_form": "1"}).status_code == 200
    assert v4.post(f"/console/register/{did}/submit", {}, user=ME).status_code == 200
    assert node not in candidate_ids(v4)
    assert f'data-row="{node}"' not in v4.get("/console/my/agents?scope=all&lang=en").text


def test_inactive_component_still_hides_the_candidate(v4: Console) -> None:
    node = first_node(v4)
    sysrow = v4.ctx.systems.register(draft(name="Gamma", owner_user="reviewer.an"), "reviewer.an")
    v4.ctx.systems.link(sysrow["system_id"], "node", node, "reviewer.an")
    comp = rows(v4, "system_component", ref_id=node)[0]
    v4.ctx.systems.unlink(sysrow["system_id"], comp["component_id"], "reviewer.an")
    assert rows(v4, "system_component", ref_id=node)
    assert node not in candidate_ids(v4)


def test_old_wizard_links_the_scanned_node(v4: Console) -> None:
    node = first_node(v4)
    page = v4.get(f"/console/systems/new?from={node}&lang=en")
    assert page.status_code == 200 and f'name="from_node" value="{node}"' in page.text
    form = {
        "name": "Old wizard sys",
        "owner_team": "payments-team",
        "owner_user": ME,
        "purpose": "Synthetic helper app.",
        "system_type": "assistant",
        "org_role": "deployer",
        "user_segment": "internal",
        "personal_data": "pseudonymised",
        "human_control": "post_review",
        "from_node": node,
    }
    checks = v4.post("/console/systems/new/checks", form, user=ME)
    assert checks.status_code == 200 and f'name="from_node" value="{node}"' in checks.text
    r = v4.post("/console/systems/new", form, user=ME)
    assert r.status_code == 200, r.text[:300]
    assert [c["ref_kind"] for c in rows(v4, "system_component", ref_id=node)] == ["node"]
    assert node not in candidate_ids(v4)


# ------------------------------------------------------------------ H8, M2, M6


def test_save_for_later_keeps_typed_values(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(on.ctx.settings, "console_register_v2", True)
    did = new(on)
    assert step(on, did, 1, S1).status_code == 200
    r = step(on, did, 2, {"purpose": "Typed purpose for later."}, save=True)
    assert r.status_code == 200 and r.headers["HX-Redirect"].startswith("/console/register?saved=1")
    assert "Saved" in on.get("/console/register?saved=1&lang=en").text
    assert "Saved" not in on.get("/console/register?lang=en").text
    page = on.get(f"/console/register/{did}/step/2?lang=en").text
    assert "Typed purpose for later." in page
    assert "formnovalidate" in page


def test_blank_start_keeps_one_empty_draft(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(on.ctx.settings, "console_register_v2", True)
    store = rs.store_of(on.ctx)
    first = new(on)
    second = new(on)
    third = new(on)
    assert [d["draft_id"] for d in store.list_mine(ME)] == [third]
    assert len({first, second, third}) == 3
    # a draft with a typed value stays when a new blank draft starts
    assert step(on, third, 1, {"name": "Kept"}, save=True).status_code == 200
    fourth = new(on)
    assert {d["draft_id"] for d in store.list_mine(ME)} == {third, fourth}


def test_guardian_reason_reaches_the_binding(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    for flag in (
        "console_register_v2",
        "agents_api_enabled",
        "guardian_bindings_enabled",
        "detectors_enabled",
    ):
        monkeypatch.setattr(on.ctx.settings, flag, True)
    did = new(on)
    assert step(on, did, 1, S1).status_code == 200
    assert step(on, did, 2, S2).status_code == 200
    view = rs.guardian_view(on.ctx, _me(), rs.store_of(on.ctx).get(did, ME))
    free = [r for r in view["rows"] if r["bindable"]]
    assert free
    slug = free[0]["slug"]
    html = on.get(f"/console/register/{did}/step/5?lang=en").text
    assert f'name="why_{slug}"' in html
    form = {
        "bind_form": "1",
        f"why_{slug}": "Not needed for this app.",
        **{f"on_{r['slug']}": "1" for r in free[1:]},
    }
    assert step(on, did, 5, form).status_code == 200
    assert step(on, did, 3).status_code == 200 and step(on, did, 4).status_code == 200
    assert on.post(f"/console/register/{did}/submit", {}, user=ME).status_code == 200
    sid = rows(on, "ai_system", name="N3 helper")[0]["system_id"]
    b = rows(on, "guardian_binding", system_id=sid)
    assert [(x["feature_slug"], x["state"], x["reason"]) for x in b] == [
        (slug, "off", "Not needed for this app.")
    ]


# ------------------------------------------------------------------ M17, M18


def test_my_agents_links_are_escaped_once(v4: Console) -> None:
    html = v4.get("/console/my/agents?scope=all&lang=en").text
    assert "&amp;amp;" not in html
    assert re.search(r'href="/console/agents/[^"]+\?tab=register&amp;lang=en"', html)


def test_pending_resume_clears_after_two_approvals(v4: Console) -> None:
    states = v4.ctx.gateway.states
    doc = states.policy.current().doc
    owner = doc.agents["payments"].owner_user
    reviewer = sorted(doc.reviewers)[0]
    states.pause("payments", reviewer, "test")
    states.resume("payments", owner, "first")

    def row() -> dict:
        got = my_agents.build_rows(v4.ctx, _me(), "all")[1]
        return next(r for r in got if r["agent_id"] == "payments")

    assert len(row()["pending"]) == 1
    assert "1 resume approval" in v4.get("/console/my/agents?scope=all&lang=en").text
    states.resume("payments", reviewer, "second")
    assert row()["pending"] == [] and row()["state"] != "PAUSED"
    assert "resume approval" not in v4.get("/console/my/agents?scope=all&lang=en").text
