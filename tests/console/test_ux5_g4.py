"""UX5-G4: agent page (primary tabs + More), catalogues, inventory, tools, credentials,
integrations, users, audit log, schema head. Every page is checked with CONSOLE_UX5 on; the old
look (flag off) is proved by the existing page tests, plus one off-path check here."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from supervisor.collectors import catalog  # noqa: F401  (catalogue import keeps the flag graph whole)
from supervisor.console import agent_detail, i18n, i18n_ux5_g4, nav, ux5_g4

from .conftest import Console

FLAGS = (
    "console_tools_enabled",
    "tool_analytics_enabled",
    "inventory_enabled",
    "console_assurance_enabled",
    "console_compliance_enabled",
    "console_risks_enabled",
    "console_controls_enabled",
    "risk_register_enabled",
    "console_transparency_enabled",
    "transparency_enabled",
    "console_my_agents",
    "onboard_intake",
    "onboard_facts",
    "onboard_predeploy",
    "onboard_attach_view",
    "onboard_postdeploy",
)
AGENT = "payments"


@pytest.fixture
def ux(console: Console, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Console:
    for flag in FLAGS:
        monkeypatch.setattr(console.ctx.settings, flag, True)
    for flag in nav.PAGES.values():
        monkeypatch.setattr(console.ctx.settings, flag, True)
    monkeypatch.setattr(console.ctx.settings, "console_ux5", True)
    monkeypatch.setattr(console.ctx.settings, "collectors_enabled", True)
    monkeypatch.setattr(console.ctx.settings, "console_nav_v3", True)
    monkeypatch.setattr(console.ctx.settings, "ingress_keys_file", tmp_path / "agent_keys.yaml")
    return console


# ---------------------------------------------------------------- agent page
def test_agent_page_has_primary_tabs_and_a_more_menu(ux: Console) -> None:
    html = ux.get(f"/console/agents/{AGENT}").text
    assert 'class="g4-tabs"' in html and 'role="tab"' not in html
    assert html.count('class="g4-more') == 1
    nav_html = html.split('class="g4-tabs"', 1)[1].split("</nav>", 1)[0]
    primary = re.findall(r'<a href="[^"]*\?tab=([a-z]+)&', nav_html.split("<details", 1)[0])
    assert primary == ["overview", "register", "guardians", "policy", "tools", "cases"]
    for hidden in ("attach", "postdeploy", "source", "facts", "predeploy", "inventory"):
        assert f"?tab={hidden}&" in nav_html  # reachable inside More
    assert "MOCK" not in html and "g4-id" in html
    assert html.count('class="g4-id"') == 1  # the id once, small, beside the name


def test_every_tab_renders_under_ux5(ux: Console) -> None:
    for tab in agent_detail.TABS:
        page = ux.get(f"/console/agents/{AGENT}?tab={tab}")
        assert page.status_code == 200, (tab, page.text[:300])
        assert "u5-" in page.text or "g4-" in page.text
        part = ux.get(f"/console/agents/{AGENT}/tab/{tab}", headers={"HX-Request": "true"})
        assert part.status_code == 200, (tab, part.text[:300])


def test_more_menu_marks_the_open_tab(ux: Console) -> None:
    html = ux.get(f"/console/agents/{AGENT}?tab=attach").text
    assert 'class="g4-more on"' in html and "<summary>Attach</summary>" in html


def test_overview_has_no_two_column_card_and_no_zero_cases_card(ux: Console) -> None:
    html = ux.get(f"/console/agents/{AGENT}").text
    assert "g4-stack" in html and "g4-stats" in html
    assert '<h3>Open <span class="k">0</span>' not in html  # never an empty cases card
    assert "Pause is one click" not in html  # the rule text is a tooltip, not a line


def test_attach_tab_keeps_the_diagram_and_folds_the_tables(ux: Console) -> None:
    html = ux.get(f"/console/agents/{AGENT}?tab=attach").text
    assert 'class="at-svg"' in html
    tables = html.split("g4-fold", 1)[1] if "g4-fold" in html else ""
    assert "attach-detectors" in tables  # the guardian tables sit inside the fold
    assert "SUPERVISOR_GATE_URL" not in html and "SUPERVISOR_CREDENTIAL_KIND" not in html
    assert "Connection type:" in html


def test_register_puts_the_action_first_and_hides_ids(ux: Console) -> None:
    html = ux.get(f"/console/agents/{AGENT}?tab=register", user="viewer.hoa").text
    assert html.index('data-section="action"') < html.index('data-section="registry"')
    assert "Technical details" not in html  # not for a viewer
    admin = ux.get(f"/console/agents/{AGENT}?tab=register", user="admin.chi").text
    assert "Technical details" in admin


def test_guardians_tab_drops_binding_columns(ux: Console) -> None:
    html = ux.get(f"/console/agents/{AGENT}?tab=guardians").text
    head = html.split('data-table="guardian-status"', 1)[1].split("</thead>", 1)[0]
    assert head.count("<th ") == 4
    assert "config/detectors.yaml" not in html


def test_tools_tab_is_bounded_and_without_p95_columns(ux: Console) -> None:
    html = ux.get(f"/console/agents/{AGENT}?tab=tools").text
    assert "p95" not in html.split('id="tools-body"', 1)[1].split("</table>", 1)[0]
    assert "docs/tool-analytics.md" not in html


# ---------------------------------------------------------------- lists and catalogues
def test_agents_list_pages_at_25_and_row_is_one_link(ux: Console) -> None:
    html = ux.get("/console/agents").text
    assert "Every agent the bank runs, and its gate state." in html
    assert "Pause, resume and quarantine are on the agent page" not in html
    assert re.findall(r'class="head rowlink" href="/console/agents/[^"?]+', html)


def test_catalogue_tabs_search_and_page(ux: Console) -> None:
    for tab in ("models", "tools", "datasets", "mcp"):
        r = ux.get(f"/console/catalogues?tab={tab}")
        assert r.status_code == 200
        assert "python -m supervisor.jobs.inventory" not in r.text
    r = ux.get("/console/catalogues?tab=models&q=zzz-no-such-model")
    assert r.status_code == 200 and ("Nothing matches" in r.text or "Nothing here yet" in r.text)
    assert ux.get("/console/catalogues?tab=models&page=junk&status=bogus").status_code == 200
    assert re.search(r"sec-tabs.*?Inventory</a>", ux.get("/console/agents").text, re.S)  # renamed


def test_inventory_page_has_one_table_not_a_tree(ux: Console) -> None:
    r = ux.get("/console/inventory")
    assert r.status_code == 200 and 'id="inv-tree"' not in r.text
    assert "Catalogues" in r.text


# ---------------------------------------------------------------- settings pages
def test_credentials_has_no_env_flag_and_no_empty_column(ux: Console) -> None:
    r = ux.get("/console/credentials", user="admin.chi")
    assert r.status_code == 200
    assert "INGRESS_AUTH_ENABLED" not in r.text and "Last used" not in r.text
    assert "How to issue or rotate a key" in r.text


def test_integrations_folds_identical_agents(ux: Console) -> None:
    r = ux.get("/console/integrations", user="admin.chi")
    assert r.status_code == 200
    assert "have no key yet" in r.text and 'class="g4-cards"' in r.text
    assert "INGRESS_AUTH_ENABLED" not in r.text and "WP26" not in r.text
    assert ux.get("/console/integrations?view=all&page=2", user="admin.chi").status_code == 200


def test_users_matrix_is_collapsed_and_without_work_package_ids(ux: Console) -> None:
    r = ux.get("/console/users", user="admin.chi")
    assert r.status_code == 200
    assert '<details class="g4-fold" id="matrix">' in r.text
    assert not re.search(r"\bWP-?[A-Z]*\d", r.text.split('id="matrix"', 1)[1])
    assert "docs/console.md" not in r.text


def test_audit_and_schema_heads(ux: Console) -> None:
    for url in ("/console/audit", "/console/admin/schema"):
        r = ux.get(url, user="admin.chi")
        assert (
            r.status_code == 200
            and "u5-head" in r.text
            and "Read only" in r.text.replace("read-only", "Read only")
        )
    assert "No entries match." in i18n.translator("en", ux5=True)("no_audit")


def test_off_path_agent_page_is_unchanged(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    for flag in FLAGS:
        monkeypatch.setattr(console.ctx.settings, flag, True)
    html = console.get(f"/console/agents/{AGENT}").text
    assert 'role="tab"' in html and "g4-" not in html and "ux5_g4.css" not in html


# ---------------------------------------------------------------- text and helpers
def test_g4_overrides_have_en_and_vi_and_known_keys() -> None:
    base = i18n.table()
    for key, (en, vi) in i18n_ux5_g4.UX5.items():
        assert key in base and en.strip() and vi.strip(), key
    for key, (en, vi) in i18n_ux5_g4.G4.items():
        assert key.startswith("g4_") and en.strip() and vi.strip(), key
    vi_t = i18n.translator("vi", ux5=True)
    en_t = i18n.translator("en", ux5=True)
    assert en_t("ik_upload") == "Upload zip" and vi_t("ik_upload") == "Tải zip"
    assert en_t("g4_more") == "More" and vi_t("g4_more") == "Thêm"


def test_strip_wp_and_paging_helpers() -> None:
    assert ux5_g4.strip_wp("Inventory page (read-only, WP24)") == "Inventory page (read-only)"
    assert "WP" not in ux5_g4.strip_wp("Playground: dry-run gate check (WP-UX3)")
    rows = [
        {"name": "a", "kind": "tool", "status": "active", "own_risk": None, "last_seen": "1"},
        {"name": "a", "kind": "tool", "status": "active", "own_risk": None, "last_seen": "2"},
        {"name": "b", "kind": "tool", "status": "unmanaged", "own_risk": None, "last_seen": "1"},
    ]
    v = ux5_g4.asset_view({"tab": "tools", "rows": rows, "off": False}, {"q": "A"})
    assert [r["name"] for r in v["rows"]] == ["a"] and v["rows"][0]["n"] == 2
    assert v["ux"]["total"] == 2 and v["ux"]["show_risk"] is False


def test_integration_agents_folds_the_common_row() -> None:
    agents = [
        {
            "agent_id": f"a{i}",
            "gate_state": "RUNNING",
            "has_key": False,
            "mode": "enforce",
            "consumers": 0,
        }
        for i in range(30)
    ]
    agents.append(
        {
            "agent_id": "k1",
            "gate_state": "RUNNING",
            "has_key": True,
            "mode": "enforce",
            "consumers": 1,
        }
    )
    v = ux5_g4.integration_agents(agents, {})
    assert v["folded"] == 30 and [a["agent_id"] for a in v["rows"]] == ["k1"]
    assert v["nokey"] == 30
    full = ux5_g4.integration_agents(agents, {"view": "all", "page": "2"})
    assert full["folded"] == 0 and full["page"] == 2 and len(full["rows"]) == 6
