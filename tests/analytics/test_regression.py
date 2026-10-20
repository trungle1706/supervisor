"""Recorded baseline, CLI, scheduler wiring, off path, and the real gate feeding the rollup."""

from __future__ import annotations

import json
from datetime import UTC, timedelta
from pathlib import Path

import pytest

from supervisor import scheduler as sched_mod
from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import build_adapters
from supervisor.analytics import tools, tools_suggest
from supervisor.analytics import tools as tools_cli
from supervisor.config import load_settings
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import StaticPolicyProvider, load_policy_dir
from supervisor.jobs import bootstrap_schema
from supervisor.monitors.common import MonitorContext
from tests.analytics.conftest import END, NOW, load_events
from tests.gateway.conftest import POLICY_DIR, MemoryEvidence

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tool_analytics"
START = END - timedelta(days=89)


def test_recorded_baseline(ctx, loaded) -> None:
    """The recorded numbers (baseline.json) must not move: the generator and the rollup are
    deterministic, so any change is a behaviour change to review."""
    base = json.loads((FIX / "baseline.json").read_text(encoding="utf-8"))
    events, _ = loaded
    out = tools.rollup(ctx, START, END)
    assert len(events) == base["events"]
    assert out["rows"] == base["rollup_rows_90d"]
    start, end = tools.window_bounds(END, 30)
    got = {
        f"{r['agent_id']}/{r['tool_name']}": {
            k: r[k] for k in next(iter(base["window_30d"].values()))
        }
        for r in tools.summarise(tools.load_daily(ctx.state, start=start, end=end))
    }
    assert got == base["window_30d"]
    sug = tools_suggest.build_all(
        ctx.state, load_settings(), as_of=END,
        policy_dir=FIX / "policies", manifest_dir=FIX / "agents",
    )  # fmt: skip
    assert {
        s["agent_id"]: {
            "remove": s["remove"],
            "undeclared": [e["tool"] for e in s["undeclared"]],
            "confidence": s["confidence"],
        }
        for s in sug
    } == base["suggestion_30d"]


def test_flags_default_off() -> None:
    s = load_settings()
    assert s.tool_analytics_enabled is False and s.console_tools_enabled is False
    assert s.tool_analytics_window_days == 30


def test_scheduler_job_is_gated_by_the_flag(tmp_path) -> None:
    for flag in (False, True):
        settings = load_settings(data_dir=tmp_path / f"d{flag}", tool_analytics_enabled=flag)
        a = build_adapters(settings, clock=FixedClock(NOW))
        bootstrap_schema.run(settings, a)
        ctx = MonitorContext.from_adapters(a, MemoryEvidence())
        job = next(
            j for j in sched_mod.build_jobs(settings, _Rt(a), ctx) if j.name == "tool_analytics"
        )
        assert job.enabled is flag
        if flag:
            load_events(a)
            out = job.fn()  # yesterday and today only
            assert out["rows"] > 0 and out["suggestions"]["files"]
            assert all(Path(p).is_file() for p in out["suggestions"]["files"])
        a.close()


class _Rt:
    chain = None

    def __init__(self, adapters) -> None:
        self.adapters = adapters


def test_scheduler_job_writes_suggestion_files_not_policies(tmp_path) -> None:
    settings = load_settings(data_dir=tmp_path / "d", tool_analytics_enabled=True)
    a = build_adapters(settings, clock=FixedClock(NOW))
    bootstrap_schema.run(settings, a)
    load_events(a)
    ctx = MonitorContext.from_adapters(a, MemoryEvidence())
    before = (POLICY_DIR / "baseline.yaml").read_bytes()
    tools.rollup(ctx, START, END)
    out = tools.run(ctx, settings, days=2, today=END)
    assert (POLICY_DIR / "baseline.yaml").read_bytes() == before
    names = sorted(Path(p).name for p in out["suggestions"]["files"])
    assert names == ["least_privilege_2026-10-20.diff", "least_privilege_2026-10-20.yaml"]
    assert Path(out["suggestions"]["files"][0]).parent == settings.tool_analytics_dir
    a.close()


