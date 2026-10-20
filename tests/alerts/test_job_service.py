"""WP21: the alerts job end to end on SQLite (chain -> signals -> alerts -> routes), route retry,
acknowledge, the off path, the dry-run CLI, and the alert table on a Databricks fake."""

# ruff: noqa: F401, F811 (the evidence conftest fixture ``env`` is imported)

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.integrations import siem as S
from supervisor.adapters.integrations.deadletter import DeadLetter
from supervisor.adapters.notify import InboxNotifier, StubNotifier, WebhookNotifier
from supervisor.adapters.sql.databricks_fake import (
    FakeStatementExecution,
    dml_result,
    succeeded,
)
from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor
from supervisor.adapters.sql.store import SqlStateStore, SqlTableStore
from supervisor.alerts import AlertError, AlertService, Routes, evaluate, load_rules
from supervisor.alerts.__main__ import main as cli_main
from supervisor.alerts.service import InboxRoute, SiemRoute, StubRoute, WebhookRoute
from supervisor.config import REPO_ROOT, load_settings
from supervisor.core.schema import load_model
from supervisor.jobs import alerts as alerts_job
from supervisor.monitors.common import MonitorContext, open_case
from tests.evidence.conftest import T0, Env, env, make_writer

RULES = REPO_ROOT / "config" / "alerts.yaml"
FIX = REPO_ROOT / "tests" / "fixtures" / "alerts"


