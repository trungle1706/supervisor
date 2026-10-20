"""WP-UX2: Sign-off list (cases waiting for a signature) and CaseService.waiting_approvals."""

from __future__ import annotations

import re
from typing import Any

from supervisor.cases.service import TWO_PERSON_SEVERITIES

from .conftest import Console

HX = {"HX-Request": "true"}


def _user(console: Console, uid: str) -> Any:
    return next(u for u in console.ctx.provider.known_users() if u.user_id == uid)


def _triage(console: Console, severity: str | None = None) -> dict[str, Any]:
    """Move the first high / critical open case to triaged (reviewer.an)."""
    svc = console.ctx.cases
    case = next(
        c
        for c in svc.list_cases(statuses=["open"])
        if c["severity"] in TWO_PERSON_SEVERITIES
        and (severity is None or c["severity"] == severity)
    )
    return svc.transition(
        case["case_id"],
        "triaged",
        _user(console, "reviewer.an"),
        case["row_version"],
        assignee="reviewer.an",
    )


def _ids(html: str) -> list[str]:
    return re.findall(r'data-case="(CASE-[0-9A-F]+)"', html)


def _sign(console: Console, case: dict[str, Any], user: str) -> Any:
    cur = console.ctx.cases.get(case["case_id"])
    return console.post(
        f"/console/cases/{case['case_id']}/signoff",
        {
            "decision": "approve",
            "reason": f"statement of {user}",
            "affirm": "yes",
            "row_version": cur["row_version"],
        },
        user=user,
    )


def test_waiting_approvals_accessor(console: Console) -> None:
    svc = console.ctx.cases
    assert svc.waiting_approvals() == []  # open cases are not waiting for a signature yet
    case = _triage(console)
    waiting = svc.waiting_approvals()
    assert [w["case"]["case_id"] for w in waiting] == [case["case_id"]]
    assert waiting[0]["missing"] == 2 and waiting[0]["approvals"] == {}
    assert _sign(console, case, "reviewer.an").status_code == 200
    one = svc.waiting_approvals()[0]
    assert one["missing"] == 1 and list(one["approvals"]) == ["reviewer.an"]
    assert _sign(console, case, "approver.em").status_code == 200
    assert svc.waiting_approvals() == []  # two signatures: nothing waits
    # low and medium cases never wait, whatever their status
    for sev in ("low", "medium"):
        assert svc.waiting_approvals([{**case, "severity": sev, "status": "triaged"}]) == []
    assert svc.waiting_approvals([{**case, "status": "open"}]) == []


def test_list_shows_waiting_cases_and_matches_the_badge(console: Console) -> None:
    empty = console.get("/console/signoff")
    assert empty.status_code == 200 and "Nothing waits for a signature" in empty.text
    case = _triage(console)
    r = console.get("/console/signoff")
    assert r.status_code == 200 and _ids(r.text) == [case["case_id"]]
    assert 'data-missing="2"' in r.text and "0/2" in r.text
    side = r.text.split('<aside class="side"', 1)[1].split("</aside>", 1)[0]
    assert re.search(r'Sign-off <span class="k[^"]*">1</span>', side)
    assert 'aria-current="page"' in side
    _sign(console, case, "reviewer.an")
    r = console.get("/console/signoff")
    assert 'data-missing="1"' in r.text and "1/2" in r.text and "reviewer.an" in r.text
    _sign(console, case, "approver.em")
    assert _ids(console.get("/console/signoff/rows", headers=HX).text) == []


def test_drawer_holds_the_existing_signoff_panel(console: Console) -> None:
    case = _triage(console)
    d = console.get(f"/console/signoff/{case['case_id']}/drawer", headers=HX)
    assert d.status_code == 200 and "<html" not in d.text and 'id="drawer-title"' in d.text
    assert f"/console/cases/{case['case_id']}/signoff" in d.text  # the audited POST
    assert 'id="signoff-panel"' in d.text and 'name="affirm"' in d.text
    # the row button is a plain link to the full sign-off page without JS
    page = console.get("/console/signoff")
    assert f'href="/console/cases/{case["case_id"]}/signoff?lang=en"' in page.text
    # signing from the drawer: audited, two rows, the answer is the panel
    r = _sign(console, case, "reviewer.an")
    assert r.status_code == 200 and "(1/2)" in r.text
    rows = [
        x for x in console.ctx.tables.query("console_action") if x["permission"] == "case.signoff"
    ]
    assert [x["outcome"] for x in rows] == ["attempted", "ok"]


def test_sort_pages_and_bad_input(console: Console) -> None:
    _triage(console)
    ok = console.get("/console/signoff/rows?sort=missing&dir=asc", headers=HX)
    assert ok.status_code == 200 and 'aria-sort="ascending"' in ok.text
    assert console.get("/console/signoff/rows?sort=__class__", headers=HX).status_code == 200
    for q in ("page=2", "page=abc", "page=0"):
        assert console.get(f"/console/signoff/rows?{q}", headers=HX).status_code == 400, q
    assert console.get("/console/signoff/CASE-NOPE/drawer", headers=HX).status_code == 400
    assert console.get("/console/signoff/bad%20id/drawer", headers=HX).status_code == 400


def test_viewer_may_read_but_not_sign(console: Console) -> None:
    case = _triage(console)
    assert console.get("/console/signoff", user="viewer.hoa").status_code == 200
    r = _sign(console, case, "viewer.hoa")
    assert r.status_code == 403
    assert console.ctx.cases.waiting_approvals()[0]["missing"] == 2


def test_vietnamese(console: Console) -> None:
    _triage(console)
    r = console.get("/console/signoff?lang=vi")
    assert r.status_code == 200 and "Phê duyệt" in r.text and "Chữ ký" in r.text
