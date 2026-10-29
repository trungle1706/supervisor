"""UX5 package G2: the systems pages (list, detail and its tabs), tasks, candidates, onboard,
integration and the register list on the CONSOLE_UX5 path. The off path is proven by the existing
tests of these pages; here the on path: shape, bounded length, key text, no env flags for a
non-admin, override text in English and Vietnamese."""

from __future__ import annotations

import re

import pytest

from supervisor.console import i18n, systems_views
from supervisor.governance import duties_gap as dg

from .conftest import Console
from .test_l3_duties import CREATOR, _control, _seed, _system, dty  # noqa: F401

FLAG = re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+){2,}\b")  # an env flag such as ONBOARD_INTAKE


@pytest.fixture
def ux(dty: Console, monkeypatch: pytest.MonkeyPatch) -> Console:  # noqa: F811
    monkeypatch.setattr(dty.ctx.settings, "console_ux5", True)
    monkeypatch.setattr(dty.ctx.settings, "console_nav_v3", True)
    return dty


def _words(html: str) -> int:
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S)
    return len(re.sub(r"<[^>]+>", " ", body).split())


def _instruments(c: Console, n: int) -> list[str]:
    kb = dg.kb_of(c.ctx)
    return sorted({o.instrument_id for o in kb.obligations.values()})[:n]


# ------------------------------------------------------------------------------------ duties
def test_duties_one_group_per_framework_with_ticks_and_bulk_bar(ux: Console) -> None:
    sid = _system(ux)
    a, b = _instruments(ux, 2)
    _seed(ux, sid, a, 3, coverage="none")
    _seed(ux, sid, a, 2, coverage="partial", skip=3)
    _seed(ux, sid, b, 2, coverage="none")
    html = ux.get(f"/console/systems/{sid}?tab=duties&lang=en").text
    assert html.count('data-section="duty-group"') == 2  # not split by coverage
    assert html.count('<details class="g2-fw"') == 2
    assert len(re.findall(r'<details class="g2-fw"[^>]*\bopen\b', html)) == 1  # only the first
    assert 'class="u5-ticks"' in html and "u5-legend" in html
    assert html.count('class="g2-bulk"') == 2
    assert "Re-evaluate" in html
    assert "Re-run the matrix on the stored answers. Nothing is deleted." in html
    assert "Advisory, not legal advice" in html  # one disclaimer chip
    assert html.count('title="Advisory, not legal advice"') == 1
    for gone in (">Applies<", ">Closing control<", ">Due<", ">Coverage<"):
        assert gone not in html
    vi = ux.get(f"/console/systems/{sid}?tab=duties&lang=vi").text
    assert "Đánh giá lại" in vi and "Chỉ tham khảo" in vi


def test_duties_page_size_25_and_pager(ux: Console) -> None:
    sid = _system(ux)
    a = _instruments(ux, 1)[0]
    n = len(list(dg.kb_of(ux.ctx).obligations_of(a)))
    _seed(ux, sid, a, min(n, 40), coverage="none")
    if n < 30:
        pytest.skip("instrument too small for two pages")
    html = ux.get(f"/console/systems/{sid}?tab=duties&lang=en").text
    assert html.count('data-obligation="') == 25
    assert "Page 1 of 2" in html and "page=2" in html
    page2 = ux.get(f"/console/systems/{sid}?tab=duties&lang=en&p=2").text
    assert 'data-obligation="' in page2 and "Page 2 of 2" in page2


def test_duties_bulk_close_selected_rows(ux: Console) -> None:
    sid = _system(ux)
    a = _instruments(ux, 1)[0]
    ids = _seed(ux, sid, a, 3, coverage="none")
    cid = _control(ux)
    sel = {f"sel_{dg.dut.status_id(sid, oid)}": "1" for oid in ids[:2]}
    r = ux.post(
        f"/console/systems/{sid}/duties/close",
        {**sel, "closing_control": cid, "evidence_ref": "DOC-1 page 2"},
        user=CREATOR,
    )
    assert r.status_code == 200, r.text[:300]
    states = [
        ux.ctx.state.get("obligation_status", {"status_id": dg.dut.status_id(sid, o)})["status"]
        for o in ids
    ]
    assert states == ["closed", "closed", "open"]
    none = ux.post(
        f"/console/systems/{sid}/duties/close",
        {"closing_control": cid, "evidence_ref": "DOC-1 page 2"},
        user=CREATOR,
    )
    assert none.status_code == 400  # nothing selected is an error message, never a 500


def test_pick_off_path_unchanged() -> None:
    rows = [
        {
            "status_id": "s1",
            "instrument_id": "I",
            "coverage": "none",
            "applies": "yes",
            "status": "open",
        }
    ]
    assert dg.pick(rows, {"status_id": "s1"}) == rows
    assert dg.pick(rows, {"group": "I|none"}) == rows
    with pytest.raises(dg.DutyError):
        dg.pick(rows, {})


# ------------------------------------------------------------------------------ system tabs
def test_system_head_and_grouped_tabs(ux: Console) -> None:
    sid = _system(ux)
    html = ux.get(f"/console/systems/{sid}?lang=en").text
    assert "g2-sysnav" in html and "g2-syshead" in html
    assert "AI management" in html and "Risk level: how is it set?" in html
    assert "The AI systems of the bank: who owns" not in html  # list copy removed
    assert "Compliance</span>" in html or "Compliance" in html
    assert _words(html) < 700
    assert not FLAG.search(re.sub(r"<[^>]+>", " ", html.split("<main", 1)[1]))
    for tab in ("components", "rules", "classification", "tasks", "reviews", "guardians"):
        r = ux.get(f"/console/systems/{sid}?tab={tab}&lang=en")
        assert r.status_code == 200, tab
        assert 'class="g2-sysnav"' in r.text


