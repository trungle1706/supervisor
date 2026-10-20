"""WP29 on the Delta path (databricks_fake): the same answers as SQLite, and the right statements.

``MirrorFake`` (as in tests/console/test_ux3_delta.py) answers each read the store sends by
running it on the SQLite store and returning strings, as the Statement Execution API does. The
register runs through the real ``DatabricksRestExecutor`` / ``SqlStateStore`` / ``SqlTableStore``
code, with Delta-dialect SQL and string-typed rows (bool, date, int, json cast by schema)."""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from databricks.sdk.service.sql import StatementResponse

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.sql.databricks_fake import (
    Call,
    FakeStatementExecution,
    dml_result,
    succeeded,
)
from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor
from supervisor.adapters.sql.store import SqlStateStore, SqlTableStore
from supervisor.core.schema import load_model
from supervisor.risk.harness import _Env
from supervisor.risk.service import RiskService
from tests.conftest import REPO_ROOT

STARTERS = REPO_ROOT / "config" / "risks"
T0 = datetime(2026, 10, 20, 5, 0, 0, tzinfo=UTC)


def _s(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, dt.datetime):
        return v.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return str(v)


class MirrorFake(FakeStatementExecution):
    def __init__(self, inner: Any) -> None:
        super().__init__()
        self.inner = inner

    def execute_statement(self, statement: str, warehouse_id: str, **kwargs: Any) -> Any:
        self.calls.append(Call("execute_statement", {"statement": statement, **kwargs}))
        sql = statement.replace("`c`.`s`.", "").replace("`", '"')
        params = {p.name: p.value for p in (kwargs.get("parameters") or [])}
        rows = self.inner.query(sql, params)
        names = list(rows[0]) if rows else _columns(sql)
        final, _ = succeeded(
            [(n, "STRING") for n in names], [[_s(r[n]) for n in names] for r in rows]
        )
        return StatementResponse.from_dict({**final, "statement_id": f"mirror-{uuid.uuid4().hex}"})


def _columns(sql: str) -> list[str]:
    m = re.match(r"SELECT (.+?) FROM", sql)
    return [c.strip() for c in m.group(1).split(",")] if m else []


@pytest.fixture
def pair(env: _Env) -> tuple[RiskService, RiskService, MirrorFake]:
    """(sqlite service, delta service over the mirror) on the same data."""
    env.agent("pay")
    rid = env.risk(
        "delta read", "pay", [("rule", "PAY-02"), ("pack", "pack_a"), ("matrix", "OB-1")]
    )
    env.risk("second", "pay", [("monitor", "oversight")], treatment="avoid", residual_likelihood=1)
    env.verdict("pay", "PAY-02", "block", env.window_time())
    env.pack("pay", "pack_a", "ok", env.window_time())
    env.svc.run_evidence()
    assert env.svc.get(rid)["evidence_state"] == "working"
    fake = MirrorFake(env.adapters.executor)
    ex = DatabricksRestExecutor(fake, warehouse_id="wh", catalog="c", schema="s")
    model = load_model()
    delta = RiskService(
        SqlStateStore(ex, env.adapters.clock, model),
        SqlTableStore(ex, model),
        env.adapters.clock,
        env.settings,
        catalogue=env.svc.catalogue,
    )
    return env.svc, delta, fake


def _plain(x: Any) -> str:
    return json.dumps(x, sort_keys=True, default=str)


def test_reads_equal_on_both_backends(pair: Any) -> None:
    sq, de, fake = pair
    assert _plain(sq.list_risks()) == _plain(de.list_risks())
    for flt in ({"agent": "pay"}, {"band": "critical"}, {"status": "active"}, {"q": "delta"}):
        assert _plain(sq.list_risks(flt)) == _plain(de.list_risks(flt)), flt
    rid = sq.list_risks({"q": "delta"})[0]["risk_id"]
    assert _plain(sq.get(rid)) == _plain(de.get(rid))
    assert _plain({k: v.as_dict() for k, v in sq.agent_levels().items()}) == _plain(
        {k: v.as_dict() for k, v in de.agent_levels().items()}
    )
    assert sq.counts() == de.counts()
    assert any("`c`.`s`.`risk_link`" in s for s in fake.statements)  # Delta dialect was used
    assert any("`c`.`s`.`risk_evidence`" in s for s in fake.statements)


