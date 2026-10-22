"""WP-G0 console: Systems list, filter bar, drawer, detail page, register form, nav, EN and VI."""

from __future__ import annotations

import re
from typing import Any

import pytest

from supervisor.console import i18n, nav

from .conftest import Console, draft

HX = {"HX-Request": "true"}
OWNER_USER = "payops-lead@example.invalid"


def _sidebar(html: str) -> str:
    return html.split('<aside class="side"', 1)[1].split("</aside>", 1)[0]


def _make(c: Console, user: str = "reviewer.an", **over: Any) -> dict[str, Any]:
    return c.ctx.systems.register(draft(owner_user=user, **over), user)


def test_flags_off_gives_a_400_message_when_the_router_is_there(
    console: Console, mounted: None
) -> None:
    r = console.get("/console/systems")
    assert r.status_code == 400 and "CONSOLE_SYSTEMS_ENABLED" in r.text
    console.ctx.settings.console_systems_enabled = True
    r = console.get("/console/systems")
    assert r.status_code == 400 and "GOVERNANCE_ENABLED" in r.text


def test_nav_item_shows_under_onboard_when_the_page_flag_is_on(on: Console) -> None:
    side = _sidebar(on.get("/console/?lang=en").text)
    assert 'href="/console/systems?lang=en"' in side
    heads = re.findall(r'<h2 class="side-h" id="sg-\d+">([^<]+)</h2>', side)
    onboard = side.split("Onboard</h2>", 1)[1].split("</section>", 1)[0]
    assert "Systems" in onboard and heads[3] == "Onboard"
    on.ctx.settings.console_nav_sections = True
    side = _sidebar(on.get("/console/?lang=en").text)
    assert 'href="/console/systems?lang=en"' in side


def test_list_filter_sort_drawer_and_scope(on: Console) -> None:
    a = _make(on, name="Alpha assistant")
    _make(on, name="Beta decisions", system_type="decision", owner_team="risk-team")
    on.ctx.systems.update_fields(a["system_id"], {"risk_level": "high", "status": "active"}, "x")
    html = on.get("/console/systems").text
    assert "Alpha assistant" in html and "Beta decisions" in html
    assert 'id="register"' in html  # the reviewer may register
    rows = on.get("/console/systems/rows?owner_team=risk-team", headers=HX).text
    assert "Beta decisions" in rows and "Alpha assistant" not in rows
    rows = on.get("/console/systems/rows?risk=high", headers=HX).text
    assert "Alpha assistant" in rows and "Beta decisions" not in rows
    rows = on.get("/console/systems/rows?status=active&q=alp", headers=HX).text
    assert "Alpha assistant" in rows
    for q in ("sort=risk&dir=desc", "sort=name&dir=desc", "sort=bogus", "page=1"):
        assert on.get(f"/console/systems/rows?{q}", headers=HX).status_code == 200, q
    for bad in ("status=zzz", "risk=zzz", "page=9", "page=x", "q=%3Cscript%3E"):
        r = on.get(f"/console/systems/rows?{bad}", headers=HX)
        assert r.status_code == 400 and "msg-error" in r.text, bad
    # drawer and the no-JS fallback
    sid = a["system_id"]
    for tab in ("details", "team", "components"):
        r = on.get(f"/console/systems/{sid}/drawer?tab={tab}", headers=HX)
        assert r.status_code == 200 and "Alpha assistant" in r.text, tab
    assert on.get(f"/console/systems/{sid}/drawer?tab=zzz", headers=HX).status_code == 400
    assert on.get(f"/console/systems?drawer={sid}").status_code == 200
    r = on.get("/console/systems/sys_nope/drawer", headers=HX)
    assert r.status_code == 400 and "does not exist" in r.text
    # a viewer sees nothing of other teams, and a hidden system looks like a missing one
    viewer = on.get("/console/systems", user="viewer.hoa").text
    assert "Alpha assistant" not in viewer and "Beta decisions" not in viewer
    assert 'id="register"' not in viewer
    assert on.get(f"/console/systems/{sid}", user="viewer.hoa").status_code == 400
    assert on.get(f"/console/systems/{sid}/drawer", user="viewer.hoa").status_code == 400
    on.ctx.systems.add_member(sid, "viewer.hoa", "data_steward", "x")
    assert "Alpha assistant" in on.get("/console/systems", user="viewer.hoa").text
    assert on.get(f"/console/systems/{sid}", user="viewer.hoa").status_code == 200
    # the owner role sees its own team's systems only
    mine = _make(on, user=OWNER_USER, name="Owner thing", owner_team="payops-team")
    got = on.get("/console/systems", user=OWNER_USER).text
    assert mine["name"] in got and "Alpha assistant" not in got


def test_detail_page_tabs_and_components(on: Console) -> None:
    sid = _make(on, name="Detail me")["system_id"]
    on.ctx.systems.link(sid, "agent", "payments", "reviewer.an")
    page = on.get(f"/console/systems/{sid}").text
    assert "Detail me" in page and "reviewer.an" in page and "Overview" in page
    comp = on.get(f"/console/systems/{sid}?tab=components").text
    assert "payments" in comp and "Component of" in comp
    part = on.get(f"/console/systems/{sid}?tab=components", headers=HX)
    assert part.status_code == 200
    assert on.get(f"/console/systems/{sid}?tab=zzz").status_code == 400
    assert on.get("/console/systems/sys_nope").status_code == 400
    assert on.get("/console/systems/bad%20id").status_code == 400


