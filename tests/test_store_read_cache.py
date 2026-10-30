"""STORE_READ_CACHE: a read scope answers state-table reads from one snapshot (off outside it)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.sql.sqlite import SqliteExecutor
from supervisor.adapters.sql.store import SqlStateStore, SqlTableStore, read_scope, scope_active
from supervisor.config import load_settings
from supervisor.jobs.bootstrap_schema import run as bootstrap_run

T0 = dt.datetime(2026, 10, 1, 9, tzinfo=dt.UTC)


class Counting(SqliteExecutor):
    def __init__(self, *a: Any, **k: Any) -> None:
        super().__init__(*a, **k)
        self.reads = 0
        self.writes = 0

    def query(self, *a: Any, **k: Any) -> Any:
        self.reads += 1
        return super().query(*a, **k)

    def execute(self, *a: Any, **k: Any) -> Any:
        self.writes += 1
        return super().execute(*a, **k)


@pytest.fixture
def stores(tmp_path: Path) -> tuple[Counting, SqlStateStore, SqlTableStore]:
    from supervisor.adapters.factory import build_adapters

    s = load_settings(sql_backend="sqlite", data_dir=tmp_path / "d")
    a = build_adapters(s)
    bootstrap_run(s, a)
    x = Counting(a.executor.path)
    return x, SqlStateStore(x, FixedClock(T0)), SqlTableStore(x)


def _agent(i: int, **kw: Any) -> dict[str, Any]:
    row: dict[str, Any] = dict(
        agent_id=f"a{i:03d}", name=f"Agent {i}", owner_user=f"u{i % 2}",
        business_owner=None if i % 3 == 0 else f"b{i % 2}",
        gate_state="RUNNING", status="registered",
    )  # fmt: skip
    row.update(kw)
    return row


def _fill(st: SqlStateStore, n: int = 8) -> None:
    from supervisor.core.schema import load_model

    cols = {c.name: c for c in load_model().table("agent").columns}
    for i in range(n):
        row: dict[str, Any] = {}
        for name, c in cols.items():
            if name in ("row_version", "updated_at"):
                continue
            if name in _agent(i):
                row[name] = _agent(i)[name]
            elif c.nullable:
                row[name] = None
            else:
                row[name] = {"string": "x", "text": "x", "int": 1, "bool": False, "json": {}}.get(
                    c.type, T0 if c.type == "timestamp" else "x"
                )
        st.insert("agent", row)


def test_off_outside_a_scope_every_read_is_sql(stores) -> None:
    x, st, _ = stores
    _fill(st)
    before = x.reads
    for _ in range(3):
        st.query("agent", {"gate_state": "RUNNING"})
    assert x.reads - before == 3 and not scope_active()


def test_scope_reads_the_table_once_and_matches_sql(stores) -> None:
    x, st, _ = stores
    _fill(st)
    cases: list[tuple[dict | None, tuple[str, ...], int | None]] = [
        (None, (), None),
        ({"gate_state": "RUNNING"}, ("-agent_id",), 3),
        ({"business_owner": None}, ("agent_id",), None),
        ({"owner_user": "u1", "gate_state": "RUNNING"}, ("-name", "agent_id"), None),
        ({"updated_at": T0}, ("-business_owner", "agent_id"), 4),
        ({"agent_id": "nope"}, (), None),
        (None, ("business_owner", "-agent_id"), 5),
    ]
    expect = [st.query("agent", w, o, n) for w, o, n in cases]
    before = x.reads
    with read_scope():
        assert scope_active()
        got = [st.query("agent", w, o, n) for w, o, n in cases]
        assert x.reads - before == 1
        assert st.get("agent", {"agent_id": "a001"}) is not None
        assert x.reads - before == 1
    assert got == expect
    assert any(len(g) for g in got)


def test_where_values_equal_snapshot_values(stores) -> None:
    _, st, _ = stores
    _fill(st)
    with read_scope():
        row = st.get("agent", {"agent_id": "a002"})
        assert row is not None
        # a timestamp with another offset, and a naive-free equal instant
        same = row["updated_at"].astimezone(dt.timezone(dt.timedelta(hours=7)))
        assert len(st.query("agent", {"updated_at": same})) == 8
        assert st.query("agent", {"agent_id": "a002", "row_version": 1})
        assert st.query("agent", {"row_version": 2}) == []


def test_write_drops_the_table_and_rows_are_copies(stores) -> None:
    x, st, _ = stores
    _fill(st)
    with read_scope():
        rows = st.query("agent")
        rows[0]["name"] = "changed by caller"
        assert st.query("agent")[0]["name"] != "changed by caller"
        a = st.get("agent", {"agent_id": "a001"})
        assert a is not None
        st.update("agent", {"agent_id": "a001"}, {"name": "renamed"}, a["row_version"])
        assert st.get("agent", {"agent_id": "a001"})["name"] == "renamed"


def test_row_cap_falls_back_to_sql(stores) -> None:
    x, st, _ = stores
    _fill(st)
    with read_scope(max_rows=3):
        before = x.reads
        st.query("agent", {"gate_state": "RUNNING"})
        st.query("agent", {"gate_state": "RUNNING"})
        assert x.reads - before == 3  # one failed load (cap+1 rows), then plain SQL each time
        assert len(st.query("agent")) == 8


def test_append_only_same_query_is_asked_once_until_an_append(stores) -> None:
    x, st, tb = stores
    ev = dict(
        event_id="e1", ts=T0, trace_id="t", span_id="s", agent_id="a1", event_type="tool_call",
        args_hash="h", args_masked="A", result_masked="R", env="dev", source="otel",
        capture_level="masked",
    )  # fmt: skip
    tb.append("agent_event", [ev])
    with read_scope():
        before = x.reads
        assert len(tb.query("agent_event", {"agent_id": "a1"})) == 1
        assert len(tb.query("agent_event", {"agent_id": "a1"})) == 1
        assert x.reads - before == 1
        tb.append("agent_event", [{**ev, "event_id": "e2"}])
        assert len(tb.query("agent_event", {"agent_id": "a1"})) == 2


def test_query_by_matches_per_key_queries(stores) -> None:
    _, _, tb = stores
    rows = [
        dict(event_id=f"e{i}", ts=T0 + dt.timedelta(seconds=i), trace_id="t", span_id="s",
             agent_id=f"a{i % 3}", event_type="gate_decision" if i % 2 else "tool_call",
             args_hash="h", args_masked="A", result_masked="R", env="dev", source="otel",
             capture_level="masked", tool_name=f"tool{i}")
        for i in range(12)
    ]  # fmt: skip
    tb.append("agent_event", rows)
    keys = ["a0", "a1", "a2", "a9"]
    got = tb.query_by(
        "agent_event", "agent_id", keys, columns=["agent_id", "tool_name", "ts"],
        where={"event_type": "gate_decision"}, order_by=("-ts",), per_key_limit=2,
    )  # fmt: skip
    for k in keys:
        want = tb.query("agent_event", {"agent_id": k, "event_type": "gate_decision"}, ("-ts",), 2)
        assert [r["tool_name"] for r in got[k]] == [r["tool_name"] for r in want]
    assert got["a9"] == []
    plain = tb.query_by("agent_event", "agent_id", ["a0"])
    assert len(plain["a0"]) == 4


def test_the_scheduler_job_runs_in_a_scope_only_when_on() -> None:
    from supervisor.scheduler import SupervisorScheduler

    seen: list[bool] = []

    class Ctx:
        clock = FixedClock(T0)

    def fn() -> dict:
        seen.append(scope_active())
        return {}

    def make(rows: int | None) -> SupervisorScheduler:
        sch = SupervisorScheduler.__new__(SupervisorScheduler)
        sch.read_cache_rows = rows
        sch.jobs = {"j": type("J", (), {"fn": staticmethod(fn)})()}
        sch.clock = Ctx.clock
        sch.ctx = Ctx()
        return sch

    import supervisor.scheduler as sm

    orig = sm.put_state
    sm.put_state = lambda *a, **k: None  # the run record is not under test
    try:
        make(None).run_job("j")
        make(100).run_job("j")
    finally:
        sm.put_state = orig
    assert seen == [False, True]


def test_middleware_scopes_get_only() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from supervisor.ops.middleware import ReadScopeMiddleware

    app = FastAPI()

    @app.get("/g")
    def g() -> dict:
        return {"scope": scope_active()}

    @app.post("/p")
    def p() -> dict:
        return {"scope": scope_active()}

    app.add_middleware(ReadScopeMiddleware, max_rows=100)
    c = TestClient(app)
    assert c.get("/g").json() == {"scope": True}
    assert c.post("/p").json() == {"scope": False}
    assert not scope_active()


def test_flag_default_is_off_and_install_is_conditional() -> None:
    from fastapi import FastAPI

    from supervisor.ops import middleware

    assert load_settings(sql_backend="sqlite").store_read_cache is False
    off, on = FastAPI(), FastAPI()
    middleware.install(off, load_settings(sql_backend="sqlite"))
    middleware.install(on, load_settings(sql_backend="sqlite", store_read_cache=True))
    names = lambda a: [m.cls.__name__ for m in a.user_middleware]  # noqa: E731
    assert "ReadScopeMiddleware" not in names(off)
    assert "ReadScopeMiddleware" in names(on)