class FakeHook:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.down = False

    def __call__(self, url: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        self.calls.append(payload)
        if self.down:
            raise ConnectionError("hook down")
        return {}


class Setup:
    def __init__(self, env: Env, tmp: Path) -> None:
        self.env = env
        self.a = env.adapters
        self.w = make_writer(env)
        self.ctx = MonitorContext.from_adapters(env.adapters, self.w)
        self.settings = load_settings(
            data_dir=tmp / "d", alerts_enabled=True, alerts_config=RULES, alerts_lag_s=0
        )
        self.inbox = InboxNotifier(self.a.state, self.a.clock)
        self.hook = FakeHook()
        self.hook_notifier = WebhookNotifier(
            self.inbox,
            "https://hook.invalid/x",
            transport=self.hook,
            dead_letter=DeadLetter(tmp / "hook.dead.jsonl"),
            sleep=lambda _s: None,
        )
        self.siem_path = tmp / "siem.log"
        self.routes = Routes(
            {
                "inbox": InboxRoute(self.inbox),
                "pager": StubRoute(StubNotifier("pager", self.inbox)),
                "webhook": WebhookRoute(self.hook_notifier),
                "siem": SiemRoute(S.LogSiemSink(self.siem_path, "ocsf")),
            }
        )
        self.svc = AlertService(self.a.state, self.a.clock, self.w, self.routes, env="laptop")

    def blocks(self, agent: str, n: int, gap: float = 5.0) -> None:
        for i in range(n):
            self.env.clock.advance(gap)
            self.w.record(
                "gate_decision",
                f"d:{agent}:{self.env.clock.now().timestamp()}:{i}",
                {"agent_id": agent, "action": "block", "rule_id": "PAY-08", "allow": False},
            )

    def run(self) -> dict[str, Any]:
        self.env.clock.advance(1)
        return alerts_job.run(self.ctx, self.settings, self.svc)

    def alerts(self) -> list[dict[str, Any]]:
        return sorted(self.a.state.query("alert"), key=lambda r: (r["ts"], r["alert_id"]))


@pytest.fixture
def s(env: Env, tmp_path: Path) -> Setup:
    return Setup(env, tmp_path)


def test_flags_are_off_by_default() -> None:
    cfg = load_settings()
    assert cfg.alerts_enabled is False and cfg.siem_enabled is False
    assert cfg.notify_webhook_enabled is False


def test_job_raises_routes_and_dedupes_across_runs(s: Setup) -> None:
    s.blocks("a1", 6)  # 5 in 25 s -> burst alert, the 6th is a repeat
    s.env.clock.advance(5)
    s.w.record(
        "gate_state_change",
        "gsc:1",
        {
            "agent_id": "a1",
            "event": "quarantine",
            "from_state": "RUNNING",
            "to_state": "QUARANTINED",
        },
    )
    s.w.record("chain_verify", "cv:1", {"ok": False, "failures": 1})
    case_id = open_case(
        s.ctx, agent_id="a1", severity="high", case_type="gate", summary="x", actor="system:test",
        evidence_payload={},
    )  # fmt: skip
    out = s.run()
    assert out["alerts"] == 3 and out["suppressed"] == 1
    rows = {r["rule_id"]: r for r in s.alerts()}
    assert set(rows) == {"AL-BLOCK-BURST", "AL-QUARANTINE", "AL-CHAIN-VERIFY-FAIL"}
    burst = rows["AL-BLOCK-BURST"]
    # what the analyst needs to triage
    assert burst["agent_id"] == "a1" and burst["severity"] == "high" and burst["status"] == "open"
    assert (burst["window_count"], burst["threshold"], burst["window_s"]) == (5, 5, 600)
    assert burst["suppressed_count"] == 1 and burst["case_id"] == case_id
    assert burst["chain_lane"] == "agent:a1" and burst["chain_seq"] is not None
    assert len(burst["entry_hash"]) == 64 and burst["first_ts"] < burst["last_ts"]
    assert burst["rule_hash"] and len(burst["refs"]) == 5
    # routes
    assert burst["route_status"] == {"inbox": "sent", "siem": "sent"}
    q = rows["AL-QUARANTINE"]
    assert q["route_status"] == {
        "inbox": "sent",
        "siem": "sent",
        "pager": "queued",
        "webhook": "sent",
    }
    assert rows["AL-CHAIN-VERIFY-FAIL"]["agent_id"] is None  # system-level: no agent
    notices = [n for n in s.inbox.list() if n["channel"] == "alert"]
    assert len(notices) == 3 + 0 and all("rule_id:" in n["body"] for n in notices)
    top = next(n for n in notices if "AL-BLOCK-BURST" in n["subject"])
    assert f"case: {case_id}" in top["body"] and "chain: agent:a1:" in top["body"]
    assert "window: 5 of 5 in 600 s" in top["body"]
    assert [n["channel"] for n in s.inbox.list() if n["channel"].startswith("pager")] == [
        "pager:alert",
        "pager:alert",
    ]  # quarantine and chain verify page; the block burst does not
    assert len(s.hook.calls) == 2 and s.hook.calls[0]["kind"] == "alert"
    assert {c["idempotency_key"] for c in s.hook.calls} >= {q["alert_id"]}
    siem_docs = [json.loads(x) for x in s.siem_path.read_text("utf-8").splitlines()]
    assert len(siem_docs) == 3 and {d["class_uid"] for d in siem_docs} == {2004}
    # each alert is also on the evidence chain (ids and counts, no text)
    recs = [p for p in s.a.tables.query("chain_entry") if p["record_type"] == "alert"]
    assert len(recs) == 3
    # alert records do not break the offline chain verification
    from supervisor.evidence.export import export_chain
    from supervisor.evidence.verify import verify_export

    s.w.close()
    export_chain(s.a.tables, s.env.tmp / "export")
    assert verify_export(s.env.tmp / "export").failures == 0
    s.w = make_writer(s.env)
    s.ctx = MonitorContext.from_adapters(s.a, s.w)
    s.svc.evidence = s.w
    # run again: nothing new, nothing sent twice
    again = s.run()
    assert again["alerts"] == 0 and len(s.alerts()) == 3 and len(s.hook.calls) == 2
    # the incident goes on inside the dedupe window: only suppressed_count grows
    s.blocks("a1", 3)
    third = s.run()
    assert third["alerts"] == 0
    assert next(r for r in s.alerts() if r["rule_id"] == "AL-BLOCK-BURST")["suppressed_count"] == 4
    # after the dedupe window a new burst is a new alert
    s.env.clock.advance(2000)
    s.blocks("a1", 5)
    s.run()
    bursts = [r for r in s.alerts() if r["rule_id"] == "AL-BLOCK-BURST"]
    assert len(bursts) == 2 and bursts[0]["alert_id"] != bursts[1]["alert_id"]


def test_alert_text_has_no_free_text(s: Setup) -> None:
    s.w.record(
        "gate_state_change",
        "gsc:1",
        {"agent_id": "a1", "event": "quarantine", "to_state": "QUARANTINED",
         "reason": "Nguyen Van A 0912345678"},
    )  # fmt: skip
    s.run()
    blob = json.dumps(
        [s.alerts(), s.inbox.list(), s.hook.calls, s.siem_path.read_text("utf-8")], default=str
    )
    assert "Nguyen" not in blob and "0912345678" not in blob


def test_failed_route_is_retried_by_the_next_run(s: Setup) -> None:
    s.hook.down = True
    s.hook_notifier.retry = type(s.hook_notifier.retry)(attempts=2, base_delay_s=0)
    s.w.record("gate_state_change", "gsc:1", {"agent_id": "a1", "event": "quarantine"})
    s.run()
    row = s.alerts()[0]
    assert row["route_status"]["webhook"] == "dead_letter"  # parked in the dead-letter file
    assert s.hook_notifier.dead_letter is not None and s.hook_notifier.dead_letter.count() == 1

    class Flaky:
        n = 0

        def send(self, alert: Any) -> str:
            Flaky.n += 1
            if Flaky.n == 1:
                raise RuntimeError("boom")
            return "sent"

    s.routes.channels["webhook"] = Flaky()  # type: ignore[assignment]
    # a fresh alert whose route raises is "failed", then redelivered
    s.env.clock.advance(4000)
    s.w.record("gate_state_change", "gsc:2", {"agent_id": "a2", "event": "quarantine"})
    s.run()
    failed = next(r for r in s.alerts() if r["agent_id"] == "a2")
    assert failed["route_status"]["webhook"] == "failed"
    s.run()  # redeliver pass at the start of the run
    healed = next(r for r in s.alerts() if r["agent_id"] == "a2")
    assert healed["route_status"]["webhook"] == "sent"
    assert s.inbox.list() and Flaky.n == 2


def test_acknowledge_is_one_way_and_records_who(s: Setup) -> None:
    s.w.record("chain_verify", "cv:1", {"ok": False})
    s.run()
    row = s.alerts()[0]
    ack = s.svc.acknowledge(row["alert_id"], "operator.khanh", row["row_version"])
    assert ack["status"] == "acknowledged" and ack["acknowledged_by"] == "operator.khanh"
    assert ack["acknowledged_at"] is not None
    assert s.svc.counts() == {"open": 0, "acknowledged": 1, "closed": 0}
    with pytest.raises(AlertError, match="only open alerts"):
        s.svc.acknowledge(row["alert_id"], "operator.khanh", ack["row_version"])
    with pytest.raises(AlertError, match="does not exist"):
        s.svc.acknowledge("nope", "u", 1)
    assert any(r["record_type"] == "alert_ack" for r in s.a.tables.query("chain_entry"))
    # an acknowledged alert still dedupes: the same failure does not page again
    s.env.clock.advance(60)
    s.w.record("chain_verify", "cv:2", {"ok": False})
    s.run()
    assert len(s.alerts()) == 1 and s.alerts()[0]["suppressed_count"] == 1


def test_job_signals_cover_scheduler_failure_and_judge_escalation(s: Setup) -> None:
    from supervisor.monitors.common import put_state

    put_state(
        s.ctx, "scheduler", "last:drift", {"ts": "2026-10-14T02:00:00.000000Z", "status": "error"}
    )
    put_state(
        s.ctx, "scheduler", "last:ingest", {"ts": "2026-10-14T02:00:00.000000Z", "status": "ok"}
    )
    for tier, mock, vid in ((2, False, "v-real"), (2, True, "v-mock"), (1, False, "v-t1")):
        s.a.tables.append(
            "verdict",
            [
                {
                    "verdict_id": vid,
                    "ts": s.a.clock.now(),
                    "trace_id": "t",
                    "event_id": "e",
                    "agent_id": "a9",
                    "tier": tier,
                    "checker_id": "judge",
                    "is_mock": mock,
                    "advisory": True,
                    "label": "suspicious",
                    "action": "alert",
                }  # fmt: skip
            ],
        )
    s.run()
    rules = sorted(r["rule_id"] for r in s.alerts())
    assert rules == ["AL-JOB-FAILURE", "AL-JUDGE-ESCALATION"]
    job = next(r for r in s.alerts() if r["rule_id"] == "AL-JOB-FAILURE")
    assert job["group_value"] == "drift" and job["agent_id"] is None


def test_policy_suppression_from_the_config(s: Setup, tmp_path: Path) -> None:
    cfg = tmp_path / "alerts.yaml"
    until = (T0 + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg.write_text(
        RULES.read_text("utf-8").replace(
            "suppressions: []",
            f"suppressions:\n  - {{rule_id: AL-QUARANTINE, agent_id: a1, until: '{until}', "
            "reason_code: planned_test}",
        ),
        "utf-8",
    )
    s.settings = load_settings(
        data_dir=tmp_path / "d", alerts_enabled=True, alerts_config=cfg, alerts_lag_s=0
    )
    s.w.record("gate_state_change", "gsc:1", {"agent_id": "a1", "event": "quarantine"})
    out = s.run()
    assert out["alerts"] == 0 and out["policy_suppressed"] == 1 and s.alerts() == []


def test_bad_config_fails_the_run_with_a_clear_error(s: Setup, tmp_path: Path) -> None:
    from supervisor.alerts import AlertConfigError

    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\nrules: [{id: x}]\n", "utf-8")
    s.settings = load_settings(data_dir=tmp_path / "d", alerts_config=bad)
    with pytest.raises(AlertConfigError, match="id must match"):
        s.run()


# --------------------------------------------------------------------------- CLI


def test_cli_list_validate_and_unknown_rule(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["validate", "--config", str(RULES)]) == 0
    assert "[OK] 8 rule(s)" in capsys.readouterr().out
    assert cli_main(["list", "--config", str(RULES)]) == 0
    out = capsys.readouterr().out
    assert "AL-BLOCK-BURST" in out and out.isascii()
    assert cli_main(["test", "AL-NOPE", "--config", str(RULES)]) == 1
    assert "unknown rule" in capsys.readouterr().out


def test_cli_dry_run_on_the_fixture_writes_nothing(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    sig = str(FIX / "dev.signals.jsonl")
    assert cli_main(["test", "AL-BLOCK-BURST", "--config", str(RULES), "--signals", sig]) == 0
    out = capsys.readouterr().out
    assert out.isascii() and "would fire: group=dev-agent-" in out
    assert "count=5/5" in out and "repeats_suppressed=3" in out
    assert "1 alert(s) would be raised (dry run, nothing stored or sent)" in out
    assert cli_main(["test", "AL-QUARANTINE", "--config", str(RULES), "--signals", sig]) == 0
    assert "1 alert(s) would be raised" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []  # no file written anywhere near the test dir
    bad = tmp_path / "x.yaml"
    bad.write_text("version: 2\nrules: []\n", "utf-8")
    assert cli_main(["validate", "--config", str(bad)]) == 1
    assert "[FAIL]" in capsys.readouterr().out


def test_cli_dry_run_on_the_live_store_reads_only(
    s: Setup, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    s.blocks("a1", 6)
    import supervisor.alerts.__main__ as M

    monkeypatch.setattr(
        M, "_live_signals", lambda since_s: M.load_signals(s.ctx, T0, T0 + timedelta(days=1))
    )
    assert cli_main(["test", "AL-BLOCK-BURST", "--config", str(RULES)]) == 0
    assert "would fire: group=a1" in capsys.readouterr().out
    assert s.a.state.query("alert") == []  # the dry run stored nothing


def test_the_alert_job_is_a_scheduler_job_gated_by_its_flag(tmp_path: Path) -> None:
    from supervisor import scheduler as sched_mod

    text = (REPO_ROOT / "src" / "supervisor" / "scheduler.py").read_text("utf-8")
    assert 'JobSpec("alerts"' in text and "settings.alerts_enabled" in text
    assert 'JobSpec("siem"' in text and "settings.siem_enabled" in text
    assert hasattr(sched_mod, "build_jobs")


# --------------------------------------------------------------------------- databricks fake


def _alert_row(**kw: Any) -> dict[str, Any]:
    row = {
        "alert_id": "a" * 32, "ts": T0, "dedupe_key": "AL-X:a1", "rule_id": "AL-X",
        "rule_hash": "h" * 64, "severity": "high", "status": "open", "title": "t",
        "agent_id": "a1", "group_value": "a1", "window_s": 600, "window_count": 5, "threshold": 5,
        "first_ts": T0, "last_ts": T0, "suppressed_count": 0, "case_id": None,
        "chain_lane": "agent:a1", "chain_seq": 3, "entry_hash": "e" * 64, "refs": ["a1:1"],
        "routes": ["inbox"], "route_status": {"inbox": "pending"}, "acknowledged_by": None,
        "acknowledged_at": None, "correlation_id": None,
    }  # fmt: skip
    row.update(kw)
    return row


def test_alert_table_on_databricks_fake_insert_read_and_ack() -> None:
    from supervisor.adapters.clock import FixedClock

    fake = FakeStatementExecution()
    ex = DatabricksRestExecutor(fake, warehouse_id="wh", catalog="c", schema="s")
    clock = FixedClock(T0)
    model = load_model()
    state = SqlStateStore(ex, clock, model)
    cols = model.table("alert").column_names
    assert "alert" in model.tables and "siem_event" in model.tables

    def select(row: dict[str, Any]) -> dict[str, Any]:
        def cell(v: Any) -> str | None:
            if v is None:
                return None
            if isinstance(v, (list, dict)):
                return json.dumps(v)
            if hasattr(v, "isoformat"):
                return v.isoformat().replace("+00:00", "Z")
            return str(v)

        full = {**row, "row_version": 1, "updated_at": T0}
        return succeeded([(c, "STRING") for c in cols], [[cell(full[c]) for c in cols]])[0]

    svc = AlertService(state, clock, None, Routes())
    # insert is an insert-only MERGE on Delta; a duplicate (0 rows) is a quiet no-op for raise_alert
    fake.add(dml_result(1), match="MERGE INTO")
    state.insert("alert", _alert_row())
    stmt = fake.statements[0]
    assert "MERGE INTO `c`.`s`.`alert`" in stmt and "WHEN NOT MATCHED" in stmt
    # counts() reads the table
    fake.add(select(_alert_row()), match="SELECT")
    assert svc.counts() == {"open": 1, "acknowledged": 0, "closed": 0}
    # acknowledge: read, optimistic UPDATE with row_version, read back
    fake.add(select(_alert_row()), match="SELECT")
    fake.add(dml_result(1), match="UPDATE")
    fake.add(
        select(_alert_row(status="acknowledged", acknowledged_by="operator.khanh")), match="SELECT"
    )
    out = svc.acknowledge("a" * 32, "operator.khanh", 1)
    assert out["status"] == "acknowledged"
    upd = next(x for x in fake.statements if x.startswith("UPDATE"))
    assert "row_version = :s_row_version" in upd and "AND row_version = :k_expected" in upd
    assert fake.remaining() == 0
    # the siem_event Delta table is append-only: no UPDATE / DELETE method exists for it
    assert model.table("siem_event").append_only is True


# --------------------------------------------------------------------------- review fixes


def _late_quarantine(s: Setup, agent: str, ts_offset_s: float) -> None:
    """A chain entry stamped ``ts_offset_s`` before now that becomes visible only now (its
    commit was slow, or another lane committed first): the clock steps back for the stamp."""
    s.env.clock.advance(-ts_offset_s)
    s.w.record(
        "gate_state_change",
        f"gsc:late:{agent}",
        {"agent_id": agent, "event": "quarantine", "from_state": "RUNNING",
         "to_state": "QUARANTINED"},
    )  # fmt: skip
    s.env.clock.advance(ts_offset_s)


def _quarantine_alerts(s: Setup, agent: str) -> list[dict[str, Any]]:
    return [a for a in s.alerts() if a["dedupe_key"] == f"AL-QUARANTINE:{agent}"]


def test_watermark_lag_catches_an_entry_that_commits_after_its_timestamp(s: Setup) -> None:
    """Review: without a lag the cursor sat at the newest signal, and an entry stamped a few
    seconds earlier that became visible after the run was behind the cursor forever."""
    s.settings = s.settings.model_copy(update={"alerts_lag_s": 30})
    s.blocks("a1", 1)
    s.env.clock.advance(100)
    s.blocks("a1", 1)  # newer than the late entry below, but younger than the lag
    out = s.run()  # judges only the first block: cursor = its ts, 100 s back
    assert out["judged"] == 1
    _late_quarantine(s, "a2", ts_offset_s=4)  # same timing as the no-lag test below
    s.env.clock.advance(60)
    s.run()
    assert len(_quarantine_alerts(s, "a2")) == 1


def test_without_lag_a_late_entry_behind_the_cursor_is_missed(s: Setup) -> None:
    """The reason for ALERTS_LAG_S: with lag 0 the same late entry is skipped."""
    s.blocks("a1", 1)
    s.env.clock.advance(100)
    s.blocks("a1", 1)  # the newest signal moves the cursor to (almost) now
    assert s.run()["judged"] == 2
    _late_quarantine(s, "a3", ts_offset_s=4)
    s.env.clock.advance(60)
    s.run()
    assert _quarantine_alerts(s, "a3") == []


def _ingress_denied(s: Setup, reason: str, claimed: str | None, suppressed: int = 0) -> None:
    """The row WP20 ingress auth writes for one rejection (gateway/ingress_auth.py)."""
    from supervisor.adapters.auth.audit import write_action

    write_action(
        s.a.tables,
        s.a.clock,
        request_id=None,
        actor=None,
        actor_fallback=(f"unverified:{claimed or 'none'}", "agent", "ingress"),
        permission="ingress.auth",
        method="POST",
        path="/gate/check",
        outcome="denied",
        target_kind="agent" if claimed else None,
        target_id=claimed,
        before_hash="0" * 64,
        detail=reason + (f";suppressed={suppressed}" if suppressed else ""),
    )


def test_wp20_ingress_rejections_from_console_action_raise_the_burst_alert(s: Setup) -> None:
    """Review: WP20 writes rejections as console_action rows, not ingress_reject chain
    records, so AL-INGRESS-REJECT-BURST could never fire after the merge."""
    from supervisor.alerts.signals import load_signals

    for i in range(4):
        s.env.clock.advance(5)
        _ingress_denied(s, "bad_signature", f"pay-{i}")
    s.run()
    assert [a for a in s.alerts() if a["rule_id"] == "AL-INGRESS-REJECT-BURST"] == []  # 4 < 20
    s.env.clock.advance(5)
    _ingress_denied(s, "stale_timestamp", "x" * 300 + " <script>", suppressed=19)  # 20 more
    s.run()
    burst = [a for a in s.alerts() if a["rule_id"] == "AL-INGRESS-REJECT-BURST"]
    assert len(burst) == 1 and burst[0]["window_count"] >= 20
    now = s.env.clock.now()
    sigs = [
        x
        for x in load_signals(s.ctx, now - timedelta(seconds=600), now)
        if x.kind == "ingress_reject"
    ]
    assert len(sigs) == 4 + 20
    assert {x.fields["reason_code"] for x in sigs} == {"bad_signature", "stale_timestamp"}
    # the unverified claimed id that is not id-shaped never reaches an alert or a signal
    assert all(x.fields["agent_id"] is None or len(x.fields["agent_id"]) <= 128 for x in sigs)
    assert "<script>" not in json.dumps([dict(x.fields) for x in sigs])
    # an ok console_action row or another permission is not a rejection
    from supervisor.adapters.auth.audit import write_action

    write_action(
        s.a.tables, s.a.clock, request_id=None, actor=None, permission="ingress.auth",
        method="POST", path="/gate/check", outcome="ok", detail="bad_signature",
    )  # fmt: skip
    assert len([x for x in load_signals(s.ctx, now - timedelta(seconds=600), now + timedelta(
        seconds=1)) if x.kind == "ingress_reject"]) == 24  # fmt: skip
