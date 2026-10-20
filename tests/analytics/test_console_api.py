"""Console Tools page and /v1/analytics/tools: flags, RBAC, output, 400s (never 500)."""

# ruff: noqa: F811, F401
from __future__ import annotations

from datetime import timedelta

import pytest

from supervisor.analytics import tools
from supervisor.monitors.common import MonitorContext
from tests.analytics.conftest import batches
from tests.console.conftest import Console, adapters, console, seeded  # noqa: F401, F811
from tests.judge.conftest import MemoryEvidence

OWNER = "payops-lead@example.invalid"


def _seed(console: Console) -> None:
    """40 days of synthetic decisions ending today (the console clock), rolled up."""
    from supervisor.data import tool_usage

    a = console.runtime.adapters
    end = a.clock.now().date()
    for chunk in batches(tool_usage.generate(end_day=end, days=40)):
        a.tables.append("agent_event", [e for e, _ in chunk])
    ctx = MonitorContext.from_adapters(a, MemoryEvidence())
    tools.rollup(ctx, end - timedelta(days=39), end)


def test_tools_page_off_by_default(console: Console) -> None:
    assert console.ctx.settings.console_tools_enabled is False
    assert console.ctx.settings.tool_analytics_enabled is False
    off = console.get("/console/tools")
    assert off.status_code == 400 and "CONSOLE_TOOLS_ENABLED" in off.text
    assert console.get("/console/tools/payments/diff", user=OWNER).status_code == 400
    page = console.get("/console/")
    assert page.status_code == 200 and "/console/tools" not in page.text
    api = console.get("/v1/analytics/tools")
    assert api.status_code == 400 and "TOOL_ANALYTICS_ENABLED" in api.json()["error"]


@pytest.fixture
def on(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(console.ctx.settings, "console_tools_enabled", True)
    monkeypatch.setattr(console.ctx.settings, "tool_analytics_enabled", True)
    _seed(console)
    return console


def test_tools_page_shows_table_and_suggestion(on: Console) -> None:
    r = on.get("/console/tools", user="viewer.hoa")
    assert r.status_code == 200, r.text
    assert 'data-agent="payments"' in r.text and 'data-tool="add_payee"' in r.text
    assert 'data-status="unused"' in r.text and 'data-status="undeclared"' in r.text
    assert "/console/analytics?lang=" in r.text  # nav entry (WP-UX2: Tools is a tab)
    assert "/console/analytics?tab=tools" in r.text
    assert 'data-suggestion="payments"' in r.text and "Suggestion only" in r.text
    # a viewer reads but cannot download
    assert "/diff?days=" not in r.text and "Only the agent owner" in r.text
    own = on.get("/console/tools?agent_id=payments", user=OWNER)
    assert own.status_code == 200 and "/console/tools/payments/diff?days=30" in own.text
    vi = on.get("/console/tools?lang=vi", user="viewer.hoa")
    assert vi.status_code == 200 and "Công cụ" in vi.text


def test_tools_page_is_sortable_and_ascii_numbers(on: Console) -> None:
    def order(html: str) -> list[str]:
        import re

        block = html.split('data-agent="payments"')[1].split("</section>")[0]
        return re.findall(r'data-tool="([a-z_]+)"', block)

    default = order(on.get("/console/tools").text)
    by_calls = order(on.get("/console/tools?sort=calls&dir=desc").text)
    assert by_calls != default and by_calls[0] in ("get_balance", "transfer")
    by_tool = order(on.get("/console/tools?sort=tool&dir=asc").text)
    assert by_tool == sorted(by_tool)
    assert default[0] == "add_payee"  # unused and risky first


def test_tools_page_bad_input_is_400(on: Console) -> None:
    for q in ("sort=nope", "days=abc", "days=0", "days=999", "agent_id=bad$id", "agent_id=nope"):
        r = on.get(f"/console/tools?{q}")
        assert r.status_code == 400, (q, r.status_code)


def test_diff_download_is_owner_only_and_not_a_write(on: Console) -> None:
    assert on.get("/console/tools/payments/diff", user="viewer.hoa").status_code == 403
    assert on.get("/console/tools/payments/diff", user="reviewer.an").status_code == 403
    r = on.get("/console/tools/payments/diff?days=30", user=OWNER)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "attachment" in r.headers["content-disposition"]
    assert r.text.startswith("--- a/policies/baseline.yaml") and "-        not_in:" in r.text
    assert on.get("/console/tools/payments/diff?days=30", user="admin.chi").status_code == 200
    # nothing to change for an agent with no unused tool in the window: a message, not a 500
    assert on.get("/console/tools/credit_prequal/diff?days=30", user=OWNER).status_code == 400
    assert on.get("/console/tools/bad$id/diff", user=OWNER).status_code in (400, 404)
    assert (
        not list(on.ctx.settings.tool_analytics_dir.glob("*"))
        if (on.ctx.settings.tool_analytics_dir.exists())
        else True
    )


def test_api_daily_summary_and_errors(on: Console) -> None:
    r = on.get("/v1/analytics/tools?agent_id=payments", user="viewer.hoa")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["view"] == "daily" and body["window"]["days"] == 30
    assert body["rows"] and {x["agent_id"] for x in body["rows"]} == {"payments"}
    row = body["rows"][0]
    assert isinstance(row["p95_us"], int) and isinstance(row["calls"], int)
    assert "usage_date" in row and "distinct_users" in row
    assert all(isinstance(v, (int, str, type(None))) for v in row.values())  # no floats
    s = on.get("/v1/analytics/tools?agent_id=payments&view=summary&days=30").json()
    assert {x["tool_name"] for x in s["rows"]} >= {"transfer", "ext_transfer_api"}
    (sug,) = s["suggestions"]
    assert sug["remove"] == ["add_payee"] and sug["confidence"] == "ok"
    assert "diff" not in sug or sug["diff"] == ""
    for q in ("view=nope", "days=0", "days=x", "agent_id=bad$id"):
        assert on.get(f"/v1/analytics/tools?{q}").status_code == 400, q
    all_agents = on.get("/v1/analytics/tools").json()["rows"]
    assert {x["agent_id"] for x in all_agents} >= {"payments", "customer_service"}


def test_api_rejects_an_unknown_identity(on: Console) -> None:
    r = on.get("/v1/analytics/tools", user="nobody.here")
    assert 400 <= r.status_code < 500
