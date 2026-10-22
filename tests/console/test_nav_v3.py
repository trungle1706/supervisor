"""WP-UX4a: merged sidebar (CONSOLE_NAV_V3) and the Supervisor-side pages. Off path first."""

from __future__ import annotations

import html as htmllib
import re

import pytest

from supervisor.console import i18n

from .conftest import Console

NEW_ROUTES = (
    "/console/governance",
    "/console/supervisor",
    "/console/activity",
    "/console/guardians",
    "/console/catalogues",
    "/console/risks-controls",
    "/console/workflows",
)


def _sidebar(html: str) -> str:
    return html.split('<aside class="side"', 1)[1].split("</aside>", 1)[0]


def _main(html: str) -> str:
    return html.split('id="main"', 1)[1].split("</main>", 1)[0]


# ------------------------------------------------------------------ off path (first)


def test_flag_is_off_by_default(console: Console) -> None:
    assert console.ctx.settings.console_nav_v3 is False


def test_off_keeps_the_six_group_sidebar(console: Console) -> None:
    side = _sidebar(console.get("/console/?lang=en").text)
    heads = re.findall(r'<h2 class="side-h" id="sg-\d+">([^<]+)</h2>', side)
    assert heads == ["Watch", "Act", "Prove", "Onboard", "Analytics", "Settings"]
    assert "side-v3" not in side and "data-nav-v3" not in side and "nav-gear" not in side


