"""Retention (ADR D13): trigger rules, port methods, job, chain still verifies."""

# ruff: noqa: F401, F811 (the evidence conftest fixture ``env`` is imported)

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.sql.databricks_fake import (
    FakeStatementExecution,
    dml_result,
    succeeded,
)
from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor
from supervisor.adapters.sql.store import SqlStateStore, SqlTableStore
from supervisor.config import load_settings
from supervisor.core.errors import AppendOnlyError, SqlError
from supervisor.core.schema import load_model, parse_model
from supervisor.evidence.export import export_chain
from supervisor.evidence.verify import verify_export
from supervisor.jobs import retention
from supervisor.jobs.bootstrap_schema import run as bootstrap_run
from tests.evidence.conftest import T0, Env, env, make_writer

DAY = timedelta(days=1)


def _event(i: int, ts, **kw):
    row = dict(
        event_id=f"e{i}", ts=ts, trace_id=f"t{i}", span_id=f"s{i}", agent_id="a1",
        event_type="tool_call", args_hash="h" * 8, args_masked="ARGS", result_masked="RES",
        env="dev", source="otel", capture_level="masked",
    )  # fmt: skip
    row.update(kw)
    return row


def _raw(i: int, ts):
    return dict(event_id=f"e{i}", ts=ts, trace_id=f"t{i}", agent_id="a1",
                args_raw="RAWARGS", result_raw="RAWRES", access_class="restricted")  # fmt: skip


def _seed(env: Env) -> None:
    t = env.adapters.tables
    old, new = T0 - 400 * DAY, T0 - 10 * DAY
    t.append("agent_event", [_event(1, old), _event(2, new)])
    t.append("agent_event_raw", [_raw(1, T0 - 100 * DAY), _raw(2, new)])
    t.append(
        "verdict",
        [
            dict(verdict_id=f"v{i}", ts=ts, agent_id="a1", tier=0, checker_id="r", is_mock=False,
                 advisory=False, label="ok", action="allow", rationale_masked="WHY")
            for i, ts in ((1, old), (2, new))
        ],
    )  # fmt: skip
    t.append(
        "case_event",
        [
            dict(case_id="c1", seq=i, ts=ts, actor="u", actor_kind="human", action="note",
                 comment_masked="CMT")
            for i, ts in ((1, old), (2, new))
        ],
    )  # fmt: skip
    for i, ts in ((1, old), (2, new)):
        env.adapters.state.insert(
            "notice",
            dict(notice_id=f"n{i}", ts=ts, channel="inbox", subject="s", body="BODY", status="new"),
        )


def _enable(env: Env, **kw):
    kw.setdefault("retention_enabled", True)
    return load_settings(data_dir=env.tmp / "data", **kw)


def test_model_declares_classes() -> None:
    m = load_model()
    got = {t.name: dict(t.retention) for t in m.tables.values() if t.retention}
    assert got == {
        "agent_event": {"masked": ("args_masked", "result_masked")},
        "agent_event_raw": {"raw": ("args_raw", "result_raw")},
        "verdict": {"masked": ("rationale_masked",)},
        "case_event": {"masked": ("comment_masked",)},
        "notice": {"notice": ("body",)},
    }
    for name in ("chain_entry", "chain_payload", "chain_signature", "anchor"):
        assert not m.table(name).retention


@pytest.mark.parametrize(
    "bad",
    ["retention: {bogus: [a]}", "retention: {raw: [nope]}", "retention: {raw: [id]}",
     "retention: {raw: [n]}"],
)  # fmt: skip
def test_model_rejects_bad_retention(bad: str) -> None:
    text = (
        "version: 1\ntables:\n  t:\n    kind: append_only\n    primary_key: [id]\n"
        f"    {bad}\n    columns:\n      id: string\n      ts: timestamp\n      a: text?\n"
        "      n: int\n"
    )
    with pytest.raises(ValueError):
        parse_model(text)


