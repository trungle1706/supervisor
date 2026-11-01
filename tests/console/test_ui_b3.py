# ruff: noqa: F811
"""UI audit batch 3 (docs/ui/redundancy-audit.md): names, labels, raw ids, en/vi, breadcrumbs.

``label_for`` (labels.py), UI-300 tagline and breadcrumbs, UI-330 names instead of ids,
UI-331/042 no flag names or API paths for people, the "Demo data" chip, UI-005/340 task titles by
code, UI-301/302/193/111 one name per page, UI-341 plurals."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.config import REPO_ROOT
from supervisor.console import i18n, labels
from supervisor.console.i18n import translator
from tests.governance.conftest import draft, mounted, on, restore_app  # noqa: F401  (fixtures)

from .conftest import Console
from .test_c4_portfolio import pf, pfall, seeded_pf  # noqa: F401  (fixtures)


@pytest.fixture
def ux(seeded_pf: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(seeded_pf.ctx.settings, "console_ux5", True)
    return seeded_pf


def _lab(lang: str = "en", *, admin: bool = False, **kw: Any) -> labels.Labeler:
    return labels.Labeler(translator(lang, ux5=True), is_admin=admin, **kw)


# ------------------------------------------------------------------ the helper


def test_label_for_uses_the_name_and_keeps_the_id_in_a_tooltip() -> None:
    lab = _lab(agents=lambda: {"shw_ag_1": "Card <Advisor>"}, systems=lambda: {"s1": "Cards"})
    assert lab.text("agent", "shw_ag_1") == "Card <Advisor>"
    html = str(lab.html("agent", "shw_ag_1"))
    assert html == '<span class="lbl" title="shw_ag_1">Card &lt;Advisor&gt;</span>'
    assert lab.text("system", "s1") == "Cards"
    # no name: the id itself, escaped, no tooltip
    assert str(lab.html("agent", "x<y")) == "x&lt;y"
    assert lab.text("agent", None) == "-" and lab.text("system", "-") == "-"


def test_label_for_translates_keys_in_both_languages() -> None:
    en, vi = _lab("en"), _lab("vi")
    assert en.text("kind", "genie_space") == "Genie space"
    assert vi.text("kind", "genie_space") == "Không gian Genie"
    assert en.text("rule", "AR-D33-HIGH") == "Decision 33 high risk"
    assert vi.text("rule", "AR-D33-HIGH") != en.text("rule", "AR-D33-HIGH")
    assert en.text("guardian", "dlp_vn") == "Vietnamese personal data"
    assert en.text("guardian", "monitor_drift") == "Drift monitor"
    assert en.text("gf_type", "regex") == "Pattern (regex)"
    assert vi.text("gf_stage", "tool_call") == "Lệnh gọi công cụ"


def test_label_for_falls_back_without_breaking() -> None:
    lab = _lab()
    assert lab.text("kind", "some_new_kind") == "Some new kind"  # spaced word
    assert lab.text("task", "CUSTOM-1", "Stored title") == "Stored title"  # free text kept
    assert lab.text("task", "CUSTOM-1") == "CUSTOM-1"
    assert lab.text("rule", "AR-NEW") == "AR-NEW"

    def boom() -> dict[str, str]:
        raise RuntimeError("store down")

    assert _lab(agents=boom).text("agent", "a1") == "a1"  # a label never breaks a page


def test_flag_names_only_for_admins() -> None:
    assert (
        str(_lab(admin=True).flag_title("RISK_REGISTER_ENABLED"))
        == ' title="RISK_REGISTER_ENABLED"'
    )
    assert str(_lab(admin=False).flag_title("RISK_REGISTER_ENABLED")) == ""


def test_demo_tag_becomes_a_chip_and_the_stored_text_is_unchanged() -> None:
    text = "[demo:showcase] Set from the approved classification."
    assert labels.strip_demo(text) == ("Set from the approved classification.", True)
    assert labels.strip_demo("Plain text") == ("Plain text", False)
    out = str(_lab("en").demo(text))
    assert "Demo data" in out and "[demo:showcase]" not in out.replace(
        'title="[demo:showcase]"', ""
    )
    assert out.endswith("Set from the approved classification.")
    assert "Dữ liệu minh họa" in str(_lab("vi").demo(text))
    assert str(_lab().demo("<b>x</b>")) == "&lt;b&gt;x&lt;/b&gt;"  # escaped
    assert str(_lab().demo(None)) == ""


def test_every_task_template_and_assignment_rule_has_a_label_in_both_languages() -> None:
    tasks = yaml.safe_load((REPO_ROOT / "config" / "tasks.yaml").read_text(encoding="utf-8"))
    rules = yaml.safe_load(
        (REPO_ROOT / "config" / "assignment_rules.yaml").read_text(encoding="utf-8")
    )
    table = i18n.table()
    for t in tasks["templates"]:
        en, vi = table[labels.key_for("task", t["id"])]
        assert en == t["title"], t["id"]  # the English label is the template title
        assert vi and vi != en, t["id"]
    for r in rules:
        assert labels.key_for("rule", r["id"]) in table, r["id"]


# ------------------------------------------------------------------ UI-300 names of the nav


def test_tagline_and_breadcrumbs_use_the_names_of_the_nav(ux: Console) -> None:
    t = translator("en", ux5=True)
    assert t("tagline") == "AI\u00a0management · AI\u00a0guardian"  # no-break: wraps after the dot
    assert translator("vi", ux5=True)("tagline") == "Quản lý AI · Giám sát AI"
    checked = 0
    for url in (
        "/console/cases",
        "/console/alerts",
        "/console/signoff",
        "/console/incidents",
        "/console/evidence",
    ):
        r = ux.get(url + "?lang=en", user="admin.chi")
        if r.status_code != 200:  # a page whose flag is off in this fixture
            continue
        checked += 1
        h = r.text
        assert "Onboard · Watch · Prove" not in h, url
        crumbs = _crumbs(h)
        assert crumbs and "AI guardian" in crumbs, url
        assert not re.search(r"\b(Act|Watch|Prove)\b", crumbs), url
    assert checked >= 2


def _crumbs(html: str) -> str:
    m = re.search(r'<nav[^>]*class="crumbs"[^>]*>(.*?)</nav>', html, re.S)
    return re.sub(r"<[^>]+>", " ", m.group(1)) if m else ""


# ------------------------------------------------------------------ UI-330 names, not ids


def test_incidents_and_cases_show_names_first(ux: Console) -> None:
    names = {r["agent_id"]: r["name"] for r in ux.ctx.state.query("agent") if r.get("name")}
    inc = ux.get("/console/incidents?lang=en", user="admin.chi").text
    cases = ux.get("/console/cases?lang=en", user="admin.chi").text
    for h in (inc, cases):
        shown = re.findall(r">(shw_(?:ag|sys)_\d+)<", h)
        assert not shown, shown  # no bare id as cell text
    # the agent filter lists names, the value stays the id
    assert any(f'title="{a}"' in cases or a not in names for a in names)
    for a, n in list(names.items())[:3]:
        if a in cases:
            assert n in cases


def test_cases_table_hides_the_report_due_column_when_every_row_is_empty(ux: Console) -> None:
    h = ux.get("/console/cases?lang=en", user="admin.chi").text
    has_clock = bool(re.search(r'class="clockcell"', h)) or "Closed" in h
    assert ("Report due" in h) == has_clock
    # the manual source is not printed as a line under every case
    assert 'class="idline">person' not in h


# ------------------------------------------------------------------ UI-331 / UI-042


def test_governance_kpis_have_no_flag_names_for_people(ux: Console) -> None:
    for user, admin in (("admin.chi", True), ("reviewer.an", False)):
        h = ux.get("/console/governance?scope=all&lang=en", user=user)
        if h.status_code != 200:
            continue
        body = h.text
        assert "GET /v1/kpis" not in body and "MCP tool" not in body
        assert "basis points" not in body
        visible = re.sub(r'title="[^"]*"', "", body)
        assert "RISK_REGISTER_ENABLED" not in visible and "CONTROLS_ENABLED" not in visible
        assert ("RISK_REGISTER_ENABLED" in body) == (admin and "The risk register is off" in body)
        # enum keys are labels
        assert "genie_space:" not in body and "model_endpoint:" not in body


def test_onboard_off_text_has_no_flag_name_in_view(ux: Console) -> None:
    h = ux.get("/console/onboard?lang=en", user="reviewer.an")
    if h.status_code == 200:
        assert "CONSOLE_ONBOARD_ENABLED" not in h.text


def test_demo_tag_is_a_chip_on_the_system_page(ux: Console) -> None:
    sid = next(iter(ux.ids.values()))  # type: ignore[attr-defined]
    row = ux.ctx.state.get("ai_system", {"system_id": sid})
    assert row is not None
    ux.ctx.state.update(
        "ai_system",
        {"system_id": sid},
        {"risk_justification": "[demo:showcase] Set from the approved classification."},
        expected_version=row["row_version"],
    )
    h = ux.get(f"/console/systems/{sid}?lang=en", user="admin.chi").text
    assert "Set from the approved classification" in h
    assert "[demo:showcase] Set" not in h
    assert "Demo data" in h
    stored = ux.ctx.state.get("ai_system", {"system_id": sid})
    assert stored["risk_justification"].startswith("[demo:showcase]")  # data unchanged


def test_copy_json_is_for_admins(ux: Console) -> None:
    rows = ux.ctx.cases.list_cases(statuses=["open"])
    if not rows:
        pytest.skip("no open case in the fixture")
    cid = rows[0]["case_id"]
    admin = ux.get(f"/console/cases/{cid}/drawer?lang=en", user="admin.chi").text
    other = ux.get(f"/console/cases/{cid}/drawer?lang=en", user="reviewer.an").text
    assert "data-copy=" in admin and "data-copy=" not in other


# ------------------------------------------------------------------ UI-301 / 193 / 111 one name


def test_one_name_per_page_in_both_languages() -> None:
    for lang in ("en", "vi"):
        t = translator(lang, ux5=True)
        assert t("nv3_t_approvals") == t("signoff")  # Approvals everywhere
        assert t("nv3_t_unmanaged") == t("nav_inventory")
        assert t("cp_title") == t("nv3_t_policies")  # Compliance: tab = heading
        assert t("nv3_t_evidence")  # the Evidence page heading uses the tab name
    en = translator("en", ux5=True)
    assert en("nv3_gov_overview").startswith(en("nv3_gov"))
    assert en("nv3_sup_overview").startswith(en("nv3_sup"))
    assert en("nv3_risks_controls") != "Risks & controls"  # the section holds more than that


# ------------------------------------------------------------------ UI-341 plurals


def test_plural_helper_picks_the_one_form() -> None:
    t = translator("en", ux5=True)
    one = t("b3_kindn_guardian_one", n=1)
    many = t("b3_kindn_guardian", n=2)
    assert one == "1 guardian feature" and many == "2 guardian features"
    assert t("fa_agents_n_one", n=1) == "1 agent" and t("fa_agents_n", n=3) == "3 agents"


def test_changed_keys_exist_in_base_and_ux5_with_the_same_text() -> None:
    from supervisor.console import i18n_ux5_b3, i18n_ux_b3

    base = i18n.table()
    for k, v in i18n_ux_b3.CHANGED.items():
        assert base[k] == v, k
        assert i18n_ux5_b3.UX5[k] == v, k
    assert not set(i18n_ux_b3.NEW) & set(i18n_ux_b3.CHANGED)


def test_templates_never_print_a_raw_flag_name_outside_admin_or_tooltip() -> None:
    """A user text key must not carry a settings flag or an API path (the page shows words)."""
    from supervisor.console import i18n_ux_b3

    bad = re.compile(r"\b[A-Z]{3,}(?:_[A-Z0-9]{2,})+\b|\b(?:GET|POST) /v1")
    for k, (en, vi) in i18n_ux_b3.NEW.items() | i18n_ux_b3.CHANGED.items():
        assert not bad.search(en) and not bad.search(vi), k


def test_labels_module_is_pure_of_io_imports() -> None:
    src = Path(labels.__file__).read_text(encoding="utf-8")
    assert "sqlite3" not in src and "httpx" not in src
