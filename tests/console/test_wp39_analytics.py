"""WP39: Traces additions, decision_daily rollup (both dialects), Analytics tables and the
Detectors tab, the nine alert use cases on the real store."""

from __future__ import annotations

import re
from datetime import UTC, timedelta
from typing import Any

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.sql.databricks_fake import FakeStatementExecution
from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor
from supervisor.adapters.sql.store import SqlStateStore, SqlTableStore
from supervisor.alerts.engine import evaluate
from supervisor.alerts.rules import load_rules
from supervisor.alerts.signals import load_signals
from supervisor.config import REPO_ROOT
from supervisor.core.schema import load_model
from supervisor.jobs import alerts as alerts_job
from supervisor.jobs import decision_rollup
from supervisor.monitors.common import MonitorContext

from .conftest import Console
from .wp39_fixtures import CORR, plant
from .wp39_helpers import add_decision


def _mctx(c: Console) -> MonitorContext:
    return MonitorContext.from_adapters(c.runtime.adapters, c.runtime.chain)


# --------------------------------------------------------------------------- traces


def test_trace_shows_correlation_chip_and_decision_link(v2console: Console) -> None:
    ids = plant(v2console)
    page = v2console.get(f"/console/traces/{ids['trace']}").text
    assert f"/console/decisions?correlation={CORR}" in page
    assert re.search(r'class="pill teal"[^>]*>\d+ findings<', page)
    span = v2console.get(f"/console/traces/{ids['trace']}/span/{ids['span']}").text
    assert CORR in span and f"/console/decisions?event={ids['a']}" in span


def test_traces_list_filters_on_correlation_id(v2console: Console) -> None:
    ids = plant(v2console)
    add_decision(v2console, corr="corr-other", trace="trace-other")
    page = v2console.get(f"/console/traces?corr={CORR}").text
    assert ids["trace"][:24] in page and "trace-other" not in page
    assert 'id="f-corr"' in page
    assert v2console.get("/console/traces?corr=%3Cb%3E").status_code == 400


def test_traces_flag_off_has_no_correlation_parts(console: Console, monkeypatch: Any) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_traces_enabled", True)
    assert 'id="f-corr"' not in console.get("/console/traces").text
    t = console.ctx.tables.query("agent_event", {"event_type": "gate_decision"}, limit=1)[0][
        "trace_id"
    ]
    assert "findings<" not in console.get(f"/console/traces/{t}").text


# --------------------------------------------------------------------------- rollup


def _seed_known(c: Console) -> None:
    add_decision(c, agent="a-one", status="report", consumer="web", codes=("pii.phone",))
    add_decision(c, agent="a-one", status="report", consumer="web", codes=("pii.phone",))
    add_decision(c, agent="a-one", status="block", consumer="web", gaps=("content_uninspectable",))
    add_decision(c, agent="a-two", status="transform", consumer="app", codes=("pii.person",))
    add_decision(c, agent="a-two", status="allow", not_executed=("timed_out",))


def test_rollup_counts_match_the_events_and_rerun_writes_nothing(v2console: Console) -> None:
    _seed_known(v2console)
    ctx = _mctx(v2console)
    out = decision_rollup.run(ctx, v2console.ctx.settings)
    assert out["inserted"] > 0 and out["updated"] == 0
    again = decision_rollup.run(ctx, v2console.ctx.settings)
    assert (again["inserted"], again["updated"], again["removed"]) == (0, 0, 0)
    assert again["unchanged"] == out["inserted"]
    rows = v2console.ctx.state.query("decision_daily")
    total = sum(r["requests"] for r in rows if r["dimension"] == "total")
    events = v2console.ctx.tables.query("agent_event", {"event_type": "gate_decision"}, limit=10000)
    assert total == len(events)
    one = [r for r in rows if r["dimension"] == "agent" and r["dim_key"] == "a-one"]
    assert sum(r["requests"] for r in one) == 3
    assert sum(r["reports"] for r in one) == 2 and sum(r["blocks"] for r in one) == 1
    assert sum(r["not_evaluated"] for r in one) == 1
    two = [r for r in rows if r["dimension"] == "agent" and r["dim_key"] == "a-two"]
    assert sum(r["not_evaluated"] for r in two) == 1  # the timed_out detector row
    code = [r for r in rows if r["dimension"] == "detector_code" and r["dim_key2"] == "pii.phone"]
    assert sum(r["requests"] for r in code) == 2
    cons = {r["dim_key"]: sum(1 for _ in [r]) for r in rows if r["dimension"] == "consumer"}
    assert {"web", "app"} <= set(cons)
    lat = [r for r in rows if r["dimension"] == "detector_latency" and r["dim_key"] == "dlp_vn"]
    assert lat and all(r["p50_us"] is not None and r["p95_us"] >= r["p50_us"] for r in lat)


