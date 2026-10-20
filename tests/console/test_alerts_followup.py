"""WP21 review follow-up: verify button and drill write evidence the alert rules read (F8), the
webhook never runs on a console request (F9)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from supervisor.adapters.notify import FanoutNotifier, WebhookNotifier
from supervisor.alerts import AlertService, build_routes
from supervisor.config import REPO_ROOT
from supervisor.console import auditpack
from supervisor.demo.drill import run_drill
from supervisor.jobs import alerts as alerts_job
from supervisor.monitors.common import MonitorContext

from .conftest import Console, add_gate_block


def _alert_job(console: Console) -> dict[str, Any]:
    rt = console.runtime
    ctx = MonitorContext.from_adapters(rt.adapters, rt.chain)
    settings = rt.settings.model_copy(
        update={"alerts_config": REPO_ROOT / "config" / "alerts.yaml", "alerts_lag_s": 0}
    )
    svc = AlertService(rt.adapters.state, rt.adapters.clock, rt.chain, build_routes(
        settings, rt.adapters.state, rt.adapters.clock))  # fmt: skip
    time.sleep(0.01)  # the records above are older than "now"
    return alerts_job.run(ctx, settings, svc)


def _rules(console: Console) -> list[str]:
    return sorted(a["rule_id"] for a in console.ctx.state.query("alert"))


def test_verify_button_writes_a_chain_verify_record_and_a_failure_alerts(
    console: Console, monkeypatch: Any
) -> None:
    r = console.post("/console/chain/verify", user="auditor.dung")
    assert r.status_code == 200
    recs = [
        e for e in console.ctx.tables.query("chain_entry") if e["record_type"] == "chain_verify"
    ]
    assert len(recs) == 1
    assert _alert_job(console)["alerts"] == 0 and _rules(console) == []  # a good verify is quiet

    real = auditpack.verify_export

    def failing(*a: Any, **k: Any) -> Any:
        rep = real(*a, **k)
        rep.failures = 2
        return rep

    monkeypatch.setattr(auditpack, "verify_export", failing)
    r = console.post("/console/chain/verify", user="auditor.dung")
    assert r.status_code == 200
    recs = [
        e for e in console.ctx.tables.query("chain_entry") if e["record_type"] == "chain_verify"
    ]
    assert len(recs) == 2
    out = _alert_job(console)
    assert out["alerts"] == 1 and _rules(console) == ["AL-CHAIN-VERIFY-FAIL"]
    row = console.ctx.state.query("alert")[0]
    assert row["severity"] == "critical" and row["chain_lane"] == "root"
    assert row["route_status"]["inbox"] == "sent"


def test_drill_writes_a_failmode_drill_record_and_a_failure_alerts(
    console: Console, tmp_path: Path
) -> None:
    class Sink:
        def __init__(self) -> None:
            self.records: list[tuple[str, dict[str, Any]]] = []

        def record(self, record_type: str, record_ref: str, payload: Any) -> str:
            self.records.append((record_type, dict(payload)))
            return "h"

    sink = Sink()
    rep = run_drill(tmp_path / "drill", echo=lambda _l: None, sink=sink)
    assert rep.ok and sink.records == [("failmode_drill", {"ok": True, "failures": 0})]
    assert any("failmode_drill" in line for line in rep.lines)
    chain = console.runtime.chain
    chain.record("failmode_drill", "d:ok", sink.records[0][1])
    assert _alert_job(console)["alerts"] == 0  # a passing drill is quiet
    chain.record(
        "failmode_drill", "d:bad", {"ok": False, "failures": 1}
    )  # what a failed drill writes
    assert _alert_job(console)["alerts"] == 1
    assert _rules(console) == ["AL-FAILCLOSED-DRILL-FAIL"]


def test_a_dead_webhook_does_not_slow_a_console_request(console: Console, tmp_path: Path) -> None:
    called: list[Any] = []

    def hangs(url: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        called.append(payload)
        time.sleep(4)
        raise ConnectionError("down")

    hook = WebhookNotifier(
        console.ctx.inbox, "https://hook.invalid/x", transport=hangs, sleep=lambda _s: None
    )
    console.ctx.cases.notifier = FanoutNotifier([console.ctx.inbox, hook])
    add_gate_block(console.runtime.adapters)
    t0 = time.perf_counter()
    r = console.post("/console/intake/run")  # opens a case: notices go to the notifier
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200
    assert called == [] and elapsed < 3.0, elapsed  # a synchronous send would take 12 s
    queued = [
        n for n in console.ctx.inbox.list(status="queued") if n["channel"].startswith("webhook:")
    ]
    assert queued, "the notice waits in the queue"
    # the scheduler job (not a request) sends it, and a dead hook is parked, not raised
    hook.transport = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("down"))
    assert hook.drain()["dead_letter"] == len(queued)
    assert all(
        n["status"] == "dead_letter"
        for n in console.ctx.inbox.list()
        if n["channel"].startswith("webhook:")
    )