def test_triggers_allow_only_nulling(env: Env) -> None:
    _seed(env)
    x = env.adapters.executor
    tbl = "agent_event"
    with pytest.raises(AppendOnlyError):
        x.execute(f"UPDATE {tbl} SET agent_id = 'z' WHERE event_id = 'e1'")
    with pytest.raises(AppendOnlyError):
        x.execute(f"UPDATE {tbl} SET args_hash = 'z', args_masked = NULL WHERE event_id = 'e1'")
    with pytest.raises(AppendOnlyError):
        x.execute(f"UPDATE {tbl} SET args_masked = 'new' WHERE event_id = 'e1'")
    with pytest.raises(AppendOnlyError):
        x.execute(f"DELETE FROM {tbl} WHERE event_id = 'e1'")
    x.execute(f"UPDATE {tbl} SET args_masked = NULL, result_masked = NULL WHERE event_id = 'e1'")
    rows = env.adapters.tables.query(tbl, {"event_id": "e1"})
    assert rows[0]["args_masked"] is None and rows[0]["args_hash"] == "hhhhhhhh"
    # tables without retention stay fully append-only
    make_writer(env).record("note", "n1", {"agent_id": "a1"})
    with pytest.raises(AppendOnlyError):
        x.execute("UPDATE chain_entry SET writer = 'x'")


def test_store_rejects_non_retention_columns(env: Env) -> None:
    _seed(env)
    with pytest.raises(SqlError):
        env.adapters.tables.redact_columns("agent_event", ["args_hash"], "ts", T0)
    with pytest.raises(SqlError):
        env.adapters.tables.count_due("chain_entry", ["writer"], "ts", T0)


def test_off_path(env: Env) -> None:
    _seed(env)
    r = retention.run(load_settings(data_dir=env.tmp / "data"), env.adapters)
    assert r["status"] == "skipped" and r["reason"] == "RETENTION_ENABLED=0"
    assert env.adapters.tables.query("agent_event", {"event_id": "e1"})[0]["args_masked"] == "ARGS"


def test_main_off_prints_skip(capsys: pytest.CaptureFixture[str]) -> None:
    assert retention.main([]) == 0
    assert capsys.readouterr().out.strip() == "[SKIP] RETENTION_ENABLED=0"


def test_dry_run_counts_only(env: Env) -> None:
    _seed(env)
    r = retention.run(_enable(env, retention_dry_run=True), env.adapters)
    assert r["status"] == "ok" and r["dry_run"] is True
    due = {(i["table"], i["class"]): i["due"] for i in r["items"]}
    assert due[("agent_event", "masked")] == 1
    assert due[("agent_event_raw", "raw")] == 1
    assert due[("notice", "notice")] == 1
    assert all(i["redacted"] == 0 for i in r["items"])
    assert env.adapters.tables.query("agent_event_raw", {"event_id": "e1"})[0]["args_raw"]


def test_job_redacts_old_keeps_new_and_chain_verifies(env: Env) -> None:
    _seed(env)
    w = make_writer(env)
    settings = _enable(env)
    w.record("verdict", "verdict:v1", {"agent_id": "a1", "score_bp": 10, "label": "ok"})
    r = retention.run(settings, env.adapters, chain=w)
    w.close()
    assert r["status"] == "ok"
    t = env.adapters.tables
    counts = {tb: len(t.query(tb)) for tb in ("agent_event", "agent_event_raw", "verdict")}
    assert counts == {"agent_event": 2, "agent_event_raw": 2, "verdict": 2}
    e1, e2 = (t.query("agent_event", {"event_id": k})[0] for k in ("e1", "e2"))
    assert e1["args_masked"] is None and e1["result_masked"] is None
    assert e1["args_hash"] == "hhhhhhhh" and e1["event_type"] == "tool_call"
    assert e2["args_masked"] == "ARGS"
    r1, r2 = (t.query("agent_event_raw", {"event_id": k})[0] for k in ("e1", "e2"))
    assert r1["args_raw"] is None and r1["result_raw"] is None  # 100 days > 90
    assert r2["args_raw"] == "RAWARGS"
    v1, v2 = (t.query("verdict", {"verdict_id": k})[0] for k in ("v1", "v2"))
    assert v1["rationale_masked"] is None and v2["rationale_masked"] == "WHY"
    c = {x["seq"]: x["comment_masked"] for x in t.query("case_event", {"case_id": "c1"})}
    assert c == {1: None, 2: "CMT"}
    n1, n2 = (env.adapters.state.get("notice", {"notice_id": k}) for k in ("n1", "n2"))
    assert n1["body"] == "" and n1["row_version"] == 2 and n2["body"] == "BODY"
    again = retention.run(settings, env.adapters)  # idempotent
    assert all(i["due"] == 0 and i["redacted"] == 0 for i in again["items"])
    assert len(t.query("chain_entry", {"record_type": "retention_run"})) == 1
    out = env.tmp / "export"
    export_chain(t, out, created_at=env.clock.now())
    report = verify_export(out)
    assert report.failures == 0, report.lines