def test_rollup_cli_is_ascii_and_has_help() -> None:
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(SystemExit):
        decision_rollup.main(["--help"])
    assert "decision_rollup" in buf.getvalue()


def test_rollup_on_the_delta_dialect_uses_delta_functions(v2console: Console) -> None:
    fake = FakeStatementExecution()
    for _ in range(12):
        fake.add_rows([("d", "STRING")], [], match="SELECT")
    ex = DatabricksRestExecutor(
        fake, warehouse_id="wh", catalog="cat", schema="sch", sleep=lambda s: None
    )
    model = load_model()
    clock = FixedClock(v2console.ctx.clock.now())
    dctx = MonitorContext(
        tables=SqlTableStore(ex, model),
        state=SqlStateStore(ex, clock, model),
        executor=ex,
        model=model,
        clock=clock,
        evidence=v2console.runtime.chain,
    )
    start = v2console.ctx.clock.now().astimezone(UTC)
    decision_rollup._scan(dctx, start - timedelta(days=1), start)
    sql = "\n".join(fake.statements)
    assert (
        "date_format(to_utc_timestamp(" in sql and "get_json_object(e.detector_latency_json" in sql
    )
    assert "json_extract" not in sql and "json_valid" not in sql and "substr(" not in sql
    assert "`cat`.`sch`.`finding`" in sql and "`cat`.`sch`.`agent_event`" in sql
    assert "NOT v.advisory" in sql
    first = next(c for c in fake.calls if c.method == "execute_statement")
    params = {p.name: p for p in first.kwargs["parameters"]}
    assert params["r_from"].type == "TIMESTAMP"


def test_scheduler_lists_the_rollup_only_with_the_flag(v2console: Console) -> None:
    from supervisor import scheduler as sched

    mctx = _mctx(v2console)
    on = sched.build_jobs(v2console.ctx.settings, v2console.runtime, mctx)
    assert "decision_rollup" in {j.name for j in on}
    off = v2console.ctx.settings.model_copy(update={"console_decisions_v2": False})
    assert "decision_rollup" not in {j.name for j in sched.build_jobs(off, v2console.runtime, mctx)}


# --------------------------------------------------------------------------- analytics


def test_gate_tab_tables_and_series(v2console: Console) -> None:
    _seed_known(v2console)
    decision_rollup.run(_mctx(v2console), v2console.ctx.settings)
    page = v2console.get("/console/analytics?tab=gate").text
    for table in ("dd-agent", "dd-consumer", "dd-rule", "dd-detector", "dd-series"):
        assert f'id="{table}"' in page
    body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
    assert "Report" in body and "Transform" in body and "Not evaluated" in body
    # a-one: 3 requests, 2 reports = 6666 bp, 1 block = 3333 bp
    m = re.search(r"a-one 3 2 (\d+) bp 0 0 bp 0 0 bp 1 (\d+) bp", body)
    assert m and m.group(1) == "6666" and m.group(2) == "3333"
    assert 'data-series="blocks"' in page and "<svg" in page


def test_gate_tab_filters_series_to_one_agent(v2console: Console) -> None:
    add_decision(v2console, agent="payments", status="report")
    add_decision(v2console, agent="payments", status="report")
    add_decision(v2console, agent="customer_service", status="report")
    decision_rollup.run(_mctx(v2console), v2console.ctx.settings)
    want = sum(
        r["reports"]
        for r in v2console.ctx.state.query("decision_daily", {"dimension": "agent"})
        if r["dim_key"] == "payments"
    )
    assert want >= 2
    page = v2console.get("/console/analytics?tab=gate&agent=payments").text
    m = re.search(r'data-series="reports">.*?<div class="bignum">(\d+)<', page, re.S)
    assert m and int(m.group(1)) == want


def test_detectors_tab_latency_and_the_indicative_marker(v2console: Console) -> None:
    _seed_known(v2console)
    decision_rollup.run(_mctx(v2console), v2console.ctx.settings)
    page = v2console.get("/console/analytics?tab=detectors").text
    assert 'id="det-latency"' in page and 'data-detector="dlp_vn"' in page
    assert "p50 (us)" in page and "p95 (us)" in page
    assert "GO (indicative)" in page  # the harness marker for a Wilson bound under the threshold
    assert 'id="det-codes"' in page and "pii.phone" in page