def test_string_typed_rows_are_cast(pair: Any) -> None:
    _, de, _ = pair
    row = de.get(de.list_risks({"q": "delta"})[0]["risk_id"])
    assert isinstance(row["inherent_likelihood"], int) and isinstance(row["review_overdue"], bool)
    assert row["links"] and all(isinstance(x["kind"], str) for x in row["links"])
    ev = row["evidence"][0]
    assert isinstance(ev["rule_hits"], int) and ev["state"] == "working"


def _store(fake: FakeStatementExecution) -> tuple[SqlStateStore, SqlTableStore]:
    ex = DatabricksRestExecutor(fake, warehouse_id="wh", catalog="c", schema="s")
    model = load_model()
    return SqlStateStore(ex, FixedClock(T0), model), SqlTableStore(ex, model)


def test_new_risk_and_link_rows_are_insert_only_merges() -> None:
    fake = FakeStatementExecution()
    fake.add(dml_result(1), match="MERGE INTO `c`.`s`.`risk`")
    fake.add(dml_result(1), match="MERGE INTO `c`.`s`.`risk_link`")
    state, _ = _store(fake)
    state.insert(
        "risk",
        {
            "risk_id": "R-1", "title": "t", "description": "", "category": "pii",
            "agent_id": "payments", "inherent_likelihood": 3, "inherent_impact": 4,
            "treatment": "mitigate", "residual_likelihood": 2, "residual_impact": 3,
            "owner": "o", "review_date": dt.date(2027, 4, 20), "status": "active",
            "source": "manual", "created_at": T0, "created_by": "u",
        },
    )  # fmt: skip
    state.insert(
        "risk_link",
        {
            "link_id": "rl_1", "risk_id": "R-1", "kind": "rule", "target": "PAY-02",
            "active": True, "created_at": T0, "created_by": "u",
        },
    )  # fmt: skip
    merges = [s for s in fake.statements if s.startswith("MERGE INTO")]
    assert len(merges) == 2 and all("WHEN NOT MATCHED THEN INSERT" in m for m in merges)
    params = {
        p.name: p.value
        for p in next(c for c in fake.calls if c.method == "execute_statement").kwargs["parameters"]
    }
    assert params["v_inherent_likelihood"] == "3" and params["v_review_date"] == "2027-04-20"
    assert fake.remaining() == 0


def test_evidence_rows_are_appended_with_typed_values() -> None:
    fake = FakeStatementExecution()
    fake.add(dml_result(1), match="MERGE INTO `c`.`s`.`risk_evidence`")
    _, tables = _store(fake)
    cols = load_model().table("risk_evidence").column_names
    row = {c: 0 for c in cols}
    row |= {
        "evidence_id": "rev_1", "risk_id": "R-1", "ts": T0, "window_start": T0,
        "window_end": T0, "state": "working", "reason": "controls_working",
        "digest": "0" * 64, "chain_hash": None,
    }  # fmt: skip
    assert tables.append("risk_evidence", [row]) == 1
    (stmt,) = [s for s in fake.statements if "risk_evidence" in s]
    assert stmt.startswith("MERGE INTO `c`.`s`.`risk_evidence`")
    assert "WHEN NOT MATCHED THEN INSERT" in stmt  # a repeat of the same window is a no-op


def test_risk_tables_are_in_both_ddls() -> None:
    sq = (REPO_ROOT / "schema" / "ddl" / "sqlite.sql").read_text(encoding="utf-8")
    dl = (REPO_ROOT / "schema" / "ddl" / "databricks.sql").read_text(encoding="utf-8")
    for table in ("risk", "risk_link", "risk_evidence"):
        assert f"CREATE TABLE IF NOT EXISTS {table} " in sq, table
        assert f"`${{catalog}}`.`${{schema}}`.`{table}`" in dl, table
    ev_ddl = dl[dl.index("`risk_evidence` (") :]
    assert "'delta.appendOnly' = 'true'" in ev_ddl.split("TBLPROPERTIES", 1)[1].split("\n", 1)[0]
    link_ddl = dl[dl.index("`risk_link` (") :]
    assert "'supervisor.kind' = 'state'" in link_ddl.split("TBLPROPERTIES", 1)[1].split("\n", 1)[0]