def test_chain_payload_has_counts_no_pii(env: Env) -> None:
    _seed(env)
    w = make_writer(env)
    retention.run(_enable(env), env.adapters, chain=w)
    w.close()
    payloads = [str(x["payload"]) for x in env.adapters.tables.query("chain_payload", {})]
    mine = [p for p in payloads if "dry_run" in p]
    assert len(mine) == 1
    assert "BODY" not in mine[0] and "ARGS" not in mine[0] and "RAW" not in mine[0]


def test_old_trigger_reports_fail_not_crash(env: Env) -> None:
    _seed(env)
    x = env.adapters.executor
    x.execute("DROP TRIGGER trg_agent_event_no_update")
    x.execute("DROP TRIGGER trg_agent_event_retention_null_only")
    x.execute(
        "CREATE TRIGGER trg_agent_event_no_update BEFORE UPDATE ON agent_event "
        "BEGIN SELECT RAISE(ABORT, 'agent_event is append-only'); END"
    )
    r = retention.run(_enable(env), env.adapters)
    assert r["status"] == "failed"
    assert any("bootstrap_schema" in m for m in r["failed"])
    bootstrap_run(env.adapters.settings, env.adapters)  # refreshes the trigger
    r = retention.run(_enable(env), env.adapters)
    assert r["status"] == "ok"
    assert env.adapters.tables.query("agent_event", {"event_id": "e1"})[0]["args_masked"] is None


def test_bootstrap_is_idempotent_with_new_triggers(env: Env) -> None:
    _seed(env)
    bootstrap_run(env.adapters.settings, env.adapters)
    bootstrap_run(env.adapters.settings, env.adapters)
    with pytest.raises(AppendOnlyError):
        env.adapters.executor.execute("DELETE FROM verdict")


def test_databricks_report_mode(tmp_path: Path) -> None:
    fake = FakeStatementExecution()
    ex = DatabricksRestExecutor(fake, warehouse_id="wh", catalog="c", schema="s")
    clock = FixedClock(T0)
    model = load_model()
    tables = SqlTableStore(ex, model)
    state = SqlStateStore(ex, clock, model)
    count = [("n", "LONG")]
    for n in ("3", "2", "4", "1", "5"):  # agent_event, raw, verdict, case_event, notice
        fake.add(succeeded(count, [[n]])[0], match="SELECT COUNT")
    fake.add(dml_result(5), match="UPDATE")
    a = SimpleNamespace(tables=tables, state=state, clock=clock, model=model, executor=ex)
    settings = load_settings(data_dir=tmp_path, retention_enabled=True)
    r = retention.run(settings, a)  # type: ignore[arg-type]
    modes = {i["table"]: i["mode"] for i in r["items"]}
    assert modes["agent_event_raw"] == "report_only" and modes["notice"] == "apply"
    assert next(i for i in r["items"] if i["table"] == "agent_event_raw")["due"] == 2
    assert next(i for i in r["items"] if i["table"] == "notice")["redacted"] == 5
    updates = [c for c in fake.calls if "UPDATE" in c.kwargs["statement"]]
    assert len(updates) == 1 and "notice" in updates[0].kwargs["statement"]
    for i in r["items"]:
        if i["mode"] == "report_only":
            assert i["reason"] == retention.DELTA_REASON
    with pytest.raises(AppendOnlyError):
        tables.redact_columns("agent_event", ["args_masked"], "ts", T0)
