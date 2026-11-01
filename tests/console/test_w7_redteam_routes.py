"""W7: the red team pages (flag REDTEAM_TAB): off path, step panel, tab, start, live panel, report,
cancel, RBAC, bad input (HTTP 400, never 500), durable rows and chain record, i18n."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from supervisor.console import i18n
from supervisor.console import redteam_view as rv
from supervisor.console.i18n_redteam import RT
from supervisor.redteam import usecase as uc
from supervisor.redteam.multiturn.catalogue import load_objectives
from tests.governance.conftest import mounted, restore_app  # noqa: F401  (fixtures)

from .conftest import Console

SID = "sys-rt"
HX = {"HX-Request": "true"}
FACTS = {
    "facts": [
        {"kind": "tool", "name": "add_payee", "detail": "risk_class=pii_export; approved=yes"},
        {"kind": "tool", "name": "transfer", "detail": "risk_class=money; approved=yes"},
        {"kind": "tool", "name": "reconcile", "detail": "risk_class=read_only; approved=yes"},
    ]
}


def mk(ctx: Any, sid: str = SID, **kw: Any) -> None:
    row = {
        "system_id": sid,
        "name": kw.pop("name", "Tro ly thanh toan"),
        "owner_user": "nguoi-so-huu",
        "owner_team": "Nhom Thanh toan",
        "business_owner": None,
        "purpose": "Ho tro van hanh thanh toan",
        "system_type": "assistant",
        "org_role": "deployer",
        "user_segment": "internal",
        "personal_data": kw.pop("pd", "identifiable"),
        "money_movement": kw.pop("money", True),
        "credit_decision": False,
        "human_control": "pre_approval",
        "lifecycle_stage": "operation",
        "risk_level": "medium",
        "risk_level_source": "manual",
        "risk_justification": None,
        "decision33_class": "not_high_risk",
        "business_impact": "medium",
        "autonomy_level": "unspecified",
        "status": kw.pop("status", "active"),
        "tags": {"autonomy_limits": json.dumps({"approval_above_vnd": 50_000_000})},
        "created_at": ctx.clock.now(),
        "created_by": "reviewer.an",
    }
    assert not kw, kw
    ctx.state.insert("ai_system", row)


@pytest.fixture
def on(console: Console, mounted: None, monkeypatch: pytest.MonkeyPatch) -> Console:  # noqa: F811
    s = console.ctx.settings
    for flag in (
        "redteam_tab",
        "console_nav_v3",
        "console_systems_enabled",
        "governance_enabled",
        "console_ux5",
    ):
        monkeypatch.setattr(s, flag, True)
    monkeypatch.setattr(rv, "facts_for", lambda ctx: lambda sid: FACTS)
    real = load_objectives()
    keep = [
        o
        for o in real
        if o.lang == "en"
        and (o.family, o.kind)
        in {
            ("echo_chamber", "split_same_payee"),
            ("crescendo", "single_over_limit"),
            ("echo_chamber", "pii_reply_other_customer"),
        }
    ]
    assert len(keep) == 3
    monkeypatch.setattr(
        uc,
        "objectives_for",
        lambda target, langs, items=None: [o for o in keep if o.kind in target.tested_kinds()],
    )
    mk(console.ctx)
    return console


def run_it(c: Console, user: str = "reviewer.an", **form: str) -> str:
    data = {"trials": "1", "langs": "en", "attacker": "templates", "ai_n": "6", **form}
    r = c.post(f"/console/redteam/{SID}/run?where=tab", data, user)
    assert r.status_code == 200, r.text[:400]
    m = re.search(r"(rtu_[0-9a-f]{20})", r.text)
    assert m, r.text[:400]
    uc.join(m.group(1))
    return m.group(1)


# ------------------------------------------------------------------------------ off path

GETS = (
    f"/console/redteam/panel/{SID}",
    "/console/redteam/progress/rtu_" + "0" * 20,
    "/console/redteam/run/rtu_" + "0" * 20,
    "/console/redteam/report/rtu_" + "0" * 20,
)


def test_off_by_default(console: Console) -> None:
    assert console.ctx.settings.redteam_tab is False
    assert console.ctx.settings.redteam_tab_pace_ms == 0


def test_off_every_route_is_400_and_nothing_is_read(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    real = console.ctx.state.query
    monkeypatch.setattr(
        console.ctx.state, "query", lambda t, *a, **k: (seen.append(t), real(t, *a, **k))[1]
    )
    for url in GETS:
        r = console.get(url, "admin.chi", headers=HX)
        assert r.status_code == 400 and "redteam_tab_off" in r.text, url
    for url in (f"/console/redteam/{SID}/run", "/console/redteam/run/rtu_" + "0" * 20 + "/cancel"):
        r = console.post(url, {}, "admin.chi")
        assert r.status_code == 400 and "redteam_tab_off" in r.text, url
    assert "redteam_usecase_run" not in seen


def test_off_the_partial_renders_nothing_and_the_tab_is_absent(
    console: Console,
    mounted: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from supervisor.console import routes

    t = i18n.translator("en")
    tpl = routes._env.get_template("_redteam_step_panel.html")  # noqa: SLF001
    assert tpl.render(t=t, lang="en", system_id=SID, redteam_tab=False).strip() == ""
    assert (
        tpl.render(t=t, lang="en", system_id=SID).strip() == ""
    )  # a caller that never heard of it
    on_ = tpl.render(t=t, lang="en", system_id=SID, redteam_tab=True)
    assert f"/console/redteam/panel/{SID}" in on_ and 'hx-trigger="load"' in on_
    s = console.ctx.settings
    for flag in ("console_nav_v3", "console_systems_enabled", "governance_enabled", "console_ux5"):
        monkeypatch.setattr(s, flag, True)
    mk(console.ctx)
    page = console.get(f"/console/systems/{SID}?lang=en", "admin.chi")
    assert page.status_code == 200 and 'data-tab="redteam"' not in page.text
    assert console.get(f"/console/systems/{SID}?tab=redteam", "admin.chi").status_code == 400
    assert (
        console.get("/console/static/rteam.css").status_code == 200
    )  # the files are always served
    assert console.get("/console/static/rteam.js").status_code == 200


# ------------------------------------------------------------------------------ the panel


def test_the_tab_and_the_loader(on: Console) -> None:
    page = on.get(f"/console/systems/{SID}?tab=redteam&lang=en", "admin.chi")
    assert page.status_code == 200
    assert (
        'data-tab="redteam"' in page.text and f"/console/redteam/panel/{SID}?where=tab" in page.text
    )
    assert "onclick" not in page.text and "onchange" not in page.text
    assert "rteam.css" in page.text


def test_panel_before_a_run(on: Console) -> None:
    r = on.get(f"/console/redteam/panel/{SID}?where=tab&lang=en", "reviewer.an", headers=HX)
    assert r.status_code == 200 and "<html" not in r.text
    assert 'data-never="1"' in r.text and 'data-act="run-redteam"' in r.text
    assert 'data-limit="1"' in r.text and "50,000,000" in r.text
    assert "add_payee" in r.text and "Simulated agent" in r.text
    vi = on.get(f"/console/redteam/panel/{SID}?where=tab&lang=vi", "reviewer.an", headers=HX).text
    assert "Chạy kiểm thử tấn công" in vi and "50.000.000" in vi
    plain = on.get(f"/console/redteam/panel/{SID}", "reviewer.an", follow_redirects=False)
    assert (
        plain.status_code == 303
        and f"/console/systems/{SID}?tab=redteam" in plain.headers["location"]
    )


def test_a_viewer_sees_the_panel_without_the_button_and_cannot_start(on: Console) -> None:
    r = on.get(f"/console/redteam/panel/{SID}?lang=en", "auditor.dung", headers=HX)
    assert r.status_code == 200 and 'data-act="run-redteam"' not in r.text
    assert 'data-readonly="1"' in r.text
    assert (
        on.post(f"/console/redteam/{SID}/run", {"trials": "1"}, "auditor.dung").status_code == 403
    )


def test_the_ai_choice_is_off_without_a_model(on: Console) -> None:
    r = on.get(f"/console/redteam/panel/{SID}?lang=en", "reviewer.an", headers=HX)
    assert 'value="ai" disabled' in r.text and "needs a language model" in r.text


# ------------------------------------------------------------------------------ run and report


def test_run_report_rows_and_chain(on: Console) -> None:
    rid = run_it(on)
    row = on.ctx.state.get("redteam_usecase_run", {"run_id": rid})
    assert row["status"] == "done" and row["verdict"] in ("safe", "conditions", "not_safe")
    assert row["started_by"] == "reviewer.an" and row["evidence_hash"]
    s = row["summary"]
    assert s["attacks"]["n"] == 3 and s["plan"]["total"] == 9 and s["how"]["is_mock_agent"] is True
    texts = " ".join(t["user"] for rep in row["replays"] for t in rep["turns"])
    assert not re.search(r"\d{9,}", texts)  # no long digit runs in the stored text
    page = on.get(f"/console/redteam/report/{rid}?lang=en", "auditor.dung")
    assert page.status_code == 200
    html = page.text
    for marker in (
        'data-verdict="',
        'data-tiles="kpi"',
        'data-section="tried"',
        'data-section="holes"',
        'data-section="replay"',
        'data-section="how"',
    ):
        assert marker in html, marker
    assert "Simulated agent" in html and "mock" in html.lower()
    assert 'data-hole="pii_reply_other_customer"' in html  # no rule covers it: named with a fix
    assert "SVC-09" in html and "Risk team" in html
    assert 'data-capability="credit"' in html  # not tested: the app makes no credit decisions
    assert "data-rt-print" in html and "rteam.js" in html and "onclick" not in html
    assert "Line crossed here" in html
    vi = on.get(f"/console/redteam/report/{rid}?lang=vi", "admin.chi").text
    assert "Báo cáo kiểm thử tấn công" in vi and "Tác tử mô phỏng" in vi
    # the finished run: panel shows the last result, progress asks the page to go to the report
    panel = on.get(
        f"/console/redteam/panel/{SID}?where=step&lang=en", "reviewer.an", headers=HX
    ).text
    assert f'data-last="{rid}"' in panel and f"/console/redteam/report/{rid}" in panel
    prog = on.get(f"/console/redteam/progress/{rid}?where=run", "reviewer.an", headers=HX)
    assert prog.status_code == 200 and prog.headers["HX-Redirect"].endswith(f"/report/{rid}")
    step = on.get(f"/console/redteam/progress/{rid}?where=step&lang=en", "reviewer.an", headers=HX)
    assert 'data-rt="panel"' in step.text
    assert (
        on.get(f"/console/redteam/run/{rid}", "reviewer.an", follow_redirects=False).status_code
        == 303
    )


def test_the_live_panel_while_a_run_goes_and_one_run_per_system(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(on.ctx.settings, "redteam_tab_pace_ms", 300)
    r = on.post(
        f"/console/redteam/{SID}/run?where=step",
        {"trials": "1", "langs": "en", "attacker": "templates", "ai_n": "6"},
        "reviewer.an",
    )
    assert r.status_code == 200
    rid = re.search(r"(rtu_[0-9a-f]{20})", r.text).group(1)  # type: ignore[union-attr]
    assert 'data-rt="live"' in r.text and 'hx-trigger="every 1s"' in r.text
    assert 'role="progressbar"' in r.text and 'data-feed="1"' in r.text
    again = on.post(f"/console/redteam/{SID}/run", {"trials": "1"}, "reviewer.an")
    assert again.status_code == 400 and "run_in_progress" in again.text
    other = on.get(f"/console/redteam/panel/{SID}?where=step&lang=en", "reviewer.an", headers=HX)
    assert 'data-rt="live"' in other.text  # the panel of a running system is the live panel
    page = on.get(f"/console/redteam/run/{rid}?lang=en", "reviewer.an")
    assert page.status_code == 200 and "Test running" in page.text
    cancel = on.post(f"/console/redteam/run/{rid}/cancel?where=run", {}, "reviewer.an")
    assert cancel.status_code == 200 and 'data-cancelling="1"' in cancel.text
    uc.join(rid)
    row = on.ctx.state.get("redteam_usecase_run", {"run_id": rid})
    assert row["status"] == "cancelled" and row["verdict"] == ""
    rep = on.get(f"/console/redteam/report/{rid}?lang=en", "reviewer.an")
    assert rep.status_code == 200 and 'data-run-state="cancelled"' in rep.text
    again = on.post(f"/console/redteam/run/{rid}/cancel", {}, "reviewer.an")
    assert again.status_code == 400 and "not_running" in again.text


def test_a_run_cut_off_by_a_restart_reads_as_failed(on: Console) -> None:
    rid = "rtu_" + "a" * 20
    on.ctx.state.insert(
        "redteam_usecase_run",
        {
            "run_id": rid,
            "system_id": SID,
            "status": "running",
            "verdict": "",
            "started_by": "reviewer.an",
            "started_at": on.ctx.clock.now(),
            "finished_at": None,
            "config": {"plan": {"total": 9}},
            "summary": {},
            "replays": [],
            "error": None,
            "evidence_hash": None,
        },
    )
    page = on.get(f"/console/redteam/report/{rid}?lang=en", "reviewer.an")
    assert page.status_code == 200 and 'data-run-state="failed"' in page.text
    prog = on.get(f"/console/redteam/progress/{rid}?where=step&lang=en", "reviewer.an", headers=HX)
    assert prog.status_code == 200


def test_the_ai_attacker_with_a_fake_model(on: Console) -> None:
    from tests.redteam.test_w7_usecase import FakeChat

    on.ctx.gate_chat = FakeChat()  # type: ignore[attr-defined]
    panel = on.get(f"/console/redteam/panel/{SID}?lang=en", "reviewer.an", headers=HX).text
    assert 'value="ai" disabled' not in panel
    rid = run_it(on, attacker="ai", ai_n="6")
    row = on.ctx.state.get("redteam_usecase_run", {"run_id": rid})
    how = row["summary"]["how"]
    assert how["attacker"] == "llm" and how["attacker_model"] == "fake-attacker-1"
    html = on.get(f"/console/redteam/report/{rid}?lang=en", "reviewer.an").text
    assert "fake-attacker-1" in html


# ------------------------------------------------------------------------------ bad input


@pytest.mark.parametrize(
    "form",
    [{"trials": "7"}, {"trials": "x"}, {"langs": "fr"}, {"attacker": "evil"}, {"ai_n": "99"}],
)
def test_bad_options_are_400(on: Console, form: dict[str, str]) -> None:
    r = on.post(f"/console/redteam/{SID}/run", form, "reviewer.an")
    assert r.status_code == 400, r.text[:200]


def test_the_ai_attacker_without_a_model_is_400(on: Console) -> None:
    r = on.post(f"/console/redteam/{SID}/run", {"attacker": "ai"}, "reviewer.an")
    assert r.status_code == 400 and "model_not_configured" in r.text


def test_unknown_archived_and_nothing_to_test_are_400(on: Console) -> None:
    assert on.post("/console/redteam/nope/run", {}, "reviewer.an").status_code == 400
    assert on.get("/console/redteam/panel/bad%20id", "reviewer.an", headers=HX).status_code == 400
    mk(on.ctx, "sys-old", status="archived", name="Cu")
    r = on.post("/console/redteam/sys-old/run", {}, "reviewer.an")
    assert r.status_code == 400
    for url in (
        "/console/redteam/progress/not-an-id",
        "/console/redteam/report/rtu_" + "9" * 20,
        "/console/redteam/run/xyz",
    ):
        r = on.get(url, "reviewer.an", headers=HX)
        assert r.status_code == 400, (url, r.status_code)
    assert (
        on.post("/console/redteam/run/rtu_" + "9" * 20 + "/cancel", {}, "reviewer.an").status_code
        == 400
    )
    plain = on.client.post(
        f"/console/redteam/{SID}/run", data={}, headers={"X-Dev-User": "reviewer.an"}
    )
    assert plain.status_code == 400  # console actions come from htmx only


# ------------------------------------------------------------------------------ i18n


def test_every_label_has_both_languages_and_the_same_placeholders() -> None:
    for key, (en, vi) in RT.items():
        assert en.strip() and vi.strip(), key
        assert set(re.findall(r"{(\w+)}", en)) == set(re.findall(r"{(\w+)}", vi)), key
    table = i18n.table()
    assert all(k in table for k in RT)


def test_labels_carry_no_setting_name_or_api_path() -> None:
    bad = re.compile(r"REDTEAM|_TAB\b|/console/|/v1/|GATE-AUTONOMY|hash|payload|orchestrator", re.I)
    for key, (en, vi) in RT.items():
        assert not bad.search(en) and not bad.search(vi), key


def test_template_keys_exist() -> None:
    root = Path(i18n.__file__).parent / "templates"
    files = (
        "_redteam_step_panel.html",
        "_redteam_progress.html",
        "redteam_run.html",
        "redteam_report.html",
        "_system_redteam_ux5.html",
    )
    used: set[str] = set()
    for f in files:
        text = (root / f).read_text(encoding="utf-8")
        used |= {k for k in re.findall(r"\bt\('(rt_[a-z0-9_]+)'", text) if not k.endswith("_")}
        for prefix in re.findall(r"\bt\('(rt_[a-z0-9_]+_)' ~", text):
            used |= {k for k in RT if k.startswith(prefix)} or {prefix}
    missing = sorted(k for k in used if k not in RT)
    assert not missing, missing
    from supervisor.console import i18n_redteam as m

    for f in m.FAMILY_KEYS:
        assert f"rt_fam_{f}" in RT and f"rt_famd_{f}" in RT
    for k in uc.NEEDS:
        assert f"rt_kind_{k}" in RT, k
    for c in uc.CAPABILITIES:
        assert f"rt_nt_{c}" in RT, c
    for k in uc.FIXES:
        assert f"rt_fix_{k}" in RT and f"rt_owner_{uc.FIXES[k]['owner']}" in RT
    for r in ("holes", "catch", "escape", "false_alarm", "small", "range"):
        assert f"rt_vr_{r}" in RT
    for v in ("safe", "conditions", "not_safe", "not_tested"):
        assert f"rt_v_{v}" in RT and f"rt_vx_{v}" in RT
