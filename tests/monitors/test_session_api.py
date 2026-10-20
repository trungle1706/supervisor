"""WP27: /v1/sessions routes, batch path, status row, databricks_app mode (SQLite stand-in)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from supervisor.config import load_settings
from supervisor.monitors.common import MonitorContext
from supervisor.monitors.session_batch import SessionMonitor
from supervisor.monitors.status import read_status
from tests.monitors.session_helpers import make_session_gateway, policy_with
from tests.monitors.test_session import SESSION_CFG, SPLIT, feed

QUIET = {"k": 8, "case_threshold_bp": 10000, "pause_scope": []}  # in-request path never acts


class Rt:
    def __init__(self, client: Any, runtime: Any) -> None:
        self.client, self.runtime = client, runtime

    def get(self, url: str, user: str = "reviewer.an") -> Any:
        return self.client.get(url, headers={"X-Dev-User": user})

    def post(self, url: str, body: dict[str, Any], user: str = "reviewer.an") -> Any:
        return self.client.post(url, json=body, headers={"X-Dev-User": user})


@pytest.fixture
def rt(tmp_path: Path) -> Iterator[Rt]:
    from fastapi.testclient import TestClient

    from supervisor.adapters.auth import set_provider
    from supervisor.app import app
    from supervisor.console.context import build_context, set_context
    from supervisor.gateway import wiring as gate_wiring
    from supervisor.wiring import build_runtime

    settings = load_settings(
        sql_backend="sqlite", data_dir=tmp_path / "d", session_monitor_enabled=True
    )
    runtime = build_runtime(settings, policy_refresh_s=0.0, state_cache_ttl_s=0.0)
    ctx = build_context(runtime)
    set_context(ctx)
    gate_wiring.set_gateway(runtime.gateway)
    try:
        yield Rt(TestClient(app, raise_server_exceptions=False), runtime)
    finally:
        set_context(None)
        gate_wiring.set_gateway(None)
        set_provider(None)
        runtime.close()


def drive(
    runtime: Any, steps: list[tuple[str, dict[str, Any], str]], sid: str = "conv-api"
) -> None:
    clock = runtime.adapters.clock
    for tool, args, text in steps:
        runtime.gateway.check(
            "payments", "1.0", tool, args,
            {"session_id": sid, "consumer_id": "u1", "turn_text": text},
        )  # fmt: skip
        assert clock.now() is not None


def test_runtime_wires_the_session_gate_only_with_the_flag(rt: Rt, tmp_path: Path) -> None:
    assert rt.runtime.gateway.session_gate is not None
    s = load_settings(sql_backend="sqlite", data_dir=tmp_path / "off")
    from supervisor.wiring import build_runtime

    off = build_runtime(s)
    try:
        assert off.gateway.session_gate is None
    finally:
        off.close()


def test_get_session_shows_masked_timeline_and_scores(rt: Rt) -> None:
    drive(rt.runtime, SPLIT[:4])
    r = rt.get("/v1/sessions/conv-api")
    assert r.status_code == 200, r.text
    body = r.json()
    agent = body["agents"][0]
    assert agent["agent_id"] == "payments" and agent["turns"] == 4
    assert [t["tool"] for t in agent["timeline"]][:2] == ["get_balance", "list_payees"]
    assert agent["assessment"]["score_bp"] >= 0
    text = r.text
    assert "chuyen 90 trieu" not in text  # no turn text anywhere
    assert agent["session_source"] == "client"


def test_get_session_errors_are_400_or_404_never_500(rt: Rt) -> None:
    assert rt.get("/v1/sessions/nope-nope").status_code == 404
    assert rt.get("/v1/sessions/bad%40id").status_code == 400
    assert rt.get("/v1/sessions/conv-api?agent_id=bad%20id").status_code == 400


def test_get_session_needs_a_role_that_holds_session_view(rt: Rt, monkeypatch: Any) -> None:
    from supervisor.adapters.auth.authz import runtime_settings

    monkeypatch.setattr(runtime_settings(), "api_rbac_enabled", True, raising=False)
    drive(rt.runtime, SPLIT[:2])
    assert rt.get("/v1/sessions/conv-api", user="reviewer.an").status_code == 200
    assert rt.get("/v1/sessions/conv-api", user="viewer.hoa").status_code == 403


def test_route_is_off_with_the_flag_off(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from supervisor.adapters.auth import set_provider
    from supervisor.app import app
    from supervisor.console.context import build_context, set_context
    from supervisor.wiring import build_runtime

    runtime = build_runtime(load_settings(sql_backend="sqlite", data_dir=tmp_path / "x"))
    set_context(build_context(runtime))
    try:
        r = TestClient(app, raise_server_exceptions=False).get(
            "/v1/sessions/conv-1", headers={"X-Dev-User": "reviewer.an"}
        )
        assert r.status_code == 400 and "SESSION_MONITOR_ENABLED" in r.json()["error"]
    finally:
        set_context(None)
        set_provider(None)
        runtime.close()


def test_resume_route_first_approval_is_pending(rt: Rt) -> None:
    from supervisor.gateway.policy import deploy_policy

    # make the session paused through the real in-request path
    deploy_policy(policy_with(SESSION_CFG), rt.runtime.adapters.state, rt.runtime.adapters.clock)
    rt.runtime.gateway.policy.current()  # refresh
    rt.runtime.adapters.clock  # noqa: B018
    drive(rt.runtime, SPLIT)
    pauses = rt.runtime.adapters.state.query("session_control", {"status": "active"})
    assert len(pauses) == 1
    r = rt.post("/v1/sessions/conv-api/resume", {"agent_id": "payments", "reason": "checked"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending" and r.json()["needs"] == "owner"
    again = rt.post("/v1/sessions/conv-api/resume", {"agent_id": "payments"})
    assert again.status_code == 400  # same person twice
    bad = rt.post("/v1/sessions/conv-api/resume", {"agent_id": "payments", "x": 1})
    assert bad.status_code == 400


# ------------------------------------------------------------------ batch path and status


def test_batch_path_opens_the_case_the_quiet_gate_did_not(adapters, evidence, clock) -> None:
    gw, sg = make_session_gateway(adapters, evidence, policy_with(QUIET))
    feed(gw, clock, SPLIT)
    assert [
        c for c in adapters.state.query("cases") if c["case_type"] == "session_escalation"
    ] == []
    mon = SessionMonitor(
        MonitorContext.from_adapters(adapters, evidence),
        sg.settings,
        policy_with({**SESSION_CFG}),
    )
    res = mon.run(clock.now())
    assert len(res.cases_opened) == 1 and len(res.pauses_set) == 1
    again = mon.run(clock.now())
    assert again.cases_opened == [] and again.pauses_set == []  # idempotent
    st = read_status(
        MonitorContext.from_adapters(adapters, evidence), clock.now().date(), "payments"
    )
    assert st["session"]["status"] == "ok" and st["session"]["n"] >= 1
    # the gate sees a pause written by the batch path
    sg.drop_pauses()
    r = feed(
        gw, clock, [("transfer", {"amount_minor": 1, "from_account_id": "A", "payee_id": "P"}, "x")]
    )[0]
    assert r["rule_id"] == "GATE-SESSION-PAUSE"
    # cool-down expiry through the batch job lifts it and records it on the chain
    clock.advance(SESSION_CFG["cooldown_s"] + 1)
    out = mon.run(clock.now())
    assert len(out.expired) == 1
    assert "session_pause_expired" in [t for t, _, _ in evidence.entries]
    gw.close()


def test_batch_and_in_request_paths_agree_on_the_case(adapters, evidence, clock) -> None:
    gw, sg = make_session_gateway(
        adapters, evidence, policy_with({**SESSION_CFG, "pause_scope": []})
    )
    feed(gw, clock, SPLIT)
    inreq = [c for c in adapters.state.query("cases") if c["case_type"] == "session_escalation"]
    mon = SessionMonitor(
        MonitorContext.from_adapters(adapters, evidence), sg.settings, policy_with({**SESSION_CFG})
    )
    res = mon.run(clock.now())
    assert len(inreq) == 1 and res.cases_opened == []  # the batch path sees the open case
    gw.close()


def test_cold_start_rebuilds_the_window_from_stored_decisions(adapters, evidence, clock) -> None:
    gw, sg = make_session_gateway(
        adapters, evidence, policy_with({**SESSION_CFG, "pause_scope": []})
    )
    feed(gw, clock, SPLIT[:5])
    gw.close()
    gw2, sg2 = make_session_gateway(
        adapters, evidence, policy_with({**SESSION_CFG, "pause_scope": []})
    )
    feed(gw2, clock, SPLIT[5:])
    cases = [c for c in adapters.state.query("cases") if c["case_type"] == "session_escalation"]
    assert len(cases) == 1  # the new process remembered the first five turns
    gw2.close()


def test_databricks_mode_statements_carry_no_session_text(adapters, evidence, clock) -> None:
    """The agent_event row and the session_control row go through the Delta executor (fake) as
    typed parameters; none of them holds the turn text."""
    import json

    from supervisor.adapters.sql.databricks_fake import FakeStatementExecution, dml_result
    from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor
    from supervisor.adapters.sql.store import SqlStateStore, SqlTableStore
    from supervisor.core.schema import load_model

    gw, _ = make_session_gateway(adapters, evidence, policy_with(None))
    feed(gw, clock, SPLIT[3:4])
    row = next(
        r for r in adapters.tables.query("agent_event", {"event_type": "gate_decision"})
        if r["session_id"]
    )  # fmt: skip
    fake = FakeStatementExecution()
    ex = DatabricksRestExecutor(fake, warehouse_id="wh", catalog="c", schema="s")
    model = load_model()
    fake.add(dml_result(1), match="MERGE INTO")
    assert SqlTableStore(ex, model).append("agent_event", [row]) == 1
    fake.add(dml_result(1))
    SqlStateStore(ex, clock, model).insert(
        "session_control",
        {
            "control_id": "c1", "session_id": "conv-1", "agent_id": "payments", "scope": "money",
            "status": "active", "score_bp": 4100, "created_at": clock.now(),
            "expires_at": clock.now() + timedelta(seconds=60),
        },
    )  # fmt: skip
    sent = json.dumps([c.kwargs for c in fake.calls], default=str) + "".join(fake.statements)
    assert "session_id" in sent and "session_control" in sent
    assert "chuyen 90 trieu" not in sent
    gw.close()
