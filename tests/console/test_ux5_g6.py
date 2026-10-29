# ruff: noqa: E501
"""UX5 group G6 on-path render tests: cases, evidence, alerts, sign-off, incidents, assurance,
agent factory (list, editor, harness grid, gate banner) and the simulation review (one Save)."""

from __future__ import annotations

import re
from typing import Any

import pytest

from supervisor.console import case_ux5, factory_ux5, i18n, i18n_ux5
from supervisor.factory import gate

from .conftest import Console
from .test_f3_gate import HX, create, fake_inputs, start


@pytest.fixture
def ux(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    s = console.ctx.settings
    for flag in (
        "console_ux5",
        "console_assurance_enabled",
        "governance_enabled",
        "agent_factory",
        "agent_factory_gate",
    ):
        monkeypatch.setattr(s, flag, True)
    from tests.factory.f3_helpers import FakeChat

    console.ctx.gate_chat = FakeChat()  # type: ignore[attr-defined]
    return console


def _pay07(c: Console) -> dict:
    return next(x for x in c.ctx.cases.list_cases() if "PAY-07" in x["summary"])


def _words(html: str) -> int:
    main = html.split("<main", 1)[-1]
    return len(re.sub(r"<[^>]+>", " ", main).split())


# ------------------------------------------------------------------ unit
def test_group_story_groups_repeats_and_keeps_singletons() -> None:
    def item(ts: str, key: str, rule: str = "R1") -> dict[str, Any]:
        return {"ts": ts, "key": key, "params": {"rule": rule, "desc": "d"}, "dot": ""}

    story = [
        item("1", "st_rule_pause"),
        item("2", "st_rule_pause"),
        item("3", "st_rule_pause", "R2"),
        item("4", "ev_open"),
        item("5", "st_rule_pause"),
    ]
    g = case_ux5.group_story(story)
    assert [(x["count"], x["ts_from"], x["ts_to"]) for x in g] == [
        (3, "1", "5"),
        (1, "3", "3"),
        (1, "4", "4"),
    ]
    assert g[0]["grouped"] and not g[1]["grouped"]


def test_group_verdicts_one_row_per_rule() -> None:
    rows = [
        {"ts": "1", "source": "tier0", "rule_id": "A", "tier": 0, "action": "pause", "label": None},
        {"ts": "2", "source": "tier0", "rule_id": "A", "tier": 0, "action": "pause", "label": None},
        {"ts": "3", "source": "tier0", "rule_id": "B", "tier": 0, "action": "block", "label": None},
    ]
    g = case_ux5.group_verdicts(rows)
    assert [x["count"] for x in g] == [2, 1]


def test_factory_event_rows_fold_simulation_marks() -> None:
    ev = [
        {
            "kind": "gate_run",
            "actor_ref": "r",
            "detail": "simulation gate_aaaaaaaaaaaa: {'agree': 3}",
        },
        {
            "kind": "gate_run",
            "actor_ref": "r",
            "detail": "simulation gate_aaaaaaaaaaaa: {'agree': 2}",
        },
        {
            "kind": "tested",
            "actor_ref": "g",
            "detail": "full gate run gate_bbbbbbbbbbbbbbbb passed",
        },
    ]
    rows = factory_ux5.event_rows(ev)
    assert len(rows) == 2 and rows[0]["kind"] == "simulation" and rows[0]["n"] == 2
    assert rows[0]["counts"] == {"agree": 3} and rows[1]["text"] == "full gate run passed"
    st = factory_ux5.stages(["template", "policy", "checklist", "gate"])
    assert [s["name"] for s in st] == ["u6_stage_define", "u6_stage_build", "u6_stage_test"]


def test_override_text_has_en_and_vi() -> None:
    i18n_ux5.load()
    base = i18n.table()
    for key in ("fa_intro", "st_t0b", "so_none", "u6_next", "u6_save_marks", "u6_grp_rule"):
        assert key in base and all(base[key]), key
    assert key in i18n_ux5.load() or key.startswith("u6_")
    assert i18n.translator("vi", ux5=True)("u6_next") == "Việc cần làm tiếp"
    assert i18n.translator("en", ux5=True)("so_none") == "Nothing to sign"
    assert i18n.translator("en")("so_none") != "Nothing to sign"  # off path unchanged


# ------------------------------------------------------------------ case page
def test_case_story_is_grouped_without_duplicates(ux: Console) -> None:
    cid = _pay07(ux)["case_id"]
    r = ux.get(f"/console/cases/{cid}")
    assert r.status_code == 200
    html = r.text
    assert "Next action" in html and "Waiting for a person: triage." in html
    assert html.index("Next action") < html.index("What happened")
    assert "u6_" not in html and "ux5_g6.css" in html
    # no rules table and no transcript copy inside the story
    assert "Every check on this case" not in html and "[gate]" not in html
    assert 'data-tab="rules"' in html
    assert _words(html) < 700


def test_case_rules_tab_is_one_table(ux: Console) -> None:
    cid = _pay07(ux)["case_id"]
    html = ux.get(f"/console/cases/{cid}/tab/rules").text
    assert html.count("<table") <= 2  # grouped table + closed check details
    assert "Hits" in html and "Check details" in html
    assert "Every check on this case" not in html
    vi = ux.get(f"/console/cases/{cid}/tab/rules?lang=vi").text
    assert "Số lần" in vi


def test_case_transcript_and_evidence_tabs(ux: Console) -> None:
    cid = _pay07(ux)["case_id"]
    t = ux.get(f"/console/cases/{cid}/tab/transcript").text
    assert "Show masked text" in t and "Masked arguments / result" in t
    e = ux.get(f"/console/cases/{cid}/tab/evidence").text
    assert "Chain details" in e and "entries" in e
    assert e.index("entries") < e.index("Chain details")
    full = ux.get(f"/console/cases/{cid}").text
    assert "g6-evid" in full  # one-line evidence card
    assert ux.get(f"/console/cases/{cid}?tab=transcript&page=99").status_code == 200


# ------------------------------------------------------------------ lists
def test_cases_list_ux5(ux: Console) -> None:
    html = ux.get("/console/cases").text
    assert "u5-head" in html and "Refresh cases" not in html
    assert 'list="g6-agents"' in html and "[demo:showcase]" not in html
    assert "Opened by</th>" not in html
    assert "Unassigned" in html or "<td>—</td>" not in html
    vi = ux.get("/console/cases?lang=vi").text
    assert "Vụ việc cần con người quyết định" in vi
    assert ux.get("/console/queue/rows", headers=HX).status_code == 200


def test_evidence_verify_first_and_lanes_paged(ux: Console) -> None:
    html = ux.get("/console/evidence", "admin.chi").text
    assert html.index("Verify now") < html.index(">Lanes<")
    assert "Page 1 of" in html and 'name="q"' in html
    assert ux.get("/console/evidence?q=zzzz-none").text.count('class="lane"') == 0
    assert ux.get("/console/evidence?page=999").status_code == 200
    assert "How to verify offline" in html and "supervisor.evidence.verify" in html
    viewer = ux.get("/console/evidence", "viewer.hoa").text
    assert "supervisor.evidence.verify" not in viewer


def test_small_pages_render(ux: Console) -> None:
    for path, needle in (
        ("/console/alerts", "Alerts"),
        ("/console/signoff", "Sign"),
        ("/console/assurance", "ssurance"),
    ):
        r = ux.get(path)
        assert r.status_code == 200 and needle in r.text and "u5-head" in r.text, path
        assert "python -m supervisor.assurance" not in r.text
        assert "u6_" not in r.text
    assert "No alerts" in ux.get("/console/alerts").text
    assert "Nothing to sign" in ux.get("/console/signoff").text


# ------------------------------------------------------------------ factory
def test_factory_list_is_a_table_without_golden_count(ux: Console) -> None:
    assert create(ux).status_code == 200
    html = ux.get("/console/factory").text
    assert 'data-table="agents"' in html and "Golden set cases" not in html
    assert "Build and test assessment agents." in html and "u6_" not in html
    assert "agent-id" in html  # id placeholder


def test_factory_editor_stages_and_harness_grid(ux: Console) -> None:
    assert create(ux).status_code == 200
    html = ux.get("/console/factory/mr-agent?step=harness").text
    assert "g6-stage" in html and "Define" in html and "Check" in html
    assert 'class="g6-grid"' in html and 'for="g6-budget"' in html
    assert "Token budget per call" in html and "1,000 to 24,000" in html
    assert "> System facts card</label>" in html and "> facts_v1</label>" not in html
    assert html.index('data-step="harness"') < html.index('data-section="events"')
    assert "Event log" in html and "u6_" not in html
    t1 = ux.get("/console/factory/mr-agent?step=template").text
    assert 'class="g6-grid"' in t1 and "Test pack used by the gate" in t1
    vi = ux.get("/console/factory/mr-agent?step=harness&lang=vi").text
    assert "Ghi nhớ" in vi
    # fragments still answer (htmx tabs)
    assert ux.get("/console/factory/mr-agent/step/harness", headers=HX).status_code == 200
    gate_page = ux.get("/console/factory/mr-agent?step=gate&lang=en").text
    assert "data-gate-banner" in gate_page and "How the gate works" in gate_page


def test_simulation_review_questions_and_one_save(
    ux: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "system_inputs", lambda ctx, sid, dim: fake_inputs(sid, dim))
    create(ux)
    assert start(ux, "simulation", systems="sys-a, sys-b").status_code == 200
    run = gate.latest_runs(gate.GateEnv.from_console(ux.ctx), "mr-agent")[0]
    url = f"/console/factory/mr-agent/simulation/{run['run_id']}"
    page = ux.get(url).text
    assert page.count("g6-q") >= 12  # a question on every card
    assert "Does the system record name" in page or "?" in page.split("g6-q", 1)[1][:300]
    assert page.count('data-act="mark"') == 1  # one Save for the page
    assert 'type="radio"' in page and "Save marks" in page
    assert ux.get(url, "viewer.hoa").text.count('data-act="mark"') == 0
    ok = ux.post(
        url + "/mark",
        {
            "sys_1": "sys-a",
            "fid_1": "f-MR-01",
            "mark_1": "agree",
            "orig_1": "||",
            "sys_2": "sys-b",
            "fid_2": "f-MR-01",
            "mark_2": "disagree",
            "cv_2": "pass",
            "orig_2": "||",
            "sys_3": "sys-b",
            "fid_3": "f-MR-02",
            "mark_3": "",
        },
        "reviewer.binh",
    )
    assert ok.status_code == 200 and 'data-count="agree" data-n="1"' in ok.text
    assert 'data-count="disagree" data-n="1"' in ok.text
    # unchanged marks are not rewritten; a disagree without a verdict is refused before any write
    bad = ux.post(
        url + "/mark",
        {"sys_1": "sys-a", "fid_1": "f-MR-02", "mark_1": "disagree", "orig_1": "||"},
        "reviewer.binh",
    )
    assert bad.status_code == 400 and "verdict_needed" in bad.text
    denied = ux.post(
        url + "/mark",
        {"sys_1": "sys-a", "fid_1": "f-MR-01", "mark_1": "agree", "orig_1": "||"},
        "viewer.hoa",
    )
    assert denied.status_code == 403
