"""WP12: Case page - header card, pill tabs (htmx partials), story timeline, decision flow."""

from __future__ import annotations

from .conftest import Console


def _pay07(console: Console) -> dict:
    return next(c for c in console.ctx.cases.list_cases() if "PAY-07" in c["summary"])


def test_case_header_story_and_decision(console: Console) -> None:
    case = _pay07(console)
    r = console.get(f"/console/cases/{case['case_id']}")
    assert r.status_code == 200, r.text
    # header: pills, plain headline from rule + tool, explanation, clocks, Decision 33 line
    assert "opened by the gate" in r.text and 'data-status="open"' in r.text
    assert "paused: a money-moving call (ext_transfer_api) was stopped before it ran" in r.text
    assert "Rule PAY-07 (Payments agent may call approved tools only) paused the agent" in r.text
    assert "SBV 24 h report" in r.text and "SBV 5-day remediation" in r.text
    assert "Decision 33" in r.text
    # pill tabs, Story active
    for tab in ("story", "rules", "transcript", "evidence", "casefile"):
        assert f'hx-get="/console/cases/{case["case_id"]}/tab/{tab}' in r.text
    assert 'data-tab="story" class="on"' in r.text
    # story timeline from real rows: planned call, rule matched with latency, case opened
    assert 'data-key="st_planned"' in r.text and 'data-key="st_rule_pause"' in r.text
    assert "Detect-to-stop" in r.text and 'data-key="ev_open"' in r.text
    assert 'data-key="waiting"' in r.text
    # decision flow: assign first, close disabled with the reason, two-person box
    decide = r.text.split("Your decision", 1)[1]
    assert decide.index("Assign to me") < decide.index("Mark triaged") < decide.index("Close (")
    assert "two different people must sign off" in decide and "disabled" in decide
    assert "Triage the case first." in decide and "ITSM ticket" in decide
    assert "Masked transcript excerpt" in r.text and "[gate] ext_transfer_api" in r.text


def test_case_tabs_are_partials(console: Console) -> None:
    cid = _pay07(console)["case_id"]
    for tab, needle in (
        ("rules", "Every check on this case"),
        ("transcript", "Masked arguments / result"),
        ("evidence", f"agent:{_pay07(console)['agent_id']}"),
        ("casefile", "Open case file (HTML)"),
        ("story", "What happened"),
    ):
        r = console.get(f"/console/cases/{cid}/tab/{tab}")
        assert r.status_code == 200 and needle in r.text, (tab, r.text[:300])
        assert "<html" not in r.text
    full = console.get(f"/console/cases/{cid}?tab=rules")
    assert 'data-tab="rules" class="on"' in full.text
    bad = console.get(f"/console/cases/{cid}/tab/nope", headers={"HX-Request": "true"})
    assert bad.status_code == 400 and "unknown case tab" in bad.text


def test_case_file_view(console: Console) -> None:
    cid = _pay07(console)["case_id"]
    html = console.get(f"/console/cases/{cid}/casefile.html")
    assert html.status_code == 200 and cid in html.text
    js = console.get(f"/console/cases/{cid}/casefile.json")
    assert js.status_code == 200 and js.json()["case_id"] == cid
    bad = console.get(f"/console/cases/{cid}/casefile.exe", headers={"HX-Request": "true"})
    assert bad.status_code == 400


def test_case_page_in_vietnamese(console: Console) -> None:
    cid = _pay07(console)["case_id"]
    r = console.get(f"/console/cases/{cid}?lang=vi")
    assert "Diễn biến" in r.text and "Quyết định của bạn" in r.text and "Giao cho tôi" in r.text
