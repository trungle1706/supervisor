"""Clean-up audit N14: ``ControlService.run_status`` reads ``control_status`` once per pass (it
read twice per agent and once per agent x control), and writes the same rows."""

from __future__ import annotations

import re
from typing import Any

from supervisor.controls.harness_env import CtlEnv


def _build(n_agents: int, n_controls: int) -> CtlEnv:
    env = CtlEnv()
    for i in range(n_agents):
        env.agent(f"ag{i}")
        env.verdict(f"ag{i}", "PAY-02", "block", env.window_time())
    for j in range(n_controls):
        env.control(f"CTL-{j:02d}", agents=["*"], evidence=[("monitor", "oversight")])
    return env


def _count(env: CtlEnv) -> dict[str, int]:
    seen = {"control_status": 0}
    ex = env.adapters.executor
    real = ex.query

    def counting(sql: str, *a: Any, **k: Any) -> Any:
        m = re.search(r'FROM\s+"?(\w+)"?', sql)
        if m and m.group(1) in seen and sql.lstrip().upper().startswith("SELECT"):
            seen[m.group(1)] += 1
        return real(sql, *a, **k)

    ex.query = counting  # type: ignore[method-assign]
    env._unwrap = lambda: setattr(ex, "query", real)  # type: ignore[attr-defined]
    return seen


def _passes(n_agents: int, n_controls: int) -> tuple[int, int, dict[str, Any], dict[str, Any]]:
    env = _build(n_agents, n_controls)
    try:
        seen = _count(env)
        first = env.controls.run_status()
        reads_first = seen["control_status"]
        again = env.controls.run_status()
        reads_both = seen["control_status"]
        env._unwrap()  # type: ignore[attr-defined]
        return reads_first, reads_both - reads_first, first, again
    finally:
        env.close()


def test_status_pass_reads_do_not_grow_with_agents_and_controls() -> None:
    small = _passes(3, 4)
    big = _passes(12, 10)
    assert small[0] == small[1] == big[0] == big[1] == 1
    assert big[2]["controls"] == 120 and big[2]["written"] == 120 and big[2]["repeat"] == 0
    assert big[3]["written"] == 0 and big[3]["repeat"] == 120  # the repeat is still found


def _rows(env: CtlEnv) -> list[tuple[Any, ...]]:
    rows = env.adapters.tables.query("control_status")
    return sorted(
        (r["control_id"], r["agent_id"], r["status"], r["reason"], r["digest"]) for r in rows
    )


def test_batch_and_per_row_reads_write_the_same_rows_with_a_reopen_row() -> None:
    def run(batch: bool) -> tuple[list[tuple[Any, ...]], dict[str, Any], dict[str, Any]]:
        env = _build(4, 3)
        try:
            assert env.controls.run_status()["written"] == 12
            # a reopen row of this window holds the pair; a later pass counts it as held
            env.controls.reopen("CTL-01", "ag2", "event-1")
            if not batch:
                env.adapters.tables.query_by = None  # type: ignore[method-assign,assignment]
            again = env.controls.run_status()
            return _rows(env), again, {"held": again.get("held", 0)}
        finally:
            env.close()

    got, again, held = run(True)
    want, again_ref, held_ref = run(False)
    assert got == want and again == again_ref and held == held_ref
    assert held["held"] == 1 and again["repeat"] == 11 and again["written"] == 0