def test_register_form_htmx_and_plain(on: Console) -> None:
    form = {
        "name": "From the form",
        "owner_team": "payments-team",
        "purpose": "Tests the form.",
        "system_type": "assistant",
        "org_role": "deployer",
        "user_segment": "internal",
        "personal_data": "none",
        "human_control": "post_review",
        "money_movement": "1",
    }
    r = on.post("/console/systems", form)
    assert r.status_code == 200 and r.headers["HX-Redirect"].startswith("/console/systems/sys_")
    (row,) = on.ctx.state.query("ai_system")
    assert row["name"] == "From the form" and row["owner_user"] == "reviewer.an"
    assert row["status"] == "draft" and row["money_movement"] in (1, True)
    # two audit rows with a system target
    rows = [
        r
        for r in on.ctx.tables.query("console_action", order_by=("ts",))
        if r["permission"] == "systems.edit"
    ]
    assert [r["outcome"] for r in rows] == ["attempted", "ok"]
    assert rows[1]["target_kind"] == "system"
    # a plain browser post needs a same-site Origin and answers with a redirect
    r = on.post("/console/systems", {**form, "name": "Plain"}, htmx=False)
    assert r.status_code == 400
    r = on.post(
        "/console/systems",
        {**form, "name": "Plain"},
        htmx=False,
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"].startswith("/console/systems/sys_")
    # bad input and a duplicate are 400 with a message; a viewer is 403
    bad = on.post("/console/systems", {**form, "name": "Third", "system_type": "robot"})
    assert bad.status_code == 400 and "msg-error" in bad.text and "system_type" in bad.text
    dup = on.post("/console/systems", form)
    assert dup.status_code == 400 and "already" in dup.text
    assert on.post("/console/systems", {**form, "name": "V"}, user="viewer.hoa").status_code == 403
    # a scoped owner cannot register for somebody else
    r = on.post("/console/systems", {**form, "name": "Owned", "owner_user": "x.y"}, user=OWNER_USER)
    assert r.status_code == 200
    assert (
        on.ctx.state.get("ai_system", {"system_id": r.headers["HX-Redirect"].rsplit("/", 1)[1]})[
            "owner_user"
        ]
        == OWNER_USER
    )


def test_vi_and_en_strings_exist_for_every_key_used() -> None:
    table = i18n.table()
    keys = [k for k in table if k.startswith("sy_") or k == "nav_systems"]
    assert len(keys) > 80
    for k in keys:
        en, vi = table[k]
        assert en and vi and en != vi or k in ("sy_ref_agent",), k
    # every enum value has a label in both languages
    from supervisor.governance import model as gm

    for prefix, values in [
        ("sy_st_", gm.STATUSES),
        ("sy_stage_", gm.LIFECYCLE_STAGES),
        ("sy_risk_", gm.RISK_LEVELS),
        ("sy_system_type_", gm.SYSTEM_TYPES),
        ("sy_org_role_", gm.ORG_ROLES),
        ("sy_user_segment_", gm.USER_SEGMENTS),
        ("sy_personal_data_", gm.PERSONAL_DATA),
        ("sy_human_control_", gm.HUMAN_CONTROLS),
        ("sy_d33_", gm.DECISION33_CLASSES),
        ("sy_impact_", gm.BUSINESS_IMPACTS),
        ("sy_role_", gm.TEAM_ROLES),
        ("sy_ref_", gm.REF_KINDS),
        ("sy_link_", gm.LINK_ROLES),
        ("sy_source_", gm.RISK_SOURCES),
    ]:
        for v in values:
            assert prefix + v in table, prefix + v


def test_vi_page_renders_vietnamese(on: Console) -> None:
    _make(on, name="Hệ thống thử")
    html = on.get("/console/systems?lang=vi").text
    assert "Hệ thống AI" in html and "Nhóm sở hữu" in html
    assert "Systems" not in _sidebar(html).split("Tiếp nhận")[1].split("</section>")[0]


def test_nav_structure_places_systems_in_the_governance_section() -> None:
    placed = [k for _, _, gs in nav.SECTIONS for _, keys in gs for k in keys]
    assert placed.count("systems") == 1
    assert nav.CODES["systems"] == "SY" and len(set(nav.CODES.values())) == len(nav.CODES)


@pytest.mark.parametrize("lang", ["en", "vi"])
def test_pages_are_html_200_for_every_role(on: Console, lang: str) -> None:
    sid = _make(on, name="For roles")["system_id"]
    for user in ("reviewer.an", "admin.chi", "auditor.dung", "approver.em"):
        for url in ("/console/systems", f"/console/systems/{sid}", "/console/systems/rows"):
            r = on.get(f"{url}{'&' if '?' in url else '?'}lang={lang}", user=user)
            assert r.status_code == 200, (user, url)
