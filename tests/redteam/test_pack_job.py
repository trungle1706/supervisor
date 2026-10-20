# ruff: noqa: E501
"""The assurance pack, the launch gate, the nightly job, the scheduler and the 7-day trend."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import build_adapters
from supervisor.assurance.engine import run_packs, validate_output
from supervisor.assurance.gates import assurance_launch_items
from supervisor.assurance.loader import load_packs
from supervisor.assurance.model import RunContext
from supervisor.assurance.targets import DemoAgentTarget
from supervisor.config import load_settings
from supervisor.jobs import bootstrap_schema
from supervisor.jobs import redteam_nightly as job
from supervisor.monitors.common import MonitorContext
from supervisor.redteam.multiturn.harness import THRESHOLDS
from supervisor.redteam.multiturn.trend import PACK_ID, pack_trend, render_trend
from tests.assurance.fakes import FakeAgent
from tests.conftest import REPO_ROOT
from tests.gateway.conftest import MemoryEvidence

PACK = next(p for p in load_packs() if p.id == PACK_ID)


def _ctx(target: Any, **extras: Any) -> RunContext:
    return RunContext(
        target=target, repo_root=REPO_ROOT, data_root=None, data_mode="synthetic", extras=extras
    )


def test_manifest_is_advisory_for_launch_and_thresholds_match_the_harness() -> None:
    assert PACK.launch_gate == "advisory" and not PACK.judge_gate
    assert PACK.requires_capabilities == [] and PACK.targets == ["agent"]
    for t in PACK.thresholds:
        direction, go, no_go = THRESHOLDS[t.metric]
        assert (PACK.metric(t.metric).direction, t.go, t.no_go) == (direction, go, no_go)
    assert {t.metric for t in PACK.thresholds} == set(THRESHOLDS)


@pytest.fixture(scope="module")
def payments_result(tmp_path_factory):  # type: ignore[no-untyped-def]
    target = DemoAgentTarget("payments", tmp_path_factory.mktemp("pk"))
    try:
        res = run_packs([PACK], target, _ctx(target, redteam_trials=2), run_id="run-t")
    finally:
        target.close()
    return res.results[0]


def test_pack_runs_on_the_sandbox_agent_with_integer_metrics(payments_result) -> None:  # type: ignore[no-untyped-def]
    r = payments_result
    assert r.status in ("ok", "warn", "fail") and r.is_mock
    assert r.data_mode == "synthetic" and r.dataset_id.endswith("objectives.jsonl")
    assert len(r.dataset_sha256) == 64
    assert r.n_items == r.metrics["conversations"] >= 30
    assert r.metrics["gate_catch_bp"] == 10000 and r.metrics["unexpected_escape_count"] == 0
    assert r.metrics["known_gap_open_count"] == 2  # two accounts, fresh payee
    for k, v in r.metrics.items():
        assert v is None or type(v) is int, k
    d = r.details
    assert d["agent_model"] == "mock-susceptibility-1" and d["trials_per_objective"] == 2
    assert d["attacker"] == "template" and d["attacker_prompt_version"]
    assert set(d["by_family"]) == {"crescendo", "echo_chamber", "memory_poison", "payload_split",
                                   "policy_puppetry", "tool_poisoning"}  # fmt: skip
    assert d["cells_below_min_trials"] == d["cells_total"]  # n=2 here, and the result says so
    assert d["probes"]["pass"]["bp"] == 10000
    json.dumps(d, allow_nan=False)


def test_runner_output_is_valid_for_the_engine(tmp_path: Path) -> None:
    target = DemoAgentTarget("credit_prequal", tmp_path)
    try:
        from supervisor.assurance.runners.security_multiturn import MultiturnRedteamRunner

        out = MultiturnRedteamRunner().run(PACK, _ctx(target, redteam_trials=3))
    finally:
        target.close()
    assert out.status == "ok" and validate_output(PACK, out) is None and out.is_mock


def test_pack_skips_agents_that_cannot_replay(tmp_path: Path) -> None:
    fake = FakeAgent(capabilities=frozenset({"chat"}))
    res = run_packs([PACK], fake, _ctx(fake), run_id="run-t").results[0]
    assert res.status == "skip" and "capability" in res.reasons[0]  # a skip, never a pass
    fake2 = FakeAgent()  # can replay but is not a sandbox target (no world, no clock)
    res2 = run_packs([PACK], fake2, _ctx(fake2), run_id="run-t").results[0]
    assert res2.status == "skip" and "sandbox" in res2.reasons[0]


def test_max_items_caps_objectives_and_small_n_skips(tmp_path: Path) -> None:
    target = DemoAgentTarget("payments", tmp_path)
    try:
        ctx = RunContext(
            target=target, repo_root=REPO_ROOT, data_root=None, data_mode="synthetic", max_items=3
        )
        res = run_packs([PACK], target, ctx, run_id="run-t").results[0]
    finally:
        target.close()
    assert res.status == "skip" and "pack needs" in res.reasons[0]  # 3 objectives x 2 trials < 30


def test_vendored_data_mode_is_a_skip_not_a_pass(tmp_path: Path) -> None:
    target = DemoAgentTarget("payments", tmp_path)
    try:
        ctx = RunContext(target=target, repo_root=REPO_ROOT, data_root=None, data_mode="vendored")
        res = run_packs([PACK], target, ctx, run_id="run-t").results[0]
    finally:
        target.close()
    assert res.status == "skip"


def test_pack_never_blocks_launch_even_when_it_fails(payments_result) -> None:  # type: ignore[no-untyped-def]
    failing = payments_result
    failing.status = "fail"
    assert assurance_launch_items([failing], [PACK], expect_target_kind="agent") == []


def test_bank_supplied_objectives_replace_the_synthetic_file(tmp_path: Path) -> None:
    from supervisor.redteam.multiturn.catalogue import OBJECTIVES_PATH

    bank = tmp_path / "bank" / PACK_ID
    bank.mkdir(parents=True)
    lines = [
        ln for ln in OBJECTIVES_PATH.read_text(encoding="utf-8").splitlines() if '"payments"' in ln
    ]
    (bank / "objectives.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    target = DemoAgentTarget("payments", tmp_path)
    try:
        ctx = RunContext(
            target=target, repo_root=REPO_ROOT, data_root=tmp_path / "bank", data_mode="auto",
            extras={"redteam_trials": 1, "redteam_langs": "vi,en"},
        )  # fmt: skip
        res = run_packs([PACK], target, ctx, run_id="run-t").results[0]
    finally:
        target.close()
    assert (
        res.data_mode == "bank_supplied_path"
        and res.dataset_id == f"bank/{PACK_ID}/objectives.jsonl"
    )
    assert res.status != "skip", res.reasons


# --------------------------------------------------------------------------- job and trend


@pytest.fixture
def jctx(tmp_path: Path):  # type: ignore[no-untyped-def]
    settings = load_settings(
        sql_backend="sqlite", data_dir=tmp_path / "d", redteam_nightly_trials=1
    )
    clock = FixedClock(datetime(2026, 10, 21, 3, 0, tzinfo=UTC))
    a = build_adapters(settings, clock=clock)
    bootstrap_schema.run(settings, a)
    sink = MemoryEvidence()
    try:
        yield settings, a, MonitorContext.from_adapters(a, sink), sink
    finally:
        a.close()


def test_flag_is_off_by_default_and_scheduler_lists_the_job_only_when_on(jctx) -> None:  # type: ignore[no-untyped-def]
    from supervisor.scheduler import build_jobs

    settings, a, ctx, sink = jctx
    assert settings.redteam_nightly_enabled is False and settings.sched_redteam_s == 86400
    assert load_settings().redteam_attacker_model == ""
    rt = SimpleNamespace(adapters=a, chain=sink, settings=settings)
    assert "redteam_nightly" not in {j.name for j in build_jobs(settings, rt, ctx)}
    settings.redteam_nightly_enabled = True
    jobs = {j.name: j for j in build_jobs(settings, rt, ctx)}
    assert jobs["redteam_nightly"].enabled and jobs["redteam_nightly"].interval_s == 86400


def test_nightly_job_writes_rows_chain_records_traces_and_trend(jctx) -> None:  # type: ignore[no-untyped-def]
    settings, a, ctx, sink = jctx
    out = job.run(ctx, settings, trials=3, agents=("payments", "credit_prequal"))
    assert out["trials"] == 3 and set(out["agents"]) == {"payments", "credit_prequal"}
    rows = a.tables.query("eval_result", {"pack_id": PACK_ID})
    assert {r["target_id"] for r in rows} == {"payments", "credit_prequal"}
    assert all(r["metrics"]["gate_catch_bp"] == 10000 for r in rows)
    recs = sink.of_type("assurance_result")
    assert len(recs) == 2 and all(r["pack_id"] == PACK_ID and r["is_mock"] for r in recs)
    run_dir = Path(out["out_dir"])
    assert (run_dir / "results.json").is_file() and (run_dir / "trend.md").is_file()
    assert not (run_dir / "work").exists()
    trace = run_dir / "multiturn_redteam" / "payments" / "traces.jsonl"
    first = json.loads(trace.read_text(encoding="utf-8").splitlines()[0])
    assert first["turns"][0]["i"] == 1 and "gate_would_stop" in first["turns"][0]
    assert a.tables.query("eval_run", {"run_id": out["run_id"]})
    trend = pack_trend(a.tables, now=a.clock.now())
    assert len(trend) == 7 and trend[-1]["runs"] == 2 and trend[0]["runs"] == 0
    assert trend[-1]["gate_catch_bp_min"] == 10000


def test_standalone_command_is_a_skip_when_the_flag_is_off(
    tmp_path: Path, monkeypatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    from supervisor.monitors import jobctx

    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "d")
    monkeypatch.setattr(job, "standalone", lambda: jobctx.standalone(settings))
    assert job.main([]) == 0
    assert "[SKIP]" in capsys.readouterr().out
    assert job.main(["--force", "--agent", "credit_prequal", "--trials", "1"]) == 0
    out = capsys.readouterr().out
    assert "[OK] redteam_nightly" in out and out.isascii()


def test_assurance_report_appends_the_trend_when_the_pack_is_in_the_run() -> None:
    from supervisor.assurance import cli

    assert hasattr(cli, "_trend_section")


class _Rows:
    """Delta-style store: values come back as strings, as the REST executor returns them
    before casting; the trend must still read them."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def query(
        self, table: str, where: dict[str, Any], order_by: Any = None
    ) -> list[dict[str, Any]]:
        return [r for r in self.rows if all(r.get(k) == v for k, v in where.items())]


