"""WP8: console pages render with seeded data (demo replay behind the real gateway)."""

from __future__ import annotations

import re

from .conftest import Console, add_gate_block


def _case_ids(html: str) -> list[str]:
    return re.findall(r'data-case="(CASE-[0-9A-F]+)"', html)


def test_queue_lists_gate_cases_sorted_with_sbv_clock(console: Console) -> None:
    r = console.get("/console/")
    assert r.status_code == 200, r.text
    ids = _case_ids(r.text)
    assert len(ids) == 4  # DEMO-1..4: one pause, three blocks (different agents / rules)
    rows = [console.ctx.cases.get(c) for c in ids]
    ranks = ["low", "medium", "high", "critical"]
    sev = [ranks.index(c["severity"]) for c in rows]
    assert sev == sorted(sev, reverse=True)
    assert "src-gate" in r.text and "left" in r.text  # source badge + SBV countdown
    assert "Dev identity" in r.text
    vi = console.get("/console/?lang=vi")
    assert "Hàng đợi" in vi.text and vi.cookies.get("sv_lang") == "vi"
    rows_partial = console.get("/console/queue/rows?severity=high&status=all")
    assert rows_partial.status_code == 200 and "<html" not in rows_partial.text
    assert console.get("/").status_code == 200  # / redirects to the console


def test_case_page_shows_rules_excerpts_chain(console: Console) -> None:
    console.get("/console/")
    case = next(
        c for c in console.ctx.cases.list_cases() if "PAY-07" in c["summary"]
    )  # DEMO-1 pause
    r = console.get(f"/console/cases/{case['case_id']}")
    assert r.status_code == 200, r.text
    assert "PAY-07" in r.text and "What happened" in r.text
    assert "Transcript excerpts (masked)" in r.text
    assert f"agent:{case['agent_id']}" in r.text
    v = console.post(f"/console/cases/{case['case_id']}/verify")
    assert v.status_code == 200 and 'data-verify="ok"' in v.text, v.text
    s = console.get(f"/console/cases/{case['case_id']}/signoff")
    assert s.status_code == 200


def test_agents_metrics_export_inbox_render(console: Console) -> None:
    a = console.get("/console/agents")
    assert a.status_code == 200 and 'data-agent="payments"' in a.text
    m = console.get("/console/metrics")
    assert m.status_code == 200 and "Chain status" in m.text
    e = console.get("/console/export")
    assert e.status_code == 200
    add_gate_block(console.runtime.adapters)
    console.post("/console/intake/run")  # intake opens a case -> notice
    i = console.get("/console/inbox")
    assert i.status_code == 200 and "new case" in i.text
    for name in ("htmx.min.js", "console.css", "console.js"):
        assert console.get(f"/console/static/{name}").status_code == 200
    assert console.get("/console/static/../../config.py").status_code == 404
