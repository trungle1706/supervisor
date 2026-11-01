"""Clean-up audit N1: ``load_signals`` reads the chain payloads and the observe-mode decisions
with a constant number of statements, and returns the same signals as the per-row reads did."""

# ruff: noqa: F401, F811 (the evidence conftest fixture ``env`` is imported)

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest

from supervisor.adapters.sql.store import SqlTableStore
from supervisor.alerts.signals import load_signals
from supervisor.core.schema import load_model
from supervisor.monitors.common import MonitorContext
from tests.evidence.conftest import Env, env, make_writer
from tests.test_store_read_cache import Counting


def _row(table: str, **given: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in load_model().table(table).columns:
        if c.name in given:
            out[c.name] = given[c.name]
        elif c.nullable:
            out[c.name] = None
        else:
            out[c.name] = {"string": "x", "text": "x", "int": 1, "bool": False, "json": {}}.get(
                c.type, "x"
            )
    return out


def _seed(env: Env, n: int, start: int = 0) -> None:
    w = make_writer(env)
    for i in range(start, start + n):
        env.clock.advance(1)
        agent = f"a{i % 3}"
        w.record(
            "gate_decision",
            f"d:{i}",
            {"agent_id": agent, "action": "block", "rule_id": "PAY-08", "allow": False},
        )
        if i % 2:
            w.record("chain_verify", f"cv:{i}", {"ok": i % 6 != 1})
        eid = f"ev{i}"
        env.adapters.tables.append(
            "agent_event",
            [
                _row(
                    "agent_event",
                    event_id=eid,
                    ts=env.clock.now(),
                    agent_id=agent,
                    event_type="gate_decision",
                    correlation_id=f"corr{i}",
                    coverage_json=json.dumps({"direction": "output" if i % 2 else "input"}),
                )
            ],
        )
        env.adapters.tables.append(
            "verdict",
            [
                _row(
                    "verdict",
                    verdict_id=f"vd{i}",
                    ts=env.clock.now(),
                    event_id=eid,
                    agent_id=agent,
                    tier=0,
                    is_mock=False,
                    advisory=False,
                    label="observe_would_block" if i % 3 else "observe_would_pause",
                    action="log",
                    rule_id="PAY-OBS",
                )
            ],
        )
    w.close()


def _signals(env: Env) -> tuple[list[Any], int]:
    x = Counting(env.adapters.executor.path)
    ctx = MonitorContext(
        tables=SqlTableStore(x),
        state=env.adapters.state,
        executor=x,
        model=env.adapters.model,
        clock=env.adapters.clock,
        evidence=None,  # type: ignore[arg-type]
    )
    now = env.clock.now()
    got = load_signals(ctx, now - timedelta(days=1), now + timedelta(seconds=1))
    return got, x.reads


def _shape(sigs: list[Any]) -> list[tuple[Any, ...]]:
    return [(s.sid, s.kind, s.ts, json.dumps(dict(s.fields), sort_keys=True)) for s in sigs]


def test_chain_and_observe_reads_do_not_grow_with_the_window(env: Env, tmp_path) -> None:
    _seed(env, 4)
    small, reads_small = _signals(env)
    _seed(env, 40, start=4)
    big, reads_big = _signals(env)
    assert len(big) > 4 * len(small) // 2
    assert reads_big == reads_small  # a constant number of statements
    kinds = {s.kind for s in big}
    assert {"gate_decision", "chain_verify", "gate_finding"} <= kinds | {"request"}
    observe = [s for s in big if s.sid.startswith("observe:")]
    assert len(observe) == 44  # 4 + 40 observe verdicts
    assert {s.fields["direction"] for s in observe} == {"input", "output"}
    assert all(s.fields["correlation_id"] for s in observe)
    chain = [s for s in big if s.kind == "chain_verify"]
    assert {s.fields["ok"] for s in chain} == {True, False}  # the payloads were found


def test_signals_equal_the_per_row_reads(env: Env) -> None:
    """The reference reads each payload and each event the old way (one query per row)."""
    _seed(env, 12)
    got, _ = _signals(env)
    ref_ctx = MonitorContext.from_adapters(env.adapters, None)  # type: ignore[arg-type]

    class NoBatch:
        """A table store without ``query_by``: ``rows_by`` falls back to one query per key."""

        def __init__(self, inner: Any) -> None:
            self._i = inner

        def query(self, *a: Any, **k: Any) -> Any:
            return self._i.query(*a, **k)

    ref_ctx = MonitorContext(
        tables=NoBatch(env.adapters.tables),  # type: ignore[arg-type]
        state=env.adapters.state,
        executor=env.adapters.executor,
        model=env.adapters.model,
        clock=env.adapters.clock,
        evidence=None,  # type: ignore[arg-type]
    )
    now = env.clock.now()
    want = load_signals(ref_ctx, now - timedelta(days=1), now + timedelta(seconds=1))
    assert _shape(got) == _shape(want)
    assert len(got) > 12