def test_analytics_without_rollup_rows_says_how_to_fill_them(v2console: Console) -> None:
    page = v2console.get("/console/analytics?tab=gate").text
    assert "decision_rollup" in page


def test_analytics_lists_the_detectors_tab_with_the_flag(v2console: Console) -> None:
    tabs = re.findall(r'data-tab="(\w+)"', v2console.get("/console/analytics").text)
    assert "detectors" in tabs


# --------------------------------------------------------------------------- alerts on the store


def _rules() -> Any:
    return load_rules(REPO_ROOT / "config" / "alerts.yaml")


def test_pii_in_output_fires_with_a_correlation_id_end_to_end(v2console: Console) -> None:
    plant(v2console)
    settings = v2console.ctx.settings.model_copy(update={"alerts_lag_s": 0})
    out = alerts_job.run(_mctx(v2console), settings)
    assert out["alerts"] >= 1
    rows = v2console.ctx.state.query("alert", {"rule_id": "AL-PII-OUTPUT"})
    assert len(rows) == 1 and rows[0]["correlation_id"] == CORR
    assert rows[0]["agent_id"] == "payments"
    # the Alerts page and its drawer show the id and link to the decision
    drawer = v2console.get(f"/console/alerts/{rows[0]['alert_id']}/drawer").text
    assert CORR in drawer and f"/console/decisions?correlation={CORR}" in drawer
    # the SIEM event carries it too
    from supervisor.adapters.integrations.siem import event_from_alert

    assert event_from_alert(rows[0]).attrs["correlation_id"] == CORR
    # the decision drawer links to the alert
    meta = v2console.get(f"/console/decisions/{plant_c(v2console)}/drawer?tab=metadata").text
    assert f"drawer={rows[0]['alert_id']}" in meta


def plant_c(c: Console) -> str:
    rows = c.ctx.tables.query(
        "agent_event", {"correlation_id": CORR, "event_type": "gate_decision"}
    )
    return str(rows[0]["event_id"])


def test_shadow_agent_with_block_findings_raises_threat_not_enforced(v2console: Console) -> None:
    ctx = _mctx(v2console)
    eid = add_decision(
        v2console, agent="shadow-agent", codes=("injection.ignore_previous",), hint="block"
    )
    now = v2console.ctx.clock.now()
    sigs = load_signals(ctx, now - timedelta(hours=1), now + timedelta(minutes=1))
    # no chain entry for this synthetic row: it counts as enforced, so no alert yet
    f = [s for s in sigs if s.kind == "gate_finding" and s.fields["agent_id"] == "shadow-agent"]
    assert f and f[0].fields["enforcement"] == "enforced"
    assert not evaluate(_rules(), f, only_rules={"AL-THREAT-NOT-ENFORCED"}).fired
    from supervisor.alerts import signals as S

    shadow = S._finding_signals(
        ctx, now - timedelta(hours=1), now + timedelta(minutes=1), {eid: "SHADOW"}
    )
    res = evaluate(_rules(), shadow, only_rules={"AL-THREAT-NOT-ENFORCED"})
    assert len(res.fired) == 1 and res.fired[0].agent_id == "shadow-agent"


def test_coverage_gap_for_an_agent_seen_without_a_decision(v2console: Console) -> None:
    ctx = _mctx(v2console)
    now = v2console.ctx.clock.now()
    add_decision(v2console, agent="payments")  # decided: no gap
    for agent in ("bypass-agent", "Payments "):  # the second is the same agent under another id
        v2console.ctx.tables.append(
            "agent_event",
            [
                {
                    "event_id": f"gap-{abs(hash(agent)) % 10**8:08d}",
                    "ts": now - timedelta(seconds=30),
                    "trace_id": "tg",
                    "span_id": f"sg{len(agent)}",
                    "agent_id": agent,
                    "event_type": "tool_call",
                    "tool_name": "x",
                    "env": "test",
                    "source": "otel",
                    "capture_level": "digest",
                }
            ],
        )
    sigs = load_signals(
        ctx, now - timedelta(hours=1), now + timedelta(seconds=1), gap_window_s=3600
    )
    gaps = {s.fields["agent_id"]: s for s in sigs if s.kind == "coverage_gap"}
    assert "payments" not in gaps and "bypass-agent" in gaps
    assert gaps["bypass-agent"].fields["registered"] is False
    # "Payments " (with a space and a capital) is not a valid id: it is dropped, never alerted
    assert "Payments " not in gaps
    res = evaluate(_rules(), list(gaps.values()), only_rules={"AL-COVERAGE-GAP"})
    assert [f.group_value for f in res.fired] == ["bypass-agent"]