def test_cli_rollup_report_suggest(capsys, tmp_path) -> None:
    settings = load_settings()
    a = build_adapters(settings, clock=FixedClock(NOW))
    bootstrap_schema.run(settings, a)
    load_events(a)
    a.close()
    day = ["--from", START.isoformat(), "--to", END.isoformat()]
    assert tools_cli.main(["rollup", *day]) == 0
    out = capsys.readouterr().out
    assert out.startswith("[OK] tool rollup") and "1005 rows" in out and "1005 new" in out
    assert tools_cli.main(["rollup", *day]) == 0
    assert "1005 same" in capsys.readouterr().out  # idempotent
    assert tools_cli.main(["report", "--as-of", END.isoformat(), "--days", "30"]) == 0
    rep = capsys.readouterr().out
    rep.encode("ascii")
    assert "agent payments" in rep and "ext_transfer_api" in rep and "p95us" in rep
    assert max(len(line) for line in rep.splitlines()) <= 100  # fits a terminal
    assert (
        tools_cli.main(
            [
                "suggest",
                "--as-of",
                END.isoformat(),
                "--agent",
                "payments",
                "--out",
                str(tmp_path / "o"),
            ]
        )
        == 0
    )
    sug = capsys.readouterr().out
    sug.encode("ascii")
    assert "suggest remove: add_payee" in sug and "nothing was changed" in sug
    assert (tmp_path / "o" / "least_privilege_2026-10-20_payments.diff").is_file()


def test_cli_user_errors_are_fail_lines(capsys) -> None:
    assert tools_cli.main(["suggest", "--agent", "nope", "--as-of", "2026-10-20"]) == 1
    assert capsys.readouterr().out.startswith("[FAIL] tool analytics:")
    assert tools_cli.main(["rollup", "--from", "2026-10-20", "--to", "2026-10-01"]) == 1
    assert capsys.readouterr().out.startswith("[FAIL]")
    with pytest.raises(SystemExit):
        tools_cli.main(["report", "--as-of", "not-a-date"])


def test_help_works(capsys) -> None:
    with pytest.raises(SystemExit) as e:
        tools_cli.main(["--help"])
    assert e.value.code == 0
    assert "rollup" in capsys.readouterr().out


def test_empty_store_reports_no_data(capsys) -> None:
    settings = load_settings()
    a = build_adapters(settings, clock=FixedClock(NOW))
    bootstrap_schema.run(settings, a)
    a.close()
    assert tools_cli.main(["report", "--as-of", "2026-10-20"]) == 0
    assert "no rollup rows" in capsys.readouterr().out
    assert tools_cli.main(["suggest", "--as-of", "2026-10-20"]) == 0
    assert "WARNING: no rollup rows in the window" in capsys.readouterr().out


def test_real_gate_decisions_feed_the_rollup(adapters, ctx) -> None:
    """End to end: Gateway.check -> agent_event (with latency_us) -> rollup -> counts that
    match what the gate answered."""
    clock = FixedClock(NOW)
    gw = Gateway(
        StaticPolicyProvider(load_policy_dir(POLICY_DIR)),
        adapters.tables,
        adapters.state,
        MemoryEvidence(),
        clock,
        tier0b_enabled=False,
    )
    answers = []
    for i in range(6):
        clock.advance(1)
        answers.append(gw.check("payments", "1", "get_balance", {"customer_id": f"C{i % 2}"}))
    clock.advance(1)
    answers.append(gw.check("customer_service", "1", "nonexistent_tool", {}))
    gw.close()
    rows = adapters.tables.query("agent_event")
    assert len(rows) == 7 and all(isinstance(r["latency_us"], int) for r in rows)
    day = NOW.astimezone(UTC).date()
    tools.rollup(ctx, day, day)
    stored = {(r["agent_id"], r["tool_name"]): r for r in ctx.state.query(tools.TABLE)}
    bal = stored[("payments", "get_balance")]
    want_allow = sum(1 for a in answers[:6] if a["allow"])
    assert bal["calls"] == 6 and bal["allows"] == want_allow
    assert bal["blocks"] + bal["pauses"] == 6 - want_allow
    assert bal["distinct_users"] == 2  # two hashed customer ids
    assert bal["p95_us"] >= bal["p50_us"] >= 0
    unk = stored[("customer_service", "nonexistent_tool")]
    assert unk["risk_class"] == "unknown" and unk["allows"] == 0


def test_notebook_is_a_clean_template() -> None:
    """Parses, keeps FILL-ME placeholders, and reads only columns the table has."""
    import ast
    import re

    from supervisor.core.schema import load_model
    from tests.conftest import REPO_ROOT

    text = (REPO_ROOT / "notebooks" / "tool_usage_analytics.py").read_text(encoding="utf-8")
    ast.parse(text)
    assert text.startswith("# Databricks notebook source")
    assert 'CATALOG = "FILL-ME-catalog"' in text and 'SCHEMA = "FILL-ME-schema"' in text
    cols = set(load_model().table("tool_usage_daily").column_names)
    used = set(re.findall(r"\b(?:sum|max|min)\((\w+)\)", text))
    assert used and used <= cols, used - cols
    assert text.isascii()