def test_off_keeps_the_sections_sidebar(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_nav_sections", True)
    side = _sidebar(console.get("/console/?lang=en").text)
    assert side.count('<details class="side-sec" open>') == 2
    assert "side-v3" not in side


def test_off_overview_is_the_old_one(console: Console) -> None:
    html = console.get("/console/?lang=en").text
    assert 'id="numbers"' in html and 'data-page="my-overview"' not in html


@pytest.mark.parametrize("path", NEW_ROUTES)
def test_off_new_routes_answer_400_with_a_message(console: Console, path: str) -> None:
    r = console.get(path)
    assert r.status_code == 400 and "CONSOLE_NAV_V3=1" in r.text


@pytest.mark.parametrize(
    "path", ["/console/agents", "/console/cases", "/console/evidence", "/console/analytics"]
)
def test_off_pages_carry_no_tab_strip(console: Console, path: str) -> None:
    assert "sec-tabs" not in console.get(path).text


def test_off_old_urls_do_not_redirect(console: Console) -> None:
    for path in ("/console/inbox", "/console/signoff", "/console/evidence", "/console/agents"):
        assert console.get(path, follow_redirects=False).status_code == 200


def test_keys_exist_in_both_languages() -> None:
    table = i18n.table()
    for key in [k for k in table if k.startswith("nv3_")]:
        assert all(table[key]), key


# ------------------------------------------------------------------ on path

UX3_FLAGS = (
    "console_decisions_enabled",
    "console_traces_enabled",
    "console_policies_enabled",
    "console_credentials_enabled",
    "console_users_enabled",
    "console_auditlog_enabled",
    "console_integrations_enabled",
    "console_playground_enabled",
    "console_risks_enabled",
    "console_controls_enabled",
    "console_transparency_enabled",
    "console_catalog_enabled",
    "console_assurance_enabled",
    "console_compliance_enabled",
    "console_integration_enabled",
    "inventory_enabled",
    "risk_register_enabled",
    "controls_enabled",
    "transparency_enabled",
)
BIGNUM = r'data-num="{key}">\s*<h3>[^<]+</h3>\s*<div class="bignum"[^>]*>(\d+)'


def _v3_side(html: str) -> str:
    return html.split('<aside class="side side-v3"', 1)[1].split("</aside>", 1)[0]


def _labels(side: str) -> list[str]:
    pat = r'<span class="ni3" aria-hidden="true"><svg.*?</svg></span><span class="nl">([^<]+)'
    return [htmllib.unescape(x).strip() for x in re.findall(pat, side)]


@pytest.fixture
def v3(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(console.ctx.settings, "console_nav_v3", True)
    return console


@pytest.fixture
def v3all(v3: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    for flag in UX3_FLAGS:
        monkeypatch.setattr(v3.ctx.settings, flag, True)
    for flag in ("console_systems_enabled", "governance_enabled"):
        monkeypatch.setattr(v3.ctx.settings, flag, True)
    return v3


def test_bar_has_one_plus_five_plus_six_items(v3all: Console) -> None:
    side = _v3_side(v3all.get("/console/?lang=en").text)
    assert _labels(side) == [
        "My overview",
        "Overview", "Systems", "Catalogues", "Risks & controls", "Workflows",
        "Overview", "Activity", "Guardians", "Cases & alerts", "Analytics", "Playground",
    ]  # fmt: skip
    kickers = re.findall(r'<span class="side-k">([^<]+)</span><span class="side-t">([^<]+)<', side)
    assert kickers == [("Governance", "AI management"), ("Supervisor", "AI guardian")]
    assert side.count("<svg") == 13  # 12 items and the gear
    assert 'stroke-width="1.8"' in side and 'width="18"' in side
    assert re.search(r'href="/console/\?lang=en" class="active"', side)
    assert 'id="nav-gear"' in v3all.get("/console/").text and "gear-btn" in side


def test_bar_in_vietnamese(v3all: Console) -> None:
    side = _v3_side(v3all.get("/console/?lang=vi").text)
    assert _labels(side)[0] == "Tổng quan của tôi"
    assert "Quản lý AI" in side and "Giám sát AI" in side


def test_items_hide_when_the_page_flag_is_off(v3: Console) -> None:
    labels = _labels(_v3_side(v3.get("/console/?lang=en").text))
    assert "Playground" not in labels and "Risks & controls" not in labels
    assert "Activity" not in labels
    assert {"Catalogues", "Guardians", "Cases & alerts", "Analytics"} <= set(labels)


def test_items_hide_when_the_role_lacks_the_permission(v3all: Console) -> None:
    viewer = v3all.get("/console/?lang=en", user="viewer.hoa").text
    assert "Playground" not in _labels(_v3_side(viewer))  # playground.run: not a viewer grant
    admin_gear = v3all.get("/console/?lang=en", user="admin.chi").text.split('id="nav-gear"')[1]
    viewer_gear = viewer.split('id="nav-gear"')[1]
    assert "/console/users" in admin_gear and "/console/audit" in admin_gear
    assert "/console/users" not in viewer_gear and "/console/audit" not in viewer_gear
    assert "/console/health" in viewer_gear  # health.view is for every role


def test_gear_lists_the_six_settings_items(v3all: Console) -> None:
    gear = v3all.get("/console/?lang=en", user="admin.chi").text.split('id="nav-gear"')[1]
    for path in ("integrations", "credentials", "users", "audit", "health", "policies"):
        assert f"/console/{path}?lang=en" in gear, path


@pytest.mark.parametrize("lang", ["en", "vi"])
@pytest.mark.parametrize(
    "path",
    [
        "/console/",
        "/console/governance",
        "/console/supervisor",
        "/console/workflows",
        "/console/catalogues?tab=models",
        "/console/catalogues?tab=tools",
        "/console/catalogues?tab=datasets",
        "/console/catalogues?tab=mcp",
        "/console/guardians?tab=detectors",
        "/console/guardians?tab=judges",
        "/console/guardians?tab=monitors",
    ],
)
def test_each_new_page_renders(v3all: Console, path: str, lang: str) -> None:
    sep = "&" if "?" in path else "?"
    r = v3all.get(f"{path}{sep}lang={lang}")
    assert r.status_code == 200, r.text[:300]
    assert "side-v3" in r.text


@pytest.mark.parametrize(
    ("path", "target"),
    [
        ("/console/activity", "/console/decisions"),
        ("/console/risks-controls", "/console/risks"),
        ("/console/catalogues", "/console/agents"),
        ("/console/catalogues?tab=unmanaged", "/console/inventory"),
        ("/console/guardians", "/console/catalog"),
        ("/console/guardians?tab=packs", "/console/assurance"),
        ("/console/risks-controls?tab=policies", "/console/compliance"),
        ("/console/activity?tab=traces", "/console/traces"),
    ],
)
def test_section_routes_redirect_to_the_tab_page(v3all: Console, path: str, target: str) -> None:
    sep = "&" if "?" in path else "?"
    r = v3all.get(f"{path}{sep}lang=vi", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"{target}?lang=vi"
    assert v3all.get(path).status_code == 200  # followed to the page


@pytest.mark.parametrize(
    "path",
    [
        "/console/activity?tab=nope",
        "/console/guardians?tab=nope",
        "/console/catalogues?tab=nope",
        "/console/risks-controls?tab=nope",
        "/console/governance?scope=nope",
        "/console/supervisor?scope=nope",
        "/console/?scope=nope",
    ],
)
def test_bad_tab_or_scope_is_400_with_a_message(v3all: Console, path: str) -> None:
    r = v3all.get(path)
    assert r.status_code == 400 and ("tab" in r.text or "scope" in r.text)


def test_a_tab_that_is_off_is_400(v3: Console) -> None:
    r = v3.get("/console/activity?tab=decisions")
    assert r.status_code == 400 and "off" in r.text
    r = v3.get("/console/activity")
    assert r.status_code == 400 and "No page of this section is on" in r.text
    assert v3.get("/console/catalogues?tab=models").status_code == 400  # inventory is off


def test_old_urls_keep_working_with_v3_on(v3all: Console) -> None:
    for path in (
        "/console/inbox", "/console/signoff", "/console/evidence", "/console/agents",
        "/console/cases", "/console/alerts", "/console/analytics", "/console/catalog",
        "/console/policies", "/console/decisions", "/console/traces", "/console/risks",
        "/console/controls", "/console/compliance", "/console/onboard", "/console/inventory",
        "/console/health", "/console/playground",
    ):  # fmt: skip
        assert v3all.get(path, follow_redirects=False).status_code == 200, path


@pytest.mark.parametrize(
    ("path", "section", "tab"),
    [
        ("/console/cases", "Cases & alerts", "Cases"),
        ("/console/alerts", "Cases & alerts", "Alerts"),
        ("/console/signoff", "Cases & alerts", "Approvals"),
        ("/console/evidence", "Analytics", "Evidence chain"),
        ("/console/analytics", "Analytics", "Analytics"),
        ("/console/agents", "Catalogues", "Agents"),
        ("/console/inventory", "Catalogues", "Unmanaged"),
        ("/console/decisions", "Activity", "Gate decisions"),
        ("/console/catalog", "Guardians", "Library"),
        ("/console/policies", "Guardians", "Rules"),
        ("/console/assurance", "Guardians", "Packs"),
        ("/console/risks", "Risks & controls", "Risks"),
        ("/console/compliance", "Risks & controls", "Policies"),
        ("/console/onboard", "Systems", "Onboard"),
    ],
)
def test_section_tab_strip_marks_the_open_tab(
    v3all: Console, path: str, section: str, tab: str
) -> None:
    html = v3all.get(path + "?lang=en").text
    strip = html.split('<nav class="subtabs sec-tabs"', 1)[1].split("</nav>", 1)[0]
    assert f'<span class="sec-tabs-t">{section}</span>' in htmllib.unescape(strip)
    assert re.findall(r'class="on" aria-current="page">([^<]+)<', strip) == [tab]
    assert strip.count("<a ") >= 2


def test_analytics_strip_has_the_evidence_tab(v3all: Console) -> None:
    html = v3all.get("/console/analytics?lang=en").text
    assert "/console/evidence?lang=en" in html.split("sec-tabs", 1)[1]


def test_pages_without_a_section_have_no_strip(v3all: Console) -> None:
    for path in ("/console/", "/console/governance", "/console/supervisor", "/console/health"):
        assert (
            "subtabs sec-tabs"
            not in v3all.get(path).text.split('id="main"', 1)[1].split("</main>")[0]
        ), path


# ------------------------------------------------------------------ numbers


def test_my_overview_numbers_are_integers_from_existing_services(v3all: Console) -> None:
    main = _main(v3all.get("/console/?lang=en").text)
    agents = v3all.ctx.state.query("agent")
    m = re.search(BIGNUM.format(key="agents"), main)
    assert m and int(m.group(1)) == len(agents)  # a non-owner defaults to scope all
    for key in ("models", "cover", "actions"):
        assert f'data-num="{key}"' in main
    for big in re.findall(r'<div class="bignum"[^>]*>(.*?)</div>', main, re.S):
        text = re.sub(r"<[^>]+>", "", big).strip()
        assert re.fullmatch(r"\d+\+?|\d+ / \d+|\d+%|not available", text), text


def test_my_overview_scope_my_shows_only_owned_agents(v3all: Console) -> None:
    agents = v3all.ctx.state.query("agent")
    owner = sorted({a["owner_user"] for a in agents})[0]
    mine = [a for a in agents if a["owner_user"] == owner]
    html = v3all.get("/console/?scope=my&lang=en", user=owner).text
    m = re.search(BIGNUM.format(key="agents"), html)
    assert m and int(m.group(1)) == len(mine)
    assert 'aria-current="true">Mine<' in html
    team = v3all.get("/console/?scope=team&lang=en", user=owner).text
    assert 'aria-current="true">My team<' in team


def test_open_actions_count_assigned_cases_and_match_the_badge(v3all: Console) -> None:
    v3all.get("/console/")  # case intake
    case = v3all.ctx.cases.list_cases()[0]
    me = v3all.ctx.provider.users["reviewer.an"]
    v3all.ctx.cases.assign(case["case_id"], "reviewer.an", me, case["row_version"])
    html = v3all.get("/console/?lang=en").text
    tile = re.search(BIGNUM.format(key="actions"), html)
    badge = re.search(r'My overview <span class="k (?:hot)?">(\d+)</span>', _v3_side(html))
    assert tile and int(tile.group(1)) >= 1
    assert badge and int(badge.group(1)) == int(tile.group(1))
    assert f"/console/cases/{case['case_id']}" in html


def test_governance_na_when_controls_and_risks_are_off(v3: Console) -> None:
    html = v3.get("/console/governance?lang=en").text
    assert html.count("not available") >= 3
    assert "CONTROLS_ENABLED=1" in html and "RISK_REGISTER_ENABLED=1" in html
    assert "<h3>Control readiness</h3>" in html


def test_governance_numbers_with_controls_on(
    v3all: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.conftest import REPO_ROOT

    s = v3all.ctx.settings
    for flag in ("controls_enabled", "risk_register_enabled"):
        monkeypatch.setattr(s, flag, True)
    risks = v3all.ctx.risks.import_path(REPO_ROOT / "config" / "risks", "t", source="starter")
    assert risks.errors == []
    ctl = v3all.ctx.controls.import_path(REPO_ROOT / "config" / "controls", "t", source="starter")
    assert ctl.errors == []
    v3all.ctx.controls.run_status()
    html = v3all.get("/console/governance?scope=all&lang=en").text
    m = re.search(
        r'data-num="readiness">.*?<div class="bignum" title="(\d+) bp">(\d+)%</div>', html, re.S
    )
    assert m and int(m.group(2)) == int(m.group(1)) // 100 and 0 <= int(m.group(1)) <= 10000
    assert v3all.ctx.tables.query("control_status", None, limit=10)
    assert re.search(BIGNUM.format(key="overdue"), html)


def test_supervisor_overview_counts_the_last_24_hours(v3all: Console) -> None:
    import datetime as dt

    main = _main(v3all.get("/console/supervisor?scope=all&lang=en").text)
    m = re.search(BIGNUM.format(key="checked"), main)
    assert m
    events = v3all.ctx.tables.query("agent_event", {"event_type": "gate_decision"}, limit=20000)
    since = v3all.ctx.clock.now() - dt.timedelta(hours=24)
    assert int(m.group(1)) == sum(1 for e in events if e["ts"] >= since)
    assert 'data-num="stopped"' in main and 'data-num="cases"' in main
    assert "Health per agent" in main and "Alerts fired 7 d" in main


def test_judges_without_a_model_are_labelled_mock(
    v3all: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = v3all.ctx.settings
    monkeypatch.setattr(s, "judge_enabled", True)
    monkeypatch.setattr(s, "judge_t1_model", "")
    mock = '<span class="pill warn">mock</span>'
    assert mock in v3all.get("/console/supervisor?scope=all").text
    monkeypatch.setattr(s, "judge_enabled", False)
    assert mock not in v3all.get("/console/supervisor?scope=all").text


def test_guardian_coverage_follows_the_detector_file(
    v3all: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = v3all.ctx.settings
    monkeypatch.setattr(s, "detectors_enabled", False)
    off = v3all.get("/console/supervisor?scope=all&lang=en").text
    assert "DETECTORS_ENABLED=1" in off and "below floor" in off
    monkeypatch.setattr(s, "detectors_enabled", True)
    on = v3all.get("/console/supervisor?scope=all&lang=en").text
    n = len(v3all.ctx.state.query("agent"))
    assert re.search(rf'data-num="cover">.*?<div class="bignum">{n} / {n}</div>', on, re.S)


def test_workflows_is_read_only_and_honest_without_a_scheduler(v3all: Console) -> None:
    main = _main(v3all.get("/console/workflows?lang=en").text)
    assert "<form" not in main and "<button" not in main
    assert "not running in this process" in main
    assert "Case sign-off" in main and "SIEM export" in main


def test_catalogue_asset_tabs_read_inventory_nodes(v3all: Console) -> None:
    from supervisor.inventory.service import InventoryService

    InventoryService.from_adapters(v3all.runtime.adapters).fill_manifests()
    nodes = [n for n in v3all.ctx.state.query("inventory_node", {"kind": "tool"})]
    html = v3all.get("/console/catalogues?tab=tools&lang=en").text
    live = [n for n in nodes if n["status"] != "gone"]
    assert live and html.count("<td><code>tool</code></td>") == len(live)


def test_localstorage_is_always_inside_try() -> None:
    from pathlib import Path

    js = (Path(i18n.__file__).parent / "static" / "console.js").read_text(encoding="utf-8")
    block = js.split("CONSOLE_NAV_V3", 1)[1].split("document.addEventListener", 3)[0]
    hits = [m.start() for m in re.finditer("localStorage", block)]
    assert hits
    for at in hits:
        assert "try {" in block[max(0, at - 160) : at], block[at - 80 : at + 40]


def test_no_cdn_and_no_script_in_the_new_templates() -> None:
    from pathlib import Path

    root = Path(i18n.__file__).parent / "templates"
    for name in ("_c_sidebar_v3.html", "_icons.html", "_c_section_tabs.html", "_v3.html"):
        text = (root / name).read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text and "<script" not in text, name


def test_dynamic_keys_exist() -> None:
    known = set(i18n.keys())
    dynamic = (
        [f"nv3_scope_{s}" for s in ("my", "team", "all")]
        + [f"nv3_kind_{s}" for s in ("case", "approval", "task")]
        + [f"nv3_kind_wf_{s}" for s in ("job", "alert", "approval", "sink")]
        + [f"nv3_wf_{s}" for s in ("signoff", "resume", "waive", "siem", "webhook")]
        + [f"nv3_t_{s}" for s in ("models", "tools", "datasets", "mcp")]
        + [f"nv3_t_{s}" for s in ("detectors", "judges", "monitors")]
        + [f"nv3_g_lede_{s}" for s in ("detectors", "judges", "monitors")]
        + [f"nv3_st_{k}_{v}" for k in ("collectors", "ingress", "audit") for v in ("on", "off")]
    )
    assert [k for k in dynamic if k not in known] == []


def test_systems_item_follows_the_systems_page_rules(v3all: Console) -> None:
    from supervisor.console import nav_v3

    kw = {"compliance": True, "integration": True, "lang": "en", "actions_n": 0}

    def keys(b: dict) -> list[str]:
        return [i["key"] for g in b["groups"] for i in g["items"]]

    off = {"pages": {"systems": False}, "inventory_n": 0, "assurance": True}
    on = {"pages": {"systems": True}, "inventory_n": 0, "assurance": True}
    assert "systems" not in keys(nav_v3.bar(off, {"reviewer"}, active="", **kw))
    assert "systems" not in keys(nav_v3.bar(on, set(), active="", **kw))  # no systems.view
    shown = nav_v3.bar(on, {"reviewer"}, active=nav_v3.active_item("systems"), **kw)
    row = [i for g in shown["groups"] for i in g["items"] if i["key"] == "systems"]
    assert row and row[0]["active"] and row[0]["href"] == "/console/systems?lang=en"
    # the strip: Systems first, then the pages that moved under it; none without the page
    strip = nav_v3.tab_strip(
        "onboard", on, {"reviewer"}, lang="en", **{k: kw[k] for k in ("compliance", "integration")}
    )
    assert strip and [t["key"] for t in strip["tabs"]][:2] == ["systems", "onboard"]
    assert (
        nav_v3.tab_strip("onboard", off, {"reviewer"}, lang="en", compliance=True, integration=True)
        is None
    )


def test_systems_page_flags_drive_the_bar(v3all: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    s = v3all.ctx.settings
    monkeypatch.setattr(s, "console_systems_enabled", True)
    monkeypatch.setattr(s, "governance_enabled", False)  # G0 rule: both flags are needed
    assert "Systems" not in _labels(_v3_side(v3all.get("/console/?lang=en").text))
    assert "subtabs sec-tabs" not in v3all.get("/console/onboard").text
    monkeypatch.setattr(s, "governance_enabled", True)
    assert "Systems" in _labels(_v3_side(v3all.get("/console/?lang=en").text))
    assert "subtabs sec-tabs" in v3all.get("/console/onboard").text


def test_guardian_coverage_ignores_a_fail_closed_that_is_not_approved(
    v3all: Console, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from supervisor.console import overview_v3

    conf = tmp_path / "det.yaml"
    conf.write_text(
        "version: 1\ndetectors:\n"
        "  dlp_vn: {enabled: true, fail_closed: true}\n"
        "  injection_classifier: {enabled: true, fail_closed: true}\n"
        "  judge_advisory: {enabled: true, fail_closed: true}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(v3all.ctx.settings, "detectors_config", conf)
    slugs, na = overview_v3.mandatory_detectors(v3all.ctx)
    # the classifier has no named approval and the judge is advisory: the gate ignores both
    assert slugs == ["dlp_vn"] and na == ""


def test_workflow_and_catalogue_words_are_translated(v3all: Console) -> None:
    html = v3all.get("/console/workflows?lang=vi").text
    assert "Bộ lập lịch" in html and "tác vụ định kỳ" in html and ">scheduler job<" not in html
    assert ">on<" not in html.split("<tbody>")[1]