def test_agent_under_two_valid_ids_gives_a_gap_for_the_unknown_one(v2console: Console) -> None:
    ctx = _mctx(v2console)
    now = v2console.ctx.clock.now()
    add_decision(v2console, agent="payments")
    v2console.ctx.tables.append(
        "agent_event",
        [
            {
                "event_id": "alias000000000001",
                "ts": now - timedelta(seconds=20),
                "trace_id": "ta",
                "span_id": "sa",
                "agent_id": "payments-v2",
                "event_type": "llm_call",
                "env": "test",
                "source": "otel",
                "capture_level": "digest",
            }
        ],
    )
    sigs = load_signals(
        ctx, now - timedelta(hours=1), now + timedelta(seconds=1), gap_window_s=3600
    )
    gaps = {s.fields["agent_id"] for s in sigs if s.kind == "coverage_gap"}
    assert gaps == {"payments-v2"}  # both ids are visible; the alias is the one to look at


def test_the_alert_harness_drills_are_go() -> None:
    from supervisor.alerts import drills

    result = drills.run_all()
    assert result["go"], "\n".join(drills.render(result))
    assert {r["rule_id"] for r in result["drills"]} == set(drills.NINE)
    assert all(s["fired_above"] == drills.SWEEP and s["fired_below"] == 0 for s in result["sweeps"])
    assert all(s["alerts"] == 1 for s in result["storms"])
    for s in result["sweeps"]:
        lo, hi = s["fired_above_ci_bp"]
        assert lo < s["fired_above_bp"] <= hi == 10000


def test_each_new_rule_has_a_doc_row() -> None:
    text = (REPO_ROOT / "docs" / "alerts.md").read_text(encoding="utf-8")
    for rule in _rules().rules:
        if rule.id in (
            "AL-COVERAGE-GAP",
            "AL-DETECTOR-FAILED",
            "AL-THREAT-NOT-ENFORCED",
            "AL-SECRETS-OUTPUT",
            "AL-PII-OUTPUT",
            "AL-REDACTION-SPIKE",
            "AL-LATENCY-DEGRADATION",
            "AL-ERROR-RATE",
            "AL-INGRESS-AUTH-ANOMALY",
        ):
            assert f"`{rule.id}`" in text, rule.id


def _observe_verdict(c: Console, eid: str, label: str, agent: str = "payments") -> None:
    c.ctx.tables.append(
        "verdict",
        [
            {
                "verdict_id": f"ob{abs(hash((eid, label))) % 10**16:016d}",
                "ts": c.ctx.clock.now(),
                "trace_id": "t-ob",
                "event_id": eid,
                "agent_id": agent,
                "tier": 0,
                "checker_id": "gate.tier0a",
                "is_mock": False,
                "advisory": False,
                "label": label,
                "action": "log",
                "rule_id": "PAY-OBS",
                "rationale_masked": "observe",
            }
        ],
    )


def test_observe_verdict_rows_raise_threat_not_enforced(v2console: Console) -> None:
    ctx = _mctx(v2console)
    eid = add_decision(v2console, agent="payments", corr="corr-obs", direction="output")
    _observe_verdict(v2console, eid, "observe_would_block")
    now = v2console.ctx.clock.now()
    sigs = load_signals(ctx, now - timedelta(hours=1), now + timedelta(minutes=1))
    obs = [s for s in sigs if s.sid.startswith("observe:")]
    assert len(obs) == 1 and obs[0].fields["enforcement"] == "observe"
    assert obs[0].fields["action_hint"] == "block" and obs[0].fields["correlation_id"] == "corr-obs"
    assert obs[0].fields["direction"] == "output"
    res = evaluate(_rules(), obs, only_rules={"AL-THREAT-NOT-ENFORCED"})
    assert len(res.fired) == 1 and res.fired[0].agent_id == "payments"


def test_response_tab_shows_the_observed_decision_line(v2console: Console) -> None:
    eid = add_decision(v2console, agent="payments")
    plain = _tab(v2console, eid)
    assert "Mode" in plain and "enforce" in plain and "Observed decision" in plain
    _observe_verdict(v2console, eid, "observe_would_pause")
    obs = _tab(v2console, eid)
    assert "observe" in obs and "would have paused (not enforced)" in obs
    assert "Approvals" in obs


def _tab(c: Console, eid: str) -> str:
    html = c.get(f"/console/decisions/{eid}/drawer?tab=response").text
    return html.split('id="tab-body"')[1]
