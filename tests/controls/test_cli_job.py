"""WP30: the CLIs, the jobs, the scheduler entries, the launch hook and the settings (all off by
default)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from supervisor.config import load_settings
from supervisor.controls import __main__ as ccli
from supervisor.jobs import control_status as cjob
from supervisor.jobs import task_due as tjob
from supervisor.tasks import __main__ as tcli
from tests.conftest import REPO_ROOT

from .conftest import ListSink

STARTERS = REPO_ROOT / "config" / "controls"
RISKS = REPO_ROOT / "config" / "risks"


def _on(monkeypatch: pytest.MonkeyPatch, on: bool = True) -> None:
    if on:
        monkeypatch.setenv("CONTROLS_ENABLED", "1")
    else:
        monkeypatch.delenv("CONTROLS_ENABLED", raising=False)
    monkeypatch.setenv("RISK_REGISTER_ENABLED", "1")
    monkeypatch.setenv("INVENTORY_ENABLED", "1")
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("LLM_BASE_URL", "")


def test_settings_default_off(tmp_path: Path) -> None:
    s = load_settings(sql_backend="sqlite", data_dir=tmp_path / "d", llm_base_url="")
    assert s.controls_enabled is False and s.console_controls_enabled is False
    assert s.tasks_launch_gate_enabled is False
    assert s.sched_control_status_s == 21600 and s.controls_pack_window_days == 30
    assert s.controls_starter_dir == STARTERS and s.tasks_config == REPO_ROOT / "config/tasks.yaml"


def test_cli_and_jobs_are_noops_when_off(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _on(monkeypatch, False)
    assert ccli.main(["list"]) == 0
    assert ccli.main(["import", str(STARTERS), "--by", "ann"]) == 0
    assert tcli.main(["list"]) == 0
    assert tcli.main(["generate", "--agent", "payments", "--by", "x"]) == 0
    assert cjob.main([]) == 0 and tjob.main([]) == 0
    assert capsys.readouterr().out.count("[SKIP]") == 6


def test_plan_needs_no_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _on(monkeypatch, False)
    assert tcli.main(["plan", "--class", "high_risk", "--band", "low"]) == 0
    out = capsys.readouterr().out
    assert "level high" in out and "DES-D33*" in out and out.isascii()


def test_controls_cli_import_list_status_export_and_jobs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from supervisor.adapters.factory import build_adapters
    from supervisor.risk import __main__ as rcli

    _on(monkeypatch)
    a0 = build_adapters(load_settings())
    try:
        from supervisor.jobs import bootstrap_schema

        bootstrap_schema.run(a0.settings, a0)
        for name in ("payments", "customer_service", "credit_prequal"):
            a0.state.insert(
                "agent",
                {
                    "agent_id": name, "name": name, "owner_team": "t", "owner_user": "u",
                    "risk_tier": "high", "host_type": "python_inprocess",
                    "plug_point": "gate_hook", "model_family": "qwen", "status": "active",
                    "gate_state": "RUNNING", "created_at": a0.clock.now(),
                },
            )  # fmt: skip
    finally:
        a0.close()
    assert rcli.main(["import", str(RISKS), "--source", "starter", "--by", "ann"]) == 0
    capsys.readouterr()
    assert (
        ccli.main(["import", str(STARTERS), "--dry-run", "--source", "starter", "--by", "ann"]) == 0
    )
    assert "dry run: created=0" in capsys.readouterr().out
    assert ccli.main(["import", str(STARTERS), "--source", "starter", "--by", "ann"]) == 0
    assert "created=28" in capsys.readouterr().out
    assert ccli.main(["import", str(STARTERS), "--source", "starter", "--by", "ann"]) == 0
    assert "unchanged=28" in capsys.readouterr().out
    assert ccli.main(["list", "--agent", "payments", "--type", "preventive"]) == 0
    out = capsys.readouterr().out
    assert "CTL-PAY-LIMIT" in out and "CTL-CRD-LIMIT" not in out and out.isascii()
    assert ccli.main(["export", "--out", str(tmp_path / "x")]) == 0
    assert (tmp_path / "x" / "controls.csv").is_file()
    assert (tmp_path / "x" / "control_maps.csv").is_file()
    capsys.readouterr()
    assert ccli.main(["status", "--run", "--by", "ann"]) == 0
    out = capsys.readouterr().out
    assert "status pass" in out and "written=" in out and out.isascii()
    assert cjob.main([]) == 0
    assert "written=0" in capsys.readouterr().out  # same window: nothing new
    # the task flow from the command line
    assert tcli.main(["generate", "--agent", "payments", "--by", "olga"]) == 0
    assert "stage initiation" in capsys.readouterr().out
    assert tcli.main(["list", "--agent", "payments"]) == 0
    assert "INI-REGISTER" in capsys.readouterr().out
    assert tcli.main(["waive", "x", "--by", "olga", "--reason", "r"]) == 1
    assert tjob.main(["--no-cases"]) == 0
    assert "task_due:" in capsys.readouterr().out
    a = build_adapters(load_settings())
    try:
        assert a.tables.query("chain_entry", {"record_type": "control_change"})
        assert a.tables.query("chain_entry", {"record_type": "control_status"})
        assert a.tables.query("chain_entry", {"record_type": "task_change"})
    finally:
        a.close()


def test_scheduler_lists_the_jobs_only_when_on(env, sink: ListSink) -> None:  # type: ignore[no-untyped-def]
    from supervisor.monitors.common import MonitorContext
    from supervisor.scheduler import build_jobs

    adapters = env.adapters
    runtime = SimpleNamespace(adapters=adapters, chain=sink, settings=adapters.settings)
    ctx = MonitorContext.from_adapters(adapters, sink)
    adapters.settings.controls_enabled = False
    names = {j.name for j in build_jobs(adapters.settings, runtime, ctx)}
    assert not names & {"control_status", "task_due"}
    adapters.settings.controls_enabled = True
    jobs = {j.name: j for j in build_jobs(adapters.settings, runtime, ctx)}
    assert jobs["control_status"].interval_s == 21600 and jobs["task_due"].interval_s == 3600
    assert jobs["control_status"].fn()["written"] == 0


def test_modules_have_help() -> None:
    for module in (ccli, tcli, cjob, tjob):
        with pytest.raises(SystemExit) as stop:
            module.main(["--help"])
        assert stop.value.code == 0


# ---- the launch hook ----------------------------------------------------------------------------


def _report(go: bool = True):  # type: ignore[no-untyped-def]
    from supervisor.onboard.models import LaunchReport

    return LaunchReport.model_construct(go=go, reasons=["all integration checks pass"])


def test_launch_hook_is_additive_and_deterministic(env) -> None:  # type: ignore[no-untyped-def]
    from supervisor.assurance.gates import task_launch_items
    from supervisor.onboard.launch import _with_tasks

    rows = [
        {"template_id": "B", "stage": "design", "status": "open", "title": "Second"},
        {"template_id": "A", "stage": "design", "status": "in_progress", "title": "First"},
    ]
    assert task_launch_items(rows) == task_launch_items(list(reversed(rows)))
    assert task_launch_items(rows)[0] == "task A of the design stage is in_progress: First"
    out = _with_tasks(_report(), "pay", rows, env.settings)
    assert out.go is False and out.tasks_enabled and len(out.task_reasons) == 2
    assert "all integration checks pass" not in out.reasons  # the GO line is replaced
    nogo = _with_tasks(_report(False), "pay", rows, env.settings)
    assert nogo.reasons[0] == "all integration checks pass"  # earlier NO-GO reasons are kept
    ok = _with_tasks(_report(), "pay", [], env.settings)
    assert ok.go is True and ok.task_reasons == []


def test_launch_unreadable_task_list_is_no_go(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from supervisor.onboard import launch as L

    def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise RuntimeError("store down")

    monkeypatch.setattr("supervisor.tasks.service.launch_tasks_for", boom)
    out = L._with_tasks(_report(), "pay", None, env.settings)
    assert out.go is False and "could not be read" in out.task_reasons[-1]


def test_launch_flag_off_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from supervisor.onboard import launch as L

    called: list[int] = []
    monkeypatch.setattr(L, "_with_tasks", lambda *a, **k: called.append(1))
    monkeypatch.setattr(L, "_launch_core", lambda *a, **k: _report())
    monkeypatch.delenv("CONTROLS_ENABLED", raising=False)
    monkeypatch.delenv("TASKS_LAUNCH_GATE_ENABLED", raising=False)
    monkeypatch.delenv("ASSURANCE_LAUNCH_ENABLED", raising=False)
    out = L.launch(None, "pay", ".")  # type: ignore[arg-type]
    assert out.tasks_enabled is False and called == []
    monkeypatch.setenv("CONTROLS_ENABLED", "1")
    L.launch(None, "pay", ".")  # type: ignore[arg-type]
    assert called == []  # the gate has its own flag
    monkeypatch.setenv("TASKS_LAUNCH_GATE_ENABLED", "1")
    L.launch(None, "pay", ".")  # type: ignore[arg-type]
    assert called == [1]
