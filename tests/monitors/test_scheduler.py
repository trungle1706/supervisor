"""In-process scheduler: fake clock, due jobs, catch-up after restart, leases, wiring."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from supervisor import scheduler as sched_mod
from supervisor.adapters.clock import FixedClock
from supervisor.config import load_settings
from supervisor.monitors.common import MonitorContext
from supervisor.monitors.sweeps import JudgeSweep
from supervisor.scheduler import FileLease, JobSpec, StateLease, SupervisorScheduler
from supervisor.wiring import build_runtime
from tests.monitors.conftest import T0


class Counter:
    def __init__(self, fail: bool = False) -> None:
        self.n = 0
        self.fail = fail

    def __call__(self) -> dict[str, int]:
        self.n += 1
        if self.fail:
            raise RuntimeError("boom")
        return {"n": self.n}


def _sched(adapters, evidence, clock, lease, jobs) -> SupervisorScheduler:
    ctx = MonitorContext.from_adapters(adapters, evidence)
    return SupervisorScheduler(jobs, ctx=ctx, lease=lease, clock=clock)


def test_due_jobs_run_on_interval_with_fake_clock(adapters, evidence, clock, tmp_path) -> None:
    fast, slow, off = Counter(), Counter(), Counter()
    lease = FileLease(tmp_path / "s.lock", ttl_s=60)
    s = _sched(adapters, evidence, clock, lease, [
        JobSpec("fast", 60, fast), JobSpec("slow", 3600, slow), JobSpec("off", 1, off, False),
    ])  # fmt: skip
    assert set(s.tick()) == {"fast", "slow"}  # first tick: never ran -> due
    assert s.tick() == {}
    clock.advance(60)
    assert set(s.tick()) == {"fast"}
    clock.advance(3600)
    assert set(s.tick()) == {"fast", "slow"}
    assert (fast.n, slow.n, off.n) == (3, 2, 0)


def test_restart_catches_up_missed_runs_only(adapters, evidence, clock, tmp_path) -> None:
    a, b = Counter(), Counter()
    lease = FileLease(tmp_path / "s.lock", ttl_s=60)
    jobs = [JobSpec("hourly", 3600, a), JobSpec("daily", 86400, b)]
    _sched(adapters, evidence, clock, lease, jobs).tick()
    clock.advance(2 * 3600)  # process down for 2 h
    restarted = _sched(adapters, evidence, clock, FileLease(tmp_path / "s.lock", 60), jobs)
    assert restarted.due() == ["hourly"]  # last runs come from monitor_state
    clock.advance(60)  # the old holder's lease has expired by now
    assert set(restarted.tick()) == {"hourly"}
    assert (a.n, b.n) == (2, 1)


def test_failing_job_is_recorded_and_others_run(adapters, evidence, clock, tmp_path) -> None:
    bad, good = Counter(fail=True), Counter()
    s = _sched(adapters, evidence, clock, FileLease(tmp_path / "s.lock", 60),
               [JobSpec("bad", 60, bad), JobSpec("good", 60, good)])  # fmt: skip
    runs = s.tick()
    assert runs["bad"].status == "error" and "boom" in (runs["bad"].error or "")
    assert runs["good"].status == "ok" and good.n == 1
    assert s.due() == []  # a failed run waits for its interval too (no hot loop)


def test_file_lease_single_holder(tmp_path: Path) -> None:
    now = T0
    a = FileLease(tmp_path / "x.lock", ttl_s=60, holder="a")
    b = FileLease(tmp_path / "x.lock", ttl_s=60, holder="b")
    assert a.acquire(now) and not b.acquire(now)
    assert a.acquire(now + timedelta(seconds=30))  # renew
    assert not b.acquire(now + timedelta(seconds=80))
    assert b.acquire(now + timedelta(seconds=91))  # a's lease expired
    b.release()
    assert a.acquire(now + timedelta(seconds=92))
    (tmp_path / "x.lock.guard").write_text("")  # another process inside the guard
    assert not b.acquire(now + timedelta(days=1))


def test_state_lease_single_holder(adapters) -> None:
    a = StateLease(adapters.state, ttl_s=60, holder="a")
    b = StateLease(adapters.state, ttl_s=60, holder="b")
    assert a.acquire(T0) and not b.acquire(T0)
    row = adapters.state.get("scheduler_lease", {"lease_name": sched_mod.LEASE_NAME})
    assert row["holder"] == "a" and row["row_version"] >= 1
    assert not b.acquire(T0 + timedelta(seconds=59))
    assert b.acquire(T0 + timedelta(seconds=61))
    b.release()
    assert a.acquire(T0 + timedelta(seconds=62))


def test_two_replicas_do_not_double_run(adapters, evidence, clock) -> None:
    c1, c2 = Counter(), Counter()
    s1 = _sched(adapters, evidence, clock, StateLease(adapters.state, 60, "r1"),
                [JobSpec("job", 60, c1)])  # fmt: skip
    s2 = _sched(adapters, evidence, clock, StateLease(adapters.state, 60, "r2"),
                [JobSpec("job", 60, c2)])  # fmt: skip
    for _ in range(5):
        s1.tick()
        s2.tick()
        clock.advance(61 if c1.n % 2 else 30)
    assert c2.n == 0 and c1.n >= 3


def test_scheduler_setting_defaults() -> None:
    assert load_settings().scheduler_on is True  # laptop mode
    assert load_settings(supervisor_mode="dev").scheduler_on is False
    assert load_settings(scheduler_enabled=False).scheduler_on is False
    s = load_settings(supervisor_mode="databricks_app", scheduler_enabled=True,
                      sql_backend="sqlite")  # fmt: skip
    assert s.scheduler_on is True
    for flag in ("drift_enabled", "fairness_enabled", "metrics_enabled", "multiagent_enabled",
                 "quality_enabled", "require_caller_id", "judge_enabled"):  # fmt: skip
        assert getattr(load_settings(), flag) is False, flag


@pytest.fixture
def runtime(tmp_path: Path, clock: FixedClock):
    from supervisor.adapters.factory import build_adapters

    def _make(**overrides: Any):
        settings = load_settings(**overrides)
        rt = build_runtime(settings, adapters=build_adapters(settings, clock=clock))
        made.append(rt)
        return settings, rt

    made: list[Any] = []
    yield _make
    for rt in made:
        rt.close()
        rt.adapters.close()


def test_build_jobs_defaults_and_anchor_seals_chain(runtime, clock) -> None:
    settings, rt = runtime()
    s = sched_mod.build_scheduler(settings, rt)
    enabled = sorted(j.name for j in s.jobs.values() if j.enabled)
    assert enabled == ["anchor", "case_intake", "ingest"]  # every monitor is off by default
    rt.chain.record("note", "n1", {"agent_id": "payments", "i": 1})
    runs = s.tick()
    assert runs["anchor"].status == "ok", runs["anchor"].error
    assert runs["ingest"].status == "ok", runs["ingest"].error
    assert rt.adapters.tables.query("anchor", {}) != []
    s.lease.release()


def test_build_jobs_all_flags_run(runtime, clock) -> None:
    settings, rt = runtime(drift_enabled=True, fairness_enabled=True, metrics_enabled=True,
                           retention_enabled=True,
                           siem_enabled=True, alerts_enabled=True,
                           multiagent_enabled=True, quality_enabled=True, judge_enabled=True,
                           llm_mock=True, judge_t1_family="llama",
                           judge_t2_family="mistral")  # fmt: skip
    s = sched_mod.build_scheduler(settings, rt)
    assert all(j.enabled for j in s.jobs.values()), [j.name for j in s.jobs.values()]
    runs = s.tick()
    assert {n: r.status for n, r in runs.items()} == {n: "ok" for n in s.jobs}, {
        n: r.error for n, r in runs.items()
    }
    s.lease.release()


def test_case_intake_job_registered_and_runs_under_lease(runtime, clock) -> None:
    settings, rt = runtime(sched_case_intake_s=7)
    s = sched_mod.build_scheduler(settings, rt)
    job = s.jobs["case_intake"]
    assert job.enabled and job.interval_s == 7
    assert load_settings().sched_case_intake_s == 30
    assert "case_intake" in sched_mod.STARTUP_JOBS
    runs = s.run_now(list(sched_mod.STARTUP_JOBS))  # the immediate run at scheduler start
    assert runs["case_intake"].status == "ok", runs["case_intake"].error
    other = sched_mod.FileLease(settings.scheduler_lock_path, 60, holder="other")
    assert other.acquire(clock.now()) is False  # s holds the lease
    s.lease.release()
    # a replica without the lease runs nothing
    assert other.acquire(clock.now())
    assert s.run_now(["case_intake"]) == {}
    other.release()


def test_start_and_stop_apscheduler(runtime) -> None:
    settings, rt = runtime()
    s = sched_mod.start_for_runtime(settings, rt)
    try:
        assert s is not None and s.running and sched_mod.current() is s
        assert sched_mod.start_for_runtime(settings, rt) is s  # once per process
    finally:
        sched_mod.stop()
    assert sched_mod.current() is None and not s.running
    off = load_settings(scheduler_enabled=False)
    assert sched_mod.start_for_runtime(off, rt) is None


# --------------------------------------------------------------------- judge sweep


@dataclass
class _CR:
    kind: str
    agent_id: str
    severity: str
    reason: str
    trace_ids: tuple[str, ...] = ("t1",)
    verdict_ids: tuple[str, ...] = ("v1",)


@dataclass
class _Out:
    case_requests: list[_CR] = field(default_factory=list)


class FakeJudge:
    def __init__(self) -> None:
        self.seen: list[int] = []

    def evaluate_window(self, events):  # noqa: ANN001, ANN201
        self.seen.append(len(events))
        return [
            _Out([_CR("open_case", "payments", "medium", "agree")]),
            _Out([_CR("raise_severity", "payments", "critical", "repeat")]),
        ]


def test_judge_sweep_cursor_and_cases(adapters, evidence, clock) -> None:
    from supervisor.monitors.seed import _event, as_rows

    ctx = MonitorContext.from_adapters(adapters, evidence)
    adapters.tables.append("agent_event", as_rows([
        _event(T0 + timedelta(seconds=10), "payments", "1", "tool_call", tool="transfer"),
        _event(T0 + timedelta(seconds=20), "payments", "1", "gate_decision", tool="transfer"),
    ]))  # fmt: skip
    judge = FakeJudge()
    sweep = JudgeSweep(ctx, judge, settle_s=60)
    clock.advance(30)
    assert sweep.run().events == 0  # not settled yet
    clock.advance(60)
    res = sweep.run()
    assert judge.seen == [1]  # gate decisions are skipped
    assert len(res.cases_opened) == 1 and res.cases_raised == res.cases_opened
    case = adapters.state.get("cases", {"case_id": res.cases_opened[0]})
    assert case["case_type"] == "judge" and case["severity"] == "critical"
    clock.advance(600)
    assert sweep.run().events == 0  # cursor moved past the events