def test_trend_reads_delta_style_rows_and_never_invents_a_day() -> None:
    now = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

    def row(days_ago: int, status: str, catch: int, esc: int) -> dict[str, Any]:
        ts = (now - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
        m = {"gate_catch_bp": catch, "unexpected_escape_count": esc, "known_gap_open_count": 6,
             "attack_success_bp": 4000, "conversations": 100, "model_gate_catch_bp": 7000}  # fmt: skip
        d = {"gap_kinds_open": ["split_two_accounts", "score_harvest"]}
        return {"pack_id": PACK_ID, "target_id": "payments", "ts": ts, "status": status,
                "metrics": json.dumps(m), "details": json.dumps(d)}  # fmt: skip

    rows = [row(0, "ok", 10000, 0), row(0, "warn", 9000, 2), row(2, "ok", 10000, 0), row(9, "ok", 1, 1),
            row(1, "skip", 5, 5)]  # fmt: skip
    t = pack_trend(_Rows(rows), now=now)
    assert [r["runs"] for r in t] == [0, 0, 0, 0, 1, 0, 2]
    assert t[-1]["gate_catch_bp_min"] == 9000 and t[-1]["unexpected_escape_max"] == 2
    assert t[-2]["gate_catch_bp_min"] is None  # the skipped row does not count
    text = render_trend(t)
    assert "| 2026-10-20 | 2 | 200 | 9000 | 7000 | 2 | 6 | 4000 |" in text and "2 of 7 days" in text
    # the pooled number (all objectives, mock) and the hole names are printed, never hidden
    assert "all incl. holes, MOCK" in text
    assert (
        "Known holes open on the latest day" in text and "score_harvest, split_two_accounts" in text
    )
    assert pack_trend(_Rows([]), now=now)[0]["runs"] == 0


def test_chain_payload_holds_no_float_and_no_conversation_text(jctx) -> None:  # type: ignore[no-untyped-def]
    settings, a, ctx, sink = jctx
    job.run(ctx, settings, trials=3, agents=("credit_prequal",))
    blob = json.dumps(sink.of_type("assurance_result"))
    assert "Chào" not in blob and '"turns"' not in blob and '"text"' not in blob
