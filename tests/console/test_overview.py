"""WP12: Overview screen - greeting (vi/en, by ICT hour), live counts from the stores."""

from __future__ import annotations

import datetime as dt
import re
from types import SimpleNamespace

from supervisor.console import readmodels

from .conftest import Console


def _num(html: str, key: str) -> str:
    block = html.split(f'data-num="{key}"', 1)[1]
    return re.search(r'class="bignum[^"]*">\s*([0-9]+\+?)', block).group(1)  # type: ignore[union-attr]


def test_greeting_key_follows_ict_hour() -> None:
    utc = dt.UTC
    assert readmodels.greeting_key(dt.datetime(2026, 10, 15, 1, 0, tzinfo=utc)) == "greet_morning"
    assert readmodels.greeting_key(dt.datetime(2026, 10, 15, 7, 0, tzinfo=utc)) == "greet_afternoon"
    assert readmodels.greeting_key(dt.datetime(2026, 10, 15, 13, 0, tzinfo=utc)) == "greet_evening"
    assert readmodels.greeting_key(dt.datetime(2026, 10, 15, 20, 0, tzinfo=utc)) == "greet_evening"


def test_first_name_and_initials() -> None:
    an = SimpleNamespace(display_name="Nguyễn Văn An", user_id="reviewer.an")
    assert readmodels.first_name(an) == "An" and readmodels.initials(an) == "NA"
    owner = SimpleNamespace(display_name="Payments Ops lead (owner)", user_id="x@y")
    assert readmodels.first_name(owner) == "Payments Ops lead"
    sso = SimpleNamespace(display_name="", user_id="rev@bank.example")
    assert readmodels.first_name(sso) == "rev"


def test_overview_greets_and_counts_from_stores(console: Console) -> None:
    r = console.get("/console/")
    assert r.status_code == 200, r.text
    key = readmodels.greeting_key(console.ctx.clock.now())
    greeting = {"greet_morning": "Good morning", "greet_afternoon": "Good afternoon"}.get(
        key, "Good evening"
    )
    assert f"{greeting}, An" in r.text
    # the four number cards come from the stores
    t = console.ctx.tables
    start = readmodels.day_start(console.ctx.clock.now())
    gates = [e for e in t.query("agent_event", {"event_type": "gate_decision"}) if e["ts"] >= start]
    assert _num(r.text, "checked") == str(len(gates))
    stops = {
        v["event_id"]
        for v in t.query("verdict", {"tier": 0})
        if v["action"] in ("block", "pause") and not v["advisory"] and v["ts"] >= start
    }
    assert _num(r.text, "stopped") == str(len(stops)) == "4"
    assert "3 blocked · 1 paused" in r.text
    open_cases = [c for c in console.ctx.cases.list_cases() if c["status"] != "closed"]
    assert _num(r.text, "cases") == str(len(open_cases))
    assert "1 critical" in r.text
    assert "4 actions were stopped today." in r.text and "3 agents are under supervision." in r.text
    # pillars and the purpose box say what the tool is
    assert "Supervisor watches the AI agents your bank runs." in r.text
    for word in ("Onboard", "Watch", "Prove"):
        assert f"<h4>{word}</h4>" in r.text
    # latest gate decisions link to their cases
    strip = r.text.split('id="latest"', 1)[1].split("</div>\n</div>", 1)[0]
    rows = strip.split('class="ev"')[1:]
    assert rows and all('data-outcome="' in row for row in rows)
    for row in rows:
        if 'data-outcome="blocked"' in row or 'data-outcome="paused"' in row:
            assert "/console/cases/CASE-" in row
    # nav counts
    assert re.search(r"Cases <span class=\"k[^\"]*\">4</span>", r.text)


def test_overview_in_vietnamese(console: Console) -> None:
    r = console.get("/console/?lang=vi")
    assert r.status_code == 200
    assert "Chào buổi" in r.text and ", An" in r.text
    assert "Supervisor giám sát các tác tử AI" in r.text
    assert "Hôm nay 4 thao tác đã bị chặn." in r.text


def test_overview_demo_line_only_on_a_demo_store(console: Console, tmp_path: object) -> None:
    from pathlib import Path

    r = console.get("/console/")
    assert 'data-demo="1"' not in r.text
    marker = Path(console.ctx.settings.data_dir) / ".supervisor-demo"
    marker.write_text("demo\n", encoding="utf-8")
    try:
        r = console.get("/console/")
        assert 'data-demo="1"' in r.text and "demo data" in r.text
    finally:
        marker.unlink()