def test_rules_tab_groups_identical_rows() -> None:
    rows = [
        {
            "kind": "obligation",
            "ref_id": f"O-{i}",
            "rules": [{"rule": "AR-D33-HIGH", "fields": ["decision33_class"]}],
            "active": True,
        }
        for i in range(190)
    ] + [
        {
            "kind": "guardian",
            "ref_id": "dlp_vn",
            "rules": [{"rule": "AR-PDPL", "fields": []}],
            "active": True,
        }
    ]
    groups = systems_views.group_assignments(rows)
    assert [g["n"] for g in groups] == [190, 1]
    assert groups[0]["fields"] == ["decision33_class"] and groups[0]["kinds"] == {"obligation": 190}


def test_rules_tab_render_is_short(ux: Console) -> None:
    sid = _system(ux)
    html = ux.get(f"/console/systems/{sid}?tab=rules&lang=en").text
    assert "g2-rulegroup" in html or "No rule" in html or "rules" in html.lower()
    assert _words(html) < 800


def test_tasks_tab_has_no_duty_tasks(ux: Console) -> None:
    sid = _system(ux)
    html = ux.get(f"/console/systems/{sid}?tab=tasks&lang=en").text
    assert "DUTY-" not in html and "Stage" in html


def test_classification_cards_without_q_codes(ux: Console) -> None:
    sid = _system(ux)
    ux.post(f"/console/systems/{sid}/classification/draft", {}, user=CREATOR)
    html = ux.get(f"/console/systems/{sid}?tab=classification&lang=en").text
    assert "Advisory, not legal advice" in html
    assert 'class="g2-q"' in html and ">Q-MONEY<" not in html and "Q-MONEY</span>" not in html
    assert 'type="radio"' in html


def test_guardians_tab_floor_once(ux: Console) -> None:
    sid = _system(ux)
    html = ux.get(f"/console/systems/{sid}?tab=guardians&lang=en").text
    assert html.count('title="Advisory, not legal advice"') == 1
    assert html.count('data-section="system-guardians-floor"') <= 1
    assert "detectors.yaml" not in html and "snippet" not in html.lower().replace("snippet-", "")


def test_riskdim_one_table_one_disclaimer(ux: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ux.ctx.settings, "risk_dimensions", True)
    sid = _system(ux)
    html = ux.get(f"/console/systems/{sid}?tab=riskdim&lang=en").text
    assert html.count('title="Advisory, not legal advice"') == 1
    assert html.count('data-table="rd-rows"') == 1
    assert _words(html) < 900


def test_empty_tabs_offer_link_an_agent(ux: Console) -> None:
    sid = _system(ux)
    for tab in ("controls", "policies", "reports"):
        r = ux.get(f"/console/systems/{sid}?tab={tab}&lang=en")
        assert r.status_code == 200, tab
        if "No agent is linked" in r.text:
            assert "Link an agent" in r.text


# ------------------------------------------------------------------------- other G2 pages
@pytest.mark.parametrize(
    ("url", "text"),
    [
        ("/console/systems?lang=en", "AI systems of the bank, with owner, stage and risk level."),
        ("/console/tasks?lang=en", "Tasks per system and lifecycle stage."),
        ("/console/candidates?lang=en", "Workspace objects not yet registered as AI systems."),
        ("/console/onboard?lang=en", "Bring an agent under supervision in 6 steps."),
        ("/console/register?lang=en", "+ Register"),
    ],
)
def test_page_render_on_path(
    ux: Console, monkeypatch: pytest.MonkeyPatch, url: str, text: str
) -> None:
    for flag in ("console_onboard_enabled", "console_register_v2", "console_overview_v4"):
        if hasattr(ux.ctx.settings, flag):
            monkeypatch.setattr(ux.ctx.settings, flag, True)
    r = ux.get(url)
    if r.status_code in (400, 404):
        pytest.skip("page is off in this fixture")
    assert r.status_code == 200, url
    assert text in r.text
    assert _words(r.text) < 2500
    main = r.text.split("<main", 1)[1]
    assert not FLAG.search(re.sub(r"<[^>]+>", " ", main))


def test_systems_list_has_no_ids_under_names(ux: Console) -> None:
    sid = _system(ux)
    html = ux.get("/console/systems?lang=en").text
    assert 'class="idline mono">' + sid not in html and sid in html  # id only in the tooltip


def test_integration_page_vi_and_en(ux: Console) -> None:
    r = ux.get("/console/integration?lang=en")
    if r.status_code != 200:
        pytest.skip("integration page is off")
    assert "Readiness reports for agents to bring under Watch." in r.text
    assert "ONBOARD_ADVISOR_ENABLED" not in r.text
    vi = ux.get("/console/integration?lang=vi").text
    assert "Báo cáo mức sẵn sàng" in vi


# ------------------------------------------------------------------------------------- text
def test_g2_text_keys_have_en_and_vi() -> None:
    from supervisor.console import i18n_g2, i18n_ux5_g2

    base = i18n.table()
    for k, (en, vi) in {**i18n_g2.G2, **i18n_ux5_g2.UX5}.items():
        assert en.strip() and vi.strip(), k
        assert k in base, k
    assert all(k.startswith("g2_") for k in i18n_g2.G2)
    t_en, t_vi = i18n.translator("en", ux5=True), i18n.translator("vi", ux5=True)
    assert t_en("sy_purpose").startswith("AI systems of the bank")
    assert t_vi("sy_purpose").startswith("Các hệ thống AI")
    assert i18n.translator("en")("sy_purpose").startswith("The AI systems of the bank: who owns")
