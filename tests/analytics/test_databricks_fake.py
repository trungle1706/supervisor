"""Rollup on the Databricks path, with the recorded fake (no network).

The fake cannot run SQL, so the test records what SQLite answers to the three rollup queries
and replays those answers, as REST strings, to the Databricks executor. This proves (1) the
statements are the Delta dialect, with typed timestamp parameters, (2) the string results are
cast back to the same groups, (3) the write path inserts one row per group.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.sql.databricks_fake import FakeStatementExecution, dml_result
from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor
from supervisor.adapters.sql.store import SqlStateStore, SqlTableStore
from supervisor.analytics import tools
from supervisor.core.schema import load_model
from supervisor.monitors.common import MonitorContext
from tests.analytics.conftest import END, NOW
from tests.judge.conftest import MemoryEvidence

T_FROM = datetime.combine(END - timedelta(days=2), datetime.min.time(), tzinfo=UTC)
T_TO = datetime.combine(END + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
LONG_COLS = {"calls", "allows", "pauses", "callers", "users", "lat", "n", "errs"}


class Recorder:
    """Wraps the SQLite executor and keeps every query result."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.dialect = inner.dialect
        self.max_params = inner.max_params
        self.results: list[tuple[str, list[dict[str, Any]]]] = []

    def qualify(self, table: str) -> str:
        return self.inner.qualify(table)

    def query(self, sql, params=None, column_types=None, param_types=None):
        rows = self.inner.query(sql, params, column_types, param_types)
        self.results.append((sql, rows))
        return rows


def _rest(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return str(v)


def _script(fake: FakeStatementExecution, results, match: list[str]) -> None:
    for (_, rows), key in zip(results, match, strict=True):
        names = list(rows[0]) if rows else []
        cols = [
            (n, "LONG" if n in LONG_COLS else "TIMESTAMP" if n.endswith("_seen") else "STRING")
            for n in names
        ]
        fake.add_rows(cols, [[_rest(r[n]) for n in names] for r in rows], match=key)


def _groups(d: dict) -> dict:
    return {
        k: (
            g.calls,
            g.allows,
            g.pauses,
            g.errors,
            g.callers,
            g.users,
            g.first_seen,
            g.last_seen,
            sorted(g.hist.items()),
        )  # fmt: skip
        for k, g in d.items()
    }


def test_delta_dialect_and_replayed_results(adapters, loaded) -> None:
    rec = Recorder(adapters.executor)
    sqlite_ctx = MonitorContext.from_adapters(adapters, MemoryEvidence())
    sqlite_ctx.executor = rec
    want = tools._scan(sqlite_ctx, T_FROM, T_TO)
    assert len(want) > 5 and len(rec.results) == 3

    fake = FakeStatementExecution()
    _script(fake, rec.results, ["COUNT(DISTINCT caller_agent_id)", "AS lat", "rule_error"])
    ex = DatabricksRestExecutor(
        fake, warehouse_id="wh-test", catalog="cat", schema="sch", sleep=lambda s: None
    )
    model = load_model()
    dctx = MonitorContext(
        tables=SqlTableStore(ex, model),
        state=SqlStateStore(ex, FixedClock(NOW), model),
        executor=ex,
        model=model,
        clock=FixedClock(NOW),
        evidence=MemoryEvidence(),
    )
    got = tools._scan(dctx, T_FROM, T_TO)
    assert _groups(got) == _groups(want)

    sql = "\n".join(fake.statements)
    assert "get_json_object(args_masked" in sql and "date_format(to_utc_timestamp(" in sql
    assert "json_extract" not in sql and "substr(" not in sql and "json_valid" not in sql
    assert "`cat`.`sch`.`agent_event`" in sql and "`cat`.`sch`.`verdict`" in sql
    first = next(c for c in fake.calls if c.method == "execute_statement")
    params = {p.name: p for p in first.kwargs["parameters"]}
    assert params["r_from"].type == "TIMESTAMP" and params["r_to"].type == "TIMESTAMP"


def test_delta_write_path_inserts_one_row_per_group(adapters, loaded) -> None:
    day = END - timedelta(days=1)
    sqlite_ctx = MonitorContext.from_adapters(adapters, MemoryEvidence())
    rows = tools.compute_rows(sqlite_ctx, day, day, tools.risk_classes())
    assert rows

    fake = FakeStatementExecution()
    fake.add_rows([("usage_date", "DATE")], [], match="SELECT")  # nothing stored for the day
    for _ in rows:
        fake.add(dml_result(1), match="MERGE INTO")
    ex = DatabricksRestExecutor(
        fake, warehouse_id="wh-test", catalog="cat", schema="sch", sleep=lambda s: None
    )
    model = load_model()
    state = SqlStateStore(ex, FixedClock(NOW), model)
    dctx = MonitorContext(
        tables=SqlTableStore(ex, model), state=state, executor=ex, model=model,
        clock=FixedClock(NOW), evidence=MemoryEvidence(),
    )  # fmt: skip
    stats = tools._write(dctx, rows, [day])
    assert stats == {"inserted": len(rows), "updated": 0, "unchanged": 0}
    inserts = [s for s in fake.statements if s.startswith("MERGE INTO")]
    assert len(inserts) == len(rows)
    assert all("`cat`.`sch`.`tool_usage_daily`" in s for s in inserts)
    assert isinstance(day, date)
