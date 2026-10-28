"""Composition root: the gateway records into the WP6 chain; the app builds it at startup."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from supervisor.adapters.factory import build_adapters
from supervisor.config import get_settings, load_settings
from supervisor.evidence.chain import ChainWriter
from supervisor.gateway import wiring as gate_wiring
from supervisor.wiring import build_runtime, register_agents
from supervisor_agents.common.manifest import load_manifest


def test_runtime_gateway_writes_to_the_chain(tmp_path: Path) -> None:
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data")
    rt = build_runtime(settings)
    try:
        assert isinstance(rt.chain, ChainWriter)
        assert rt.gateway.evidence is rt.chain and rt.gateway.states.evidence is rt.chain
        register_agents(rt, [load_manifest("payments")])
        register_agents(rt, [load_manifest("payments")])  # idempotent
        assert rt.adapters.state.get("agent", {"agent_id": "payments"})["gate_state"] == "RUNNING"
        assert len(rt.adapters.tables.query("agent_version", {"agent_id": "payments"})) == 1
        r = rt.gateway.check("payments", "1.0.0", "get_balance", {"account_id": "ACC-1"}, {})
        assert r["allow"] is True
        lane = rt.adapters.tables.query("chain_entry", {"lane": "agent:payments"})
        assert {e["record_type"] for e in lane} == {
            "agent_registered",
            "agent_version",
            "gate_decision",
        }
    finally:
        rt.close()
    with pytest.raises(ValueError, match="not in the deployed policy"):
        rt2 = build_runtime(settings)
        try:
            bad = load_manifest("payments")
            object.__setattr__(bad, "id", "ghost")
            register_agents(rt2, [bad])
        finally:
            rt2.close()


def test_app_startup_installs_chain_backed_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supervisor.app import app

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    get_settings.cache_clear()
    gate_wiring.set_gateway(None)
    try:
        with TestClient(app) as client:
            gw = gate_wiring.get_gateway()
            assert isinstance(gw.evidence, ChainWriter)
            r = client.post(
                "/gate/check",
                json={
                    "agent_id": "payments",
                    "agent_version": "1.0.0",
                    "tool_name": "ext_transfer_api",
                    "args": {"amount_minor": 1000, "to_account": "1"},
                    "context": {"caller_agent_id": "customer_service"},
                },
            )
            assert r.status_code == 200 and r.json()["rule_id"] == "PAY-07"
        a = build_adapters(load_settings(sql_backend="sqlite", data_dir=tmp_path / "data"))
        try:
            rows = a.tables.query("chain_entry", {"record_type": "gate_decision"})
            assert len(rows) == 1
            roots = a.tables.query("chain_entry", {"lane": "root"})
            assert roots and roots[-1]["seq"] >= 1  # sealed at shutdown
        finally:
            a.close()
    finally:
        gate_wiring.set_gateway(None)
        get_settings.cache_clear()


def test_app_still_serves_when_runtime_build_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from supervisor.app import app

    def broken(*_a: object, **_k: object) -> None:
        raise RuntimeError("store unavailable at startup")

    monkeypatch.setattr(gate_wiring, "install_runtime", broken)
    gate_wiring.set_gateway(None)
    try:
        with TestClient(app) as client:
            assert client.get("/healthz").json()["status"] == "ok"
    finally:
        gate_wiring.set_gateway(None)


def test_gate_time_budgets_come_from_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WP-P6: GATE_DECISION_TIMEOUT_S, POLICY_REFRESH_S and STATE_CACHE_TTL_S reach the engine
    (a Databricks store needs more than the 2 s local default)."""
    monkeypatch.setenv("GATE_DECISION_TIMEOUT_S", "7.5")
    monkeypatch.setenv("POLICY_REFRESH_S", "30")
    monkeypatch.setenv("STATE_CACHE_TTL_S", "9")
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data")
    assert settings.gate_decision_timeout_s == 7.5
    rt = build_runtime(settings)
    try:
        assert rt.gateway.timeout_s == 7.5
        assert rt.gateway.policy.refresh_s == 30
        assert rt.gateway.states.cache_ttl_s == 9
    finally:
        rt.close()
    rt0 = build_runtime(settings, policy_refresh_s=0.0)  # an explicit value still wins
    try:
        assert rt0.gateway.policy.refresh_s == 0.0
    finally:
        rt0.close()


def test_gate_time_budgets_default_unchanged(tmp_path: Path) -> None:
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data")
    assert (settings.gate_decision_timeout_s, settings.policy_refresh_s) == (2.0, 5.0)
    assert settings.state_cache_ttl_s == 1.0
