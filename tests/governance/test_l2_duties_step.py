"""WP-L2: the Duties step of the register workflow v2 (CONSOLE_REGISTER_DUTIES).

Flag off: six steps and every URL as before. Flag on: seven steps, the matrix rows of a synthetic
draft, the open questions as fields, answers kept in the draft, back and re-run, the submit writes
one obligation_status row per applying duty and one task per duty that is partial or none."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import pytest

from supervisor.governance.register_v2 import duties as dut
from supervisor.governance.register_v2 import model as rm
from supervisor.governance.register_v2 import service as rs

from .conftest import Console
from .test_n3_register import ME, S1, S2, new, rows, step, submit

NAME = "N3 helper"  # the name S1 gives the system
BANNER = "Not legal advice. Bank counsel must confirm."


@pytest.fixture
def reg(on: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    for flag in ("console_register_v2", "console_nav_v3", "agents_api_enabled"):
        monkeypatch.setattr(on.ctx.settings, flag, True)
    return on


@pytest.fixture
def duties(reg: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(reg.ctx.settings, "console_register_duties", True)
    return reg


def draft_to_duties(c: Console, extra2: dict[str, Any] | None = None) -> str:
    """A draft that has finished steps 1 to 3 (the Duties step is step 4)."""
    did = new(c)
    assert step(c, did, 1, S1).status_code == 200
    assert step(c, did, 2, {**S2, **(extra2 or {})}).status_code == 200
    assert step(c, did, 3).status_code == 200
    return did


def page(c: Console, did: str, n: int, query: str = "", lang: str = "en") -> str:
    r = c.get(f"/console/register/{did}/step/{n}?lang={lang}{query}")
    assert r.status_code == 200, r.text[:300]
    return r.text


def get_draft(c: Console, did: str) -> dict[str, Any]:
    return rs.store_of(c.ctx).get(did, ME)


# ------------------------------------------------------------------ model: data-driven steps


def test_model_steps_are_data_driven() -> None:
    assert rm.STEPS == 6 and rm.n_steps(False) == 6 and rm.n_steps(True) == 7
    assert rm.step_keys(False) == ("identify", "ai", "check", "class", "guardians", "review")
    assert rm.step_keys(True)[3] == "duties" and rm.step_keys(True)[2] == "check"
    assert rm.step_keys(True)[4] == "class"  # Decision 33 follows the Duties step
    assert rm.key_of(4, False) == "class" and rm.key_of(4, True) == "duties"
    assert rm.FIELDS_OF_STEP == {1: rm.STEP1, 2: rm.STEP2}
    with pytest.raises(rm.RegisterError):
        rm.key_of(7, False)
    with pytest.raises(rm.RegisterError):
        rm.key_of(8, True)
    # every step has a label for the translations
    assert all(k in rm.LABEL_OF_KEY for k in rm.step_keys(True))


# ------------------------------------------------------------------ flag off


def test_flag_off_six_steps_and_every_url_as_before(reg: Console) -> None:
    assert reg.ctx.settings.console_register_duties is False
    did = new(reg)
    assert step(reg, did, 1, S1).status_code == 200
    assert step(reg, did, 2, S2).status_code == 200
    html = page(reg, did, 1)
    nav = re.search(r'<ol class="wiz-steps rg2-steps".*?</ol>', html, re.S)
    assert nav and nav.group(0).count("<li") == 6
    assert "Duties" not in html and 'data-register="duties"' not in html
    assert 'data-register="step4"' in page(reg, did, 4)  # Decision 33 stays step 4
    assert 'data-register="step5"' in page(reg, did, 5)
    assert 'data-register="review"' in page(reg, did, 6)
    assert reg.get(f"/console/register/{did}/step/7").status_code == 400
    assert step(reg, did, 7).status_code == 400
    assert not dut.enabled(reg.ctx.settings)
    assert rs.total_steps(reg.ctx) == 6


def test_flag_off_submit_writes_no_duty_rows(reg: Console) -> None:
    did = new(reg)
    for n, form in ((1, S1), (2, S2), (3, {}), (4, {}), (5, {"bind_form": "1"})):
        assert step(reg, did, n, form).status_code == 200
    html = page(reg, did, 6)
    assert "review-duties" not in html and "Duty status rows" not in html
    assert submit(reg, did).status_code == 200
    assert rows(reg, "obligation_status") == []
    assert not [t for t in rows(reg, "task") if str(t["template_id"]).startswith("DUTY-")]
    assert get_draft(reg, did)["step"] == 6
    assert "duties_answers" not in get_draft(reg, did)["data"]


def test_flag_needs_register_v2(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(on.ctx.settings, "console_register_duties", True)
    assert on.ctx.settings.console_register_v2 is False
    assert dut.enabled(on.ctx.settings) is False  # the duties flag alone does nothing
    assert on.get("/console/register").status_code == 400
    monkeypatch.setattr(on.ctx.settings, "console_register_v2", True)
    assert dut.enabled(on.ctx.settings) is True
    monkeypatch.setattr(on.ctx.settings, "governance_enabled", False)
    assert dut.enabled(on.ctx.settings) is False


# ------------------------------------------------------------------ flag on: seven steps


def test_flag_on_seven_steps_in_order(duties: Console) -> None:
    did = new(duties)
    assert step(duties, did, 1, S1).status_code == 200
    assert step(duties, did, 2, S2).status_code == 200
    html = page(duties, did, 3)
    nav = re.search(r'<ol class="wiz-steps rg2-steps".*?</ol>', html, re.S)
    assert nav and nav.group(0).count("<li") == 7
    labels = re.findall(r"<li[^>]*>(?:<a[^>]*>)?([^<]+)", nav.group(0))
    assert labels == [
        "Identify",
        "AI information",
        "Pre-deployment check",
        "Duties",
        "Quick risk assessment",
        "Guardian tools",
        "Review and submit",
    ]
    assert step(duties, did, 3).status_code == 200
    assert 'data-register="duties"' in page(duties, did, 4)
    assert 'data-register="step4"' in page(duties, did, 5)  # Decision 33 is step 5 now
    assert 'data-register="step5"' in page(duties, did, 6)  # guardians
    assert 'data-register="review"' in page(duties, did, 7)
    assert duties.get(f"/console/register/{did}/step/8").status_code == 400
    assert duties.get(f"/console/register/{did}/step/0").status_code == 400
    assert step(duties, did, 8).status_code == 400
    # going on from the Duties step leads to Decision 33, the review's back link to guardians
    r = step(duties, did, 4)
    assert (
        r.status_code == 200
        and r.headers["HX-Redirect"].endswith(f"/{did}/step/5?lang=en")
        or (r.headers["HX-Redirect"].endswith(f"/{did}/step/5"))
    )
    assert f"/{did}/step/6" in page(duties, did, 7)


# ------------------------------------------------------------------ the step page


def test_step_renders_matrix_rows_and_questions(duties: Console) -> None:
    did = draft_to_duties(duties)
    html = page(duties, did, 4)
    assert BANNER in html and 'data-register="disclaimer"' in html
    # the summary and the table (default filter: gaps = apply, not fully covered)
    assert 'data-num="duties"' in html and 'data-num="coverage"' in html
    assert 'data-table="duties"' in html
    assert re.search(r'data-duty="[^"]+" data-applies="yes" data-coverage="(partial|none)"', html)
    assert 'data-applies="no"' not in html
    for head in ("Instrument", "Article", "Duty", "Applies", "Coverage"):
        assert f">{head}</th>" in html
    # the open questions are fields named by the question id
    v = dut.view(duties.ctx, get_draft(duties, did))
    assert v["questions"], "a draft that says nothing about hosting must raise questions"
    for q in v["questions"]:
        assert q["id"].startswith("Q-")
        assert f'name="{q["id"]}"' in html and f'data-q="{q["id"]}"' in html
    assert 'name="Q-data_classes"' in html and 'name="Q-model_hosting"' in html
    assert 'data-duties="rerun"' in html
    # the summary counts add up
    s = v["summary"]
    assert s["yes"] + s["no"] + s["needs_answer"] == s["total"] > 100
    assert s["full"] + s["partial"] + s["none"] == s["yes"]
    assert s["tasks"] == s["partial"] + s["none"]
    # filters
    for f, applies in (("yes", "yes"), ("no", "no"), ("needs_answer", "needs_answer")):
        h = page(duties, did, 4, f"&f={f}")
        found = set(re.findall(r'data-applies="(\w+)"', h))
        assert found == {applies}, (f, found)
    allh = page(duties, did, 4, "&f=all")
    assert {"yes", "no"} <= set(re.findall(r'data-applies="(\w+)"', allh))
    # paging keeps 100 rows a page
    assert len(re.findall(r'data-duty="', allh)) == dut.PAGE_SIZE
    assert 'data-duties="pages"' in allh
    p2 = page(duties, did, 4, "&f=all&p=2")
    assert p2.count('data-duty="') == dut.PAGE_SIZE
    assert not set(re.findall(r'data-duty="([^"]+)"', allh)) & set(
        re.findall(r'data-duty="([^"]+)"', p2)
    )
    # a duty whose instrument has an effective date shows it
    assert re.search(r"<td>\d{4}-\d{2}-\d{2}</td></tr>", allh) or re.search(
        r"<td>\d{4}-\d{2}-\d{2}</td></tr>", p2
    )


def test_step_needs_steps_one_and_two(duties: Console) -> None:
    did = new(duties)
    assert step(duties, did, 1, S1).status_code == 200
    html = page(duties, did, 4)
    assert "Finish steps 1 and 2 first." in html and BANNER in html
    assert 'data-table="duties"' not in html
    # saving and moving on is still possible: nothing is asked
    r = step(duties, did, 4)
    assert r.status_code == 200
    assert "duties_answers" not in get_draft(duties, did)["data"]


def test_bad_filter_and_page_are_400(duties: Console) -> None:
    did = draft_to_duties(duties)
    for q in ("&f=bogus", "&f=", "&p=0", "&p=x", "&p=-1", "&p=99999999999", "&f=all&p=%00"):
        r = duties.get(f"/console/register/{did}/step/4?lang=en{q}")
        if q == "&f=":  # an empty filter is the default one
            assert r.status_code == 200, q
        else:
            assert r.status_code == 400, (q, r.status_code)
    # a page beyond the last one shows the last page
    assert 'data-table="duties"' in page(duties, did, 4, "&p=999")


# ------------------------------------------------------------------ the profile


def test_profile_comes_from_the_draft_answers(duties: Console) -> None:
    did = draft_to_duties(
        duties,
        {
            "money_movement": "1",
            "credit_decision": "1",
            "user_segment": "customer",
            "personal_data": "special",
            "human_control": "pre_approval",
            "autonomy_level": "l4_autonomous_bounded",
            "org_role": "both",
        },
    )
    p = dut.profile_of(duties.ctx, get_draft(duties, did))
    assert set(p.agent_classes or ()) == {"payment", "credit_decision", "customer_facing"}
    assert p.agent_classes_complete is True
    assert p.executes_payments is True and p.credit_decisions is True
    assert p.human_approval_before_execution is True
    assert p.customer_facing is True
    assert p.data_classes == ("personal", "sensitive_personal")
    assert p.data_classes_complete is False  # financial data is never asked: a lower bound
    assert p.autonomy == "acts_autonomously"
    assert set(p.roles or ()) == {"deployer", "provider"}
    assert p.cross_border is None and p.model_hosting is None  # unknown stays unknown
    assert p.controls.supervised is True and p.controls.basis == "planned"
    # the answers of the step go on top
    p2 = dut.profile_of(
        duties.ctx, get_draft(duties, did), {"Q-cross_border": True, "Q-model_hosting": "on_prem"}
    )
    assert p2.cross_border is True and p2.model_hosting == "on_prem"
    # internal read-only assistant: no money, no credit
    did2 = draft_to_duties(duties)
    p3 = dut.profile_of(duties.ctx, get_draft(duties, did2))
    assert p3.agent_classes == ("internal_tool",) and p3.executes_payments is False
    assert p3.human_approval_before_execution is None


def test_payment_draft_gets_more_applying_duties(duties: Console) -> None:
    plain = draft_to_duties(duties)
    pay = draft_to_duties(duties, {"money_movement": "1", "human_control": "pre_approval"})
    a = dut.view(duties.ctx, get_draft(duties, plain))["summary"]
    b = dut.view(duties.ctx, get_draft(duties, pay))["summary"]
    assert (a["yes"], a["needs_answer"]) != (b["yes"], b["needs_answer"])


def test_facts_rows_are_optional_and_never_needed(duties: Console) -> None:
    did = draft_to_duties(duties)
    d = get_draft(duties, did)
    assert dut.facts_rows(duties.ctx, d) == 0  # a blank draft has no scanned node
    d["source_kind"], d["source_ref"] = "scan", "app:nothing"
    assert dut.facts_rows(duties.ctx, d) == 0  # no table onboard_facts: skipped, no error
    assert 'data-register="duties"' in page(duties, did, 4)


# ------------------------------------------------------------------ answers


def test_answers_persist_back_and_rerun(duties: Console) -> None:
    did = draft_to_duties(duties)
    before = dut.view(duties.ctx, get_draft(duties, did))
    qids = {q["id"] for q in before["questions"]}
    assert {"Q-cross_border", "Q-model_hosting"} <= qids
    # "Run again" saves the answers and stays on the step
    r = step(
        duties,
        did,
        4,
        {
            "Q-cross_border": "no",
            "Q-model_hosting": "on_prem",
            "Q-data_classes": "personal, financial",
            "run": "1",
        },
    )
    assert r.status_code == 200
    assert r.headers["HX-Redirect"].split("?")[0].endswith(f"/{did}/step/4")
    d = get_draft(duties, did)
    assert d["data"]["duties_answers"] == {
        "Q-cross_border": False,
        "Q-model_hosting": "on_prem",
        "Q-data_classes": ["personal", "financial"],
    }
    assert d["step"] == 4 or d["step"] >= 3  # the furthest step never goes back
    # the matrix ran again on the answers: the answered questions are gone, needs-answer fell
    after = dut.view(duties.ctx, d)
    still_open = {q["id"] for q in after["questions"] if q["open"]}
    assert not {"Q-cross_border", "Q-model_hosting"} & still_open
    # ... but they stay on the page as fields, marked answered, so the person can change them
    kept = {q["id"]: q for q in after["questions"] if not q["open"]}
    assert kept["Q-model_hosting"]["value"] == "on_prem" and kept["Q-cross_border"]["value"] == "no"
    assert after["summary"]["needs_answer"] < before["summary"]["needs_answer"]
    assert after["summary"]["yes"] + after["summary"]["no"] > (
        before["summary"]["yes"] + before["summary"]["no"]
    )
    # go back to step 3 and forward again: the answers are still there and are used
    assert 'data-register="step3"' in page(duties, did, 3)
    html = page(duties, did, 4)
    assert re.search(r'data-q="Q-model_hosting" data-open="no"', html)  # answered, still a field
    assert '<option value="on_prem" selected>' in html
    again = get_draft(duties, did)["data"]["duties_answers"]
    assert again["Q-model_hosting"] == "on_prem"
    # change an answer: the new value replaces the old; a blank makes it unknown again
    assert (
        step(duties, did, 4, {"Q-in_operation_since": "2026-03-01", "run": "1"}).status_code == 200
    )
    assert get_draft(duties, did)["data"]["duties_answers"]["Q-in_operation_since"] == "2026-03-01"
    assert step(duties, did, 4, {"Q-in_operation_since": "", "run": "1"}).status_code == 200
    assert "Q-in_operation_since" not in get_draft(duties, did)["data"]["duties_answers"]
    # an answered question can be shown again if it is asked again: here a field in the form
    # for a question that is not asked still replaces the stored answer
    assert step(duties, did, 4, {"Q-model_hosting": "foreign_cloud", "run": "1"}).status_code == 200
    assert get_draft(duties, did)["data"]["duties_answers"]["Q-model_hosting"] == "foreign_cloud"
    # "Continue" with the same form moves to Decision 33 and keeps the answers
    r = step(duties, did, 4, {"Q-model_hosting": "foreign_cloud"})
    assert r.headers["HX-Redirect"].split("?")[0].endswith(f"/{did}/step/5")
    assert get_draft(duties, did)["data"]["duties_answers"]["Q-model_hosting"] == "foreign_cloud"
    assert get_draft(duties, did)["step"] == 5


def test_answer_form_fields_show_the_stored_value(duties: Console) -> None:
    did = draft_to_duties(duties)
    assert step(duties, did, 4, {"Q-data_classes": "personal", "run": "1"}).status_code == 200
    html = page(duties, did, 4)
    assert 'name="Q-data_classes"' in html and 'value="personal"' in html


def test_bad_answers_are_400_with_the_field(duties: Console) -> None:
    did = draft_to_duties(duties)
    cases = {
        "Q-model_hosting": "mars",
        "Q-cross_border": "maybe",
        "Q-in_operation_since": "yesterday",
        "Q-max_daily_vnd": "12.5",
        "Q-data_classes": "personal,secrets",
        "Q-name": "x",  # not a question of this step
        "Q-nope": "x",
        "Q-autonomy": "x" * 300,
    }
    for field, value in cases.items():
        r = step(duties, did, 4, {field: value, "run": "1"})
        assert r.status_code == 400, (field, r.status_code)
        assert field in r.text, field
    r = step(duties, did, 4, {"Q-data_classes": "personal,secrets"})
    assert r.status_code == 400 and 'value="personal,secrets"' in r.text  # shows what was typed
    assert "duties_answers" not in get_draft(duties, did)["data"]
    # nothing leaked into the other answers; the draft is unchanged and still editable
    assert step(duties, did, 4, {"Q-model_hosting": "on_prem", "run": "1"}).status_code == 200


def test_plain_form_post_redirects_303(duties: Console) -> None:
    did = draft_to_duties(duties)
    r = duties.client.post(
        f"/console/register/{did}/step/4",
        data={"Q-cross_border": "yes"},
        headers={"X-Dev-User": ME, "Sec-Fetch-Site": "same-origin"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"].endswith(f"/{did}/step/5")
    assert get_draft(duties, did)["data"]["duties_answers"] == {"Q-cross_border": True}
    # save for later keeps the answers and goes to the drafts list
    r = step(duties, did, 4, {"Q-model_hosting": "on_prem"}, save=True)
    assert r.status_code == 200 and r.headers["HX-Redirect"] == "/console/register?saved=1"


def test_htmx_fragment_headers(duties: Console) -> None:
    did = draft_to_duties(duties)
    r = step(duties, did, 4, {"Q-cross_border": "no", "run": "1"})
    assert r.status_code == 200 and "HX-Redirect" in r.headers and r.text == ""
    # a rejected post re-renders the step with the message, status 400, the banner and the rows
    r = step(duties, did, 4, {"Q-cross_border": "perhaps"})
    assert r.status_code == 400 and 'data-register="error"' in r.text
    assert BANNER in r.text and 'data-table="duties"' in r.text


# ------------------------------------------------------------------ submit


def test_submit_writes_status_rows_and_gap_tasks(duties: Console) -> None:
    did = draft_to_duties(duties, {"money_movement": "1", "human_control": "pre_approval"})
    assert (
        step(
            duties,
            did,
            4,
            {"Q-cross_border": "no", "Q-model_hosting": "on_prem", "run": "1"},
        ).status_code
        == 200
    )
    assert (
        step(duties, did, 4, {"Q-cross_border": "no", "Q-model_hosting": "on_prem"}).status_code
        == 200
    )
    assert step(duties, did, 5).status_code == 200
    assert step(duties, did, 6, {"bind_form": "1"}).status_code == 200
    review = page(duties, did, 7)
    assert 'data-register="review-duties"' in review and BANNER in review
    d = get_draft(duties, did)
    m = dut.matrix_of(duties.ctx, d)
    applying = [r for r in m.rows if r.applies == "yes"]
    gaps = [r for r in applying if dut.coverage_of(r) in ("partial", "none")]
    assert applying and gaps
    assert f"{len(applying)} duties apply; {len(gaps)} tasks will open" in review
    r = submit(duties, did)
    assert r.status_code == 200 and "HX-Redirect" in r.headers
    sid = rows(duties, "ai_system", name=NAME)[0]["system_id"]
    # --- one obligation_status row per applying duty
    st = rows(duties, "obligation_status", system_id=sid)
    assert len(st) == len(applying) == len({s["obligation_id"] for s in st})
    assert {s["obligation_id"] for s in st} == {r.obligation_id for r in applying}
    by_ob = {s["obligation_id"]: s for s in st}
    for row in applying:
        s = by_ob[row.obligation_id]
        assert s["instrument_id"] == row.instrument_id
        assert s["applies"] == "yes" and s["status"] == "open"
        assert s["coverage"] == dut.coverage_of(row) in ("full", "partial", "none")
        assert s["owner_user"] == ME and s["closing_control"] is None
        assert BANNER in s["note"]
        eff = dut.effective_date(row)
        assert (str(s["due_date"])[:10] if s["due_date"] else None) == (
            eff.isoformat() if eff else None
        )
        assert s["row_version"] == 1 and s["status_id"].startswith("os_")
    # needs_answer and no rows are not written
    assert not {s["obligation_id"] for s in st} & {
        r.obligation_id for r in m.rows if r.applies != "yes"
    }
    # --- one task per duty with coverage partial or none
    tasks = [
        t for t in rows(duties, "task", agent_id=sid) if str(t["template_id"]).startswith("DUTY-")
    ]
    assert len(tasks) == len(gaps)
    assert {t["title"] for t in tasks} == {f"Close duty {r.obligation_id}" for r in gaps}
    for t in tasks:
        assert t["owner_role"] == "owner" and t["status"] == "open" and t["kind"] == "custom"
        assert t["stage"] == "initiation" and not t["required"]
        assert BANNER in t["evidence_ref"]
    # a duty that is fully covered would get no task (none is covered fully today)
    assert not [
        t
        for t in tasks
        if t["title"].split()[-1]
        in {r.obligation_id for r in applying if dut.coverage_of(r) == "full"}
    ]
    # the due date is the effective date of the instrument when it is in the future
    now = duties.ctx.clock.now()
    future = [
        r
        for r in gaps
        if (e := dut.effective_date(r)) and dt.date(e.year, e.month, e.day) > now.date()
    ]
    past = [r for r in gaps if (e := dut.effective_date(r)) and e <= now.date()]
    assert future and past, (len(future), len(past))  # both branches are tested
    by_title = {t["title"]: t for t in tasks}
    for r in future[:5]:
        due = by_title[f"Close duty {r.obligation_id}"]["due_at"]
        assert str(due)[:10] == dut.effective_date(r).isoformat()
    for r in past[:5]:  # in force already: the default period, not a date in the past
        assert (
            str(by_title[f"Close duty {r.obligation_id}"]["due_at"])[:10] >= now.date().isoformat()
        )
    # the result page names the write and its counts; the intake tasks are still opened
    page_ = duties.get(f"/console/register/{did}/result?lang=en").text
    assert "Duty status rows" in page_ and f"{len(applying)} / {len(gaps)}" in page_
    assert {"SYS-INTAKE-CONFIRM", "SYS-INTAKE-CHECKS"} <= {
        t["template_id"] for t in rows(duties, "task", agent_id=sid)
    }
    # the draft keeps the answers, and the audit rows are the same two as before
    assert get_draft(duties, did)["data"]["duties_answers"]["Q-model_hosting"] == "on_prem"
    assert [
        a["outcome"] for a in rows(duties, "console_action") if a["path"].endswith("/submit")
    ] == ["attempted", "ok"]
    # a repeat submit is refused and writes nothing more
    assert submit(duties, did).status_code == 400
    assert len(rows(duties, "obligation_status", system_id=sid)) == len(applying)


def test_write_twice_is_a_no_op(duties: Console) -> None:
    did = draft_to_duties(duties)
    d = get_draft(duties, did)
    first = dut.write(duties.ctx, d, "sys_x", ME, ME)
    second = dut.write(duties.ctx, d, "sys_x", ME, ME)
    assert first["rows"] > 0 and first["tasks"] > 0
    assert second == {"rows": 0, "tasks": 0}
    assert len(rows(duties, "obligation_status", system_id="sys_x")) == first["rows"]


def test_submit_without_step_two_is_refused_before_any_write(duties: Console) -> None:
    did = new(duties)
    assert step(duties, did, 1, S1).status_code == 200
    assert submit(duties, did).status_code == 400
    assert rows(duties, "obligation_status") == []


# ------------------------------------------------------------------ permissions and languages


def test_permissions(duties: Console) -> None:
    did = draft_to_duties(duties)
    url = f"/console/register/{did}/step/4"
    assert duties.get(url, user="viewer.hoa").status_code == 403
    assert duties.post(url, {"Q-cross_border": "no"}, user="viewer.hoa").status_code == 403
    assert duties.get("/console/register/new", user="viewer.hoa").status_code == 403
    # another person with the right gets the answer for a draft that does not exist
    other = duties.get(url, user="reviewer.binh")
    assert other.status_code == 400 and "does not exist" in other.text
    assert duties.post(url, {"Q-cross_border": "no"}, user="reviewer.binh").status_code == 400
    assert "duties_answers" not in get_draft(duties, did)["data"]


@pytest.mark.parametrize("lang", ["en", "vi"])
def test_all_seven_steps_render_in_both_languages(duties: Console, lang: str) -> None:
    did = draft_to_duties(duties)
    assert step(duties, did, 4, {"Q-cross_border": "no", "run": "1"}).status_code == 200
    for n in range(1, 8):
        html = page(duties, did, n, lang=lang)
        assert "rg2_" not in re.sub(r'data-[\w-]+="[^"]*"', "", html), (n, lang)
    html = page(duties, did, 4, lang=lang)
    assert ("Nghĩa vụ" in html) == (lang == "vi")
    assert (BANNER in html) == (lang == "en")
    assert ("Không phải tư vấn pháp lý" in html) == (lang == "vi")
    assert submit(duties, did).status_code == 200
    res = duties.get(f"/console/register/{did}/result?lang={lang}")
    assert res.status_code == 200 and "rg2_" not in re.sub(r'data-[\w-]+="[^"]*"', "", res.text)


def test_drafts_list_and_resume_work_with_seven_steps(duties: Console) -> None:
    did = draft_to_duties(duties)
    assert step(duties, did, 4, {"Q-cross_border": "no"}).status_code == 200
    assert get_draft(duties, did)["step"] == 5
    assert step(duties, did, 7, save=True).status_code == 200  # review: nothing to save
    assert get_draft(duties, did)["step"] == 7
    lst = duties.get("/console/register?lang=en").text
    assert did in lst and "Resume" in lst
    # the furthest-step marker never exceeds the number of steps
    d = get_draft(duties, did)
    assert rs.store_of(duties.ctx).save(d, step=99)["step"] == rm.MAX_STEPS


# ------------------------------------------------------------------ schema


def test_obligation_status_table_in_the_model() -> None:
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[2]
    model = yaml.safe_load((root / "schema" / "model.yaml").read_text(encoding="utf-8"))
    t = model["tables"]["obligation_status"]
    assert t["kind"] == "state" and t["primary_key"] == ["status_id"]
    assert list(t["columns"]) == [
        "status_id",
        "system_id",
        "obligation_id",
        "instrument_id",
        "applies",
        "coverage",
        "status",
        "owner_user",
        "due_date",
        "closing_control",
        "note",
        "created_at",
    ]
    assert t["columns"]["due_date"] == "date?" and t["columns"]["closing_control"] == "string?"
    sqlite = (root / "schema" / "ddl" / "sqlite.sql").read_text(encoding="utf-8")
    delta = (root / "schema" / "ddl" / "databricks.sql").read_text(encoding="utf-8")
    nb = (root / "notebooks" / "bootstrap_and_smoke.py").read_text(encoding="utf-8")
    for text in (sqlite, delta, nb):
        assert "obligation_status" in text
    ddl = sqlite.split("CREATE TABLE IF NOT EXISTS obligation_status (", 1)[1].split(");", 1)[0]
    assert "row_version INTEGER NOT NULL" in ddl and "updated_at TEXT NOT NULL" in ddl
    # the table is the last one of the model (a parallel work package appends after it)
    assert list(model["tables"])[-1] == "obligation_status"


def test_obligation_status_roundtrip(duties: Console) -> None:
    now = duties.ctx.clock.now()
    row = {
        "status_id": "os_t1",
        "system_id": "s1",
        "obligation_id": "VN-X-1",
        "instrument_id": "VN-X",
        "applies": "yes",
        "coverage": "partial",
        "status": "open",
        "owner_user": ME,
        "due_date": "2027-01-01",
        "closing_control": None,
        "note": BANNER,
        "created_at": now,
    }
    duties.ctx.state.insert("obligation_status", row)
    got = rows(duties, "obligation_status", system_id="s1")
    assert (
        len(got) == 1
        and got[0]["row_version"] == 1
        and str(got[0]["due_date"])[:10] == "2027-01-01"
    )
