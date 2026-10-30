"""A transparency run changes nothing the next run can see: the job's own chain records and the
root lane head are not part of the facts."""

from __future__ import annotations

from supervisor.jobs import transparency as job
from supervisor.monitors.common import MonitorContext
from supervisor.transparency.harness import Env


def test_second_run_writes_nothing_after_the_lane_had_records(env: Env) -> None:
    aid = env.svc.facts.running_agents()[0]
    env.rt.chain.record("gate_decision", "probe-1", {"n": 1}, lane=f"agent:{aid}")
    ctx = MonitorContext.from_adapters(env.adapters, env.rt.chain)
    before = env.svc.facts.chain_lane(aid)
    first = job.run(ctx, env.settings)
    assert first["made"] > 0
    assert env.svc.facts.chain_lane(aid) == before  # its own records are not counted
    n_rows = len(env.adapters.tables.query("transparency_report"))
    n_chain = len(env.adapters.tables.query("chain_entry"))
    second = job.run(ctx, env.settings)
    assert second["made"] == 0 and second["unchanged"] == first["agents"] * 3
    assert len(env.adapters.tables.query("transparency_report")) == n_rows
    assert len(env.adapters.tables.query("chain_entry")) == n_chain


def test_root_head_in_the_report_has_no_moving_seq(env: Env) -> None:
    root = env.svc.facts.chain_root()
    assert root is None or "seq" not in root
