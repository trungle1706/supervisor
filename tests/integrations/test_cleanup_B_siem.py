# ruff: noqa: F401, F811 (the evidence conftest fixture ``env`` is imported)
"""Code clean-up batch B (audit N11): a SIEM poll no longer reads the whole chain. The statement
count of an idle poll and of a poll with a few new entries is constant in the chain length, and
the events equal what the old full scan produced on the same seeded chain."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import pytest

from supervisor.adapters.integrations import siem as S
from supervisor.adapters.sql.sqlite import SqliteExecutor
from supervisor.adapters.sql.store import SqlStateStore, SqlTableStore
from tests.evidence.conftest import Env, env, make_writer

from .test_siem_wp21 import ListSink


class Counting(SqliteExecutor):
    reads = 0

    def query(self, *a: Any, **k: Any) -> Any:
        self.reads += 1
        return super().query(*a, **k)


def _stores(env: Env) -> tuple[Counting, SqlTableStore, SqlStateStore]:
    x = Counting(env.adapters.executor.path)
    return x, SqlTableStore(x), SqlStateStore(x, env.clock)


def _decisions(w: Any, env: Env, agent: str, n: int) -> None:
    for i in range(n):
        env.clock.advance(1)
        w.record(
            "gate_decision",
            f"d:{agent}:{i}:{env.clock.now().timestamp()}",
            {"agent_id": agent, "action": "block", "rule_id": "PAY-08", "allow": False},
        )


def _old_poll_events(tables: Any, max_events: int = 10**9) -> list[dict[str, Any]]:
    """The first poll of the old code: scan the whole chain, one payload query per entry."""
    out = []
    for entry in tables.query("chain_entry", order_by=["lane", "seq"]):
        rows = tables.query("chain_payload", {"lane": entry["lane"], "seq": entry["seq"]})
        payload = json.loads(rows[0]["payload"]) if rows else {}
        ev = S.event_from_chain(entry, payload)
        if ev is not None:
            out.append(asdict(ev))
    return sorted(out, key=lambda e: (e["ts"], e["event_id"]))


def _sent(sink: ListSink) -> list[dict[str, Any]]:
    flat = [asdict(e) for b in sink.batches for e in b]
    return sorted(flat, key=lambda e: (e["ts"], e["event_id"]))


def test_first_poll_equals_the_old_full_scan(env: Env) -> None:
    w = make_writer(env)
    for a in ("a1", "a2", "a3"):
        _decisions(w, env, a, 4)
    x, tables, state = _stores(env)
    sink = ListSink()
    S.ChainEventFeed(tables, sink, state).poll()
    assert _sent(sink) == _old_poll_events(tables)


@pytest.mark.parametrize("per_lane", [3, 30])
def test_poll_cost_does_not_grow_with_the_chain(env: Env, per_lane: int) -> None:
    w = make_writer(env)
    for a in ("a1", "a2", "a3"):
        _decisions(w, env, a, per_lane)
    x, tables, state = _stores(env)
    sink = ListSink()
    feed = S.ChainEventFeed(tables, sink, state)
    feed.poll()
    before = x.reads
    assert feed.poll() == 0  # idle
    idle = x.reads - before
    assert idle <= 4  # heads of all lanes, newest root commit (+ its payload)
    _decisions(w, env, "a2", 2)
    before = x.reads
    n = feed.poll()
    assert n >= 2 and x.reads - before <= 8
    ids = [e["event_id"] for e in _sent(sink)]
    assert len(ids) == len(set(ids))


def test_a_lane_that_appears_later_is_found_and_a_restart_continues(env: Env) -> None:
    w = make_writer(env)
    _decisions(w, env, "a1", 3)
    x, tables, state = _stores(env)
    sink = ListSink()
    S.ChainEventFeed(tables, sink, state).poll()
    _decisions(w, env, "late", 2)  # a new lane (the writer commits a root for it)
    restarted = S.ChainEventFeed(tables, sink, state)  # reads the saved cursors and lanes
    restarted.poll()
    restarted.poll()
    assert _sent(sink) == _old_poll_events(tables)
    saved = {r["state_key"] for r in state.query("monitor_state", {"monitor": "siem"})}
    assert {"lanes", "cursor:agent:late", "cursor:agent:a1"} <= saved


def test_old_deployment_with_cursors_but_no_lane_list_scans_once(env: Env) -> None:
    w = make_writer(env)
    _decisions(w, env, "a1", 3)
    _decisions(w, env, "a2", 3)
    x, tables, state = _stores(env)
    sink = ListSink()
    S.ChainEventFeed(tables, sink, state).poll()
    row = state.get("monitor_state", {"monitor": "siem", "state_key": "lanes"})
    assert row is not None
    # what an older version left behind: cursors only
    env.adapters.executor.execute(
        "DELETE FROM monitor_state WHERE state_key = :k",
        {"k": "lanes"},
        param_types={"k": "string"},
    )
    sink2 = ListSink()
    feed = S.ChainEventFeed(tables, sink2, state)
    assert feed.poll() == 0
    _decisions(w, env, "a2", 1)
    assert feed.poll() >= 1


@pytest.mark.parametrize("cap", [1, 3, 5])
def test_batch_cap_gives_the_same_events_as_before(env: Env, cap: int) -> None:
    w = make_writer(env)
    _decisions(w, env, "a1", 5)
    _decisions(w, env, "a2", 4)
    x, tables, state = _stores(env)
    sink = ListSink()
    feed = S.ChainEventFeed(tables, sink, state, max_events=cap)
    for _ in range(40):
        n = feed.poll()
        assert n <= cap
        if n == 0:
            break
    assert _sent(sink) == _old_poll_events(tables)
