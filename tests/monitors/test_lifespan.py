"""App lifespan: scheduler starts after the runtime, stops before the chain is sealed."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from supervisor import scheduler as sched_mod
from supervisor.config import get_settings
from supervisor.gateway import wiring as gate_wiring


@pytest.fixture
def app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    get_settings.cache_clear()
    gate_wiring.set_gateway(None)
    yield monkeypatch
    gate_wiring.set_gateway(None)
    get_settings.cache_clear()


def _record_order(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real_stop, real_shutdown = sched_mod.stop, gate_wiring.shutdown_runtime

    def stop() -> None:
        calls.append("scheduler.stop")
        real_stop()

    def shutdown() -> None:
        calls.append("shutdown_runtime")
        real_shutdown()

    monkeypatch.setattr(sched_mod, "stop", stop)
    monkeypatch.setattr(gate_wiring, "shutdown_runtime", shutdown)
    return calls


def test_laptop_mode_starts_scheduler_and_stops_it_before_seal(app_env) -> None:
    from supervisor.app import app

    calls = _record_order(app_env)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        s = sched_mod.current()
        assert s is not None and s.running
    assert calls == ["scheduler.stop", "shutdown_runtime"]
    assert sched_mod.current() is None and not s.running


@pytest.mark.parametrize(("env", "value"), [("SCHEDULER_ENABLED", "0"), ("SUPERVISOR_MODE", "dev")])
def test_scheduler_off_outside_laptop_mode_or_when_disabled(app_env, env, value) -> None:
    from supervisor.app import app

    app_env.setenv(env, value)
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert sched_mod.current() is None
