# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
"""UX5 group G5: guardian catalog, guardian factory (list, new, detail), playground, analytics
tabs, oversight metrics, traces. On-path render tests: bounded length, key text present, no env
flags or docs paths for a non-admin, override text in English and Vietnamese. The off path is
covered by the existing tests of each page."""

from __future__ import annotations

import re
from typing import Any

import pytest

from supervisor.console import i18n, i18n_ux5, i18n_ux5_g5, ux5_g5
from tests.console.test_g3_routes import DEF, Clk, api, findings, make_shadow
from tests.guardian_factory.conftest import adapters, console, gf, regex_def, seeded  # noqa: F401

AN = "reviewer.an"
CHI = "admin.chi"
HX = {"HX-Request": "true"}


def words(html: str) -> int:
    main = html.split("<main", 1)[-1]
    return len(re.findall(r"\S+", re.sub(r"<[^>]+>", " ", main)))


@pytest.fixture
def ux(gf: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    s = gf.ctx.settings
    monkeypatch.setattr(s, "console_ux5", True)
    for flag in (
        "console_nav_v3",
        "console_decisions_v2",
        "console_catalog_enabled",
        "console_playground_enabled",
        "console_traces_enabled",
        "console_tools_enabled",
    ):
        monkeypatch.setattr(s, flag, True)
    return gf


# ------------------------------------------------------------------ text tables
def test_new_text_has_both_languages_and_matching_placeholders() -> None:
    for key, (en, vi) in i18n_ux5_g5.NEW.items():
        assert en.strip() and vi.strip(), key
        assert set(re.findall(r"{(\w+)}", en)) == set(re.findall(r"{(\w+)}", vi)), key
        assert i18n.table()[key] == (en, vi), f"{key} is merged into the base table"
    assert i18n.translator("vi")("cat_title") != i18n.translator("en")("cat_title")


def test_g5_module_is_registered_and_overrides_real_keys() -> None:
    assert "supervisor.console.i18n_ux5_g5" in i18n_ux5.MODULES
    base = i18n.table()
    for key in i18n_ux5_g5.UX5:
        assert key in base, key


# ------------------------------------------------------------------ helpers
def test_helpers() -> None:
    assert ux5_g5.pct(316) == "3.2%" and ux5_g5.pct(0) == "0%" and ux5_g5.pct(10000) == "100%"
    assert ux5_g5.pct(None) == "-" and ux5_g5.share(1, 4) == "25%" and ux5_g5.share(1, 0) == "-"
    assert ux5_g5.when("2026-10-29T14:00:43.419685Z") == "29 Oct 2026, 21:00"
    assert ux5_g5.when("2026-10-29T14:00:43Z", short=True) == "29 Oct 21:00"
    assert ux5_g5.when(None) == "-" and ux5_g5.when("junk") == "junk"
    assert ux5_g5.rule("injection_regex") == "Prompt injection patterns"
    assert ux5_g5.rule("injection.instruction_override") == "Injection: instruction override"
    assert ux5_g5.rule("gf:vn-account-number-mask@1") == "Vn account number mask"
    assert ux5_g5.monitor_reason("no reply tool bound (monitors.quality.reply_tools) and none") == (
        "No reply tool chosen"
    )
    assert "monitors." not in ux5_g5.monitor_reason(
        "several money tools (a, b): set monitors.split_payment.tool"
    )
    assert ux5_g5.monitor_reason("no gate_decision events for transfer in the last 3600 s") == (
        "No calls to transfer in the last hour"
    )


def test_monitor_view_keeps_only_agents_with_data() -> None:
    na = {"status": "not_applicable"}
    rows = [
        {"agent_id": "a", "monitors": {"quality": na, "drift": na}},
        {"agent_id": "b", "monitors": {"quality": {"status": "no_data"}, "drift": na}},
    ]
    out = ux5_g5.monitor_view(rows, ("quality", "drift"))
    assert [r["agent_id"] for r in out["mon_active"]] == ["b"]
    assert out["mon_hidden"] == 1 and out["mon_summary"]["drift"]["not_applicable"] == 2


# ------------------------------------------------------------------ catalog
def test_catalog_is_one_list_without_dev_text_for_a_reviewer(ux: Any) -> None:
    r = ux.get("/console/catalog", user=AN)
    assert r.status_code == 200
    html = r.text
    assert "Guardian catalog" in html and "Can block" in html and "g5-row" in html
    assert "docs/" not in html and "DETECTORS_ENABLED" not in html and "WP-D" not in html
    assert "Technical details" not in html  # admin only
    assert "Ask the platform team to turn it on" in html
    assert 'class="cat-card' not in html  # rows, not cards
    assert words(html) < 1500


def test_catalog_admin_sees_the_technical_disclosure(ux: Any) -> None:
    html = ux.get("/console/catalog", user=CHI).text
    assert "Technical details" in html and "DETECTORS_ENABLED=1" in html


def test_catalog_filters_and_guardians_tabs_share_the_list(ux: Any) -> None:
    only = ux.get("/console/catalog?cat=detect", user=AN).text
    assert "Vietnamese personal data" in only and "Policy rules" not in only
    off = ux.get("/console/catalog?state=off", user=AN).text
    assert "Ask the platform team" in off
    on = ux.get("/console/catalog?state=on", user=AN).text
    assert "Ask the platform team" not in on
    tab = ux.get("/console/guardians?tab=monitors", user=AN)
    assert tab.status_code == 200 and "g5-row" in tab.text and "Drift monitor" in tab.text
    assert "Policy rules" not in tab.text
    bad = ux.get("/console/catalog?cat=nonsense", user=AN)
    assert bad.status_code == 200 and "Policy rules" in bad.text  # unknown filter = all


def test_catalog_system_picker_resolves_a_name_to_the_system(
    ux: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supervisor.console import guardians_view

    calls: list[Any] = []

    def fake(ctx: Any, me: Any, system_id: Any) -> dict[str, Any]:
        calls.append(system_id)
        systems = [{"system_id": "sys_1", "name": "Payment copilot"}]
        chosen = systems[0] if system_id == "sys_1" else None
        return {
            "systems": systems,
            "system": chosen,
            "by_card": {},
            "can_edit": False,
            "never_cards": (),
            "state_actions": False,
        }

    monkeypatch.setattr(guardians_view, "catalog_panel", fake)
    html = ux.get("/console/catalog?system_name=Payment%20copilot", user=AN).text
    assert "sys_1" in calls  # the name was turned into the id
    assert 'list="gb-systems"' in html and '<option value="Payment copilot">' in html
    assert "(sys_1)" not in html and '<select id="gb-system"' not in html
    none = ux.get("/console/catalog", user=AN).text
    assert "Choose a system to see which guardians are on" in none


def test_catalog_vietnamese(ux: Any) -> None:
    html = ux.get("/console/catalog?lang=vi", user=AN).text
    assert "Danh mục bộ bảo vệ" in html and "Có thể chặn" in html


# ------------------------------------------------------------------ guardian factory
def test_factory_list_has_filter_chips_and_no_state_dropdown(ux: Any) -> None:
    assert (
        api(ux, "POST", "/v1/guardian-defs", regex_def(owner_group="model_risk")).status_code == 201
    )
    html = ux.get("/console/guardian-factory", user=AN).text
    assert "Guardian factory" in html and "g5-chips" in html and 'id="f-state"' not in html
    assert "Account numbers" in html and "Draft 1" in html
    assert "Retired" not in html  # a state with no guardian is hidden
    assert words(html) < 400


def test_new_form_puts_business_fields_first_and_json_under_advanced(ux: Any) -> None:
    html = ux.get("/console/guardian-factory/new", user=AN).text
    assert 'name="name"' in html and "Advanced" in html
    adv = html.index('data-advanced="1"')
    for field in ('name="name"', 'name="description"', 'name="text"', 'name="type"'):
        assert html.index(field) < adv, field
    for field in ('name="config_json"', 'name="min_tpr_pct"', 'name="sensitivity"'):
        assert html.index(field) > adv, field
    assert html.index('data-action="draft"') < adv and 'data-action="save"' in html
    assert "Benchmark pack id" not in html and "Test pack (optional)" in html
    assert words(html) < 400
    vi = ux.get("/console/guardian-factory/new?lang=vi", user=AN).text
    assert "Mô tả guardian" in vi


def test_detail_has_section_nav_plain_words_and_folded_findings(ux: Any) -> None:
    clk = Clk()
    make_shadow(ux, clk)
    assert (
        api(ux, "POST", f"/v1/guardian-defs/{DEF}/shadow/start", {}, user="lead.model").status_code
        == 200
    )
    findings(ux, clk, n=9)
    html = ux.get(f"/console/guardian-factory/{DEF}", user=AN).text
    for anchor in ("#g5-rule", "#g5-test", "#g5-trial", "#g5-approval"):
        assert anchor in html, anchor
    assert "Caught" in html or "Latest run" in html
    assert ">TP<" not in html and ">FPR %<" not in html and "p50 (us)" not in html
    assert "Show all 9" in html  # 5 shown, the rest folded
    assert "bench_pack_generate" not in html and "shadow_started" not in html
    assert "Trial run" in html and "started a trial run" in html


def test_detail_edit_form_still_posts_the_same_fields(ux: Any) -> None:
    assert (
        api(ux, "POST", "/v1/guardian-defs", regex_def(owner_group="model_risk")).status_code == 201
    )
    html = ux.get(f"/console/guardian-factory/{DEF}", user=AN).text
    for name in (
        "name",
        "description",
        "owner_group",
        "type",
        "stage",
        "action_on_fail",
        "scope_agents",
        "scope_tools",
        "scope_data_classes",
        "sensitivity",
        "benchmark_pack",
        "min_tpr_pct",
        "max_fpr_pct",
        "max_p95_ms",
        "shadow_days",
        "config_json",
    ):
        assert f'name="{name}"' in html, name
    assert 'hx-post="/console/guardian-factory/account-numbers?lang=en"' in html


# ------------------------------------------------------------------ playground
def test_playground_check_button_before_advanced_fields(ux: Any) -> None:
    r = ux.get("/console/playground", user=AN)
    assert r.status_code == 200
    html = r.text
    assert html.index("btn primary") < html.index('id="pg-context"')
    assert "Call details (JSON)" in html and "Test what the gate would decide" in html
    assert '<datalist id="pg-agents">' in html and '<select id="pg-agent"' not in html
    assert words(html) < 300


def test_playground_result_hides_hashes_from_a_reviewer(ux: Any) -> None:
    form = {
        "agent_id": "payments",
        "version": "playground",
        "tool": "transfer",
        "args": '{"amount": 1}',
        "context": "{}",
        "direction": "input",
    }
    r = ux.post("/console/playground/run", data=form, user=AN)
    assert r.status_code == 200 and "Result" in r.text
    assert "Policy hash" not in r.text and "Technical details" not in r.text
    admin = ux.post("/console/playground/run", data=form, user=CHI)
    assert "Technical details" in admin.text


# ------------------------------------------------------------------ analytics
def test_analytics_tabs_render_and_stay_short(ux: Any) -> None:
    for tab, cap in (("gate", 900), ("metrics", 900), ("latency", 200), ("detectors", 400)):
        r = ux.get(f"/console/analytics?tab={tab}", user=AN)
        assert r.status_code == 200, tab
        assert words(r.text) < cap, (tab, words(r.text))
        assert " bp" not in r.text, tab
    assert ux.get("/console/analytics?tab=latency&lang=vi", user=AN).status_code == 200


def test_metrics_tab_folds_not_applicable_agents(ux: Any) -> None:
    html = ux.get("/console/analytics?tab=metrics", user=AN).text
    assert "monitors.quality" not in html and "monitors.split_payment" not in html
    assert "Chain status" not in html and "Evidence chain" in html


def test_metrics_redirect_target_is_the_analytics_tab(ux: Any) -> None:
    r = ux.get("/console/metrics", user=AN, follow_redirects=True)
    assert r.status_code == 200 and "Oversight metrics" in r.text


# ------------------------------------------------------------------ traces
def test_traces_list_and_detail(ux: Any) -> None:
    r = ux.get("/console/traces", user=AN)
    assert (
        r.status_code == 200
        and "More filters" in r.text
        and "Open a trace to see each step" in r.text
    )
    ids = re.findall(r'href="/console/traces/([0-9a-f]{8,})\?lang', r.text)
    if ids:
        d = ux.get(f"/console/traces/{ids[0]}", user=AN)
        assert d.status_code == 200 and "Technical details" not in d.text
        assert ids[0] not in d.text.split("<main", 1)[1].split("</h1>", 1)[0]
        admin = ux.get(f"/console/traces/{ids[0]}", user=CHI)
        assert "Technical details" in admin.text
    assert ux.get("/console/traces/rows", user=AN, headers=HX).status_code == 200
    assert ux.get("/console/traces?lang=vi", user=AN).status_code == 200
