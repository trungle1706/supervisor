"""WP-G5 off path: with GOVERNANCE_ACTIONS_ENABLED off nothing is mounted, nothing is scheduled,
no table gets a row, and the console and the system pages are as before. Then the job: the
scheduler entry, the command line and the dry run."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from supervisor.app import app
from supervisor.config import Settings, load_settings
from supervisor.governance import event_sources as src
from supervisor.jobs import governance_actions as job
from supervisor.monitors.common import MonitorContext
from supervisor.scheduler import SupervisorScheduler, build_jobs

from .conftest import Console
from .g5_support import Rig, only, rule


def test_the_flag_is_off_by_default_and_the_defaults() -> None:
    assert Settings.model_fields["governance_actions_enabled"].default is False
    assert Settings.model_fields["sched_governance_s"].default == 60
    s = load_settings(sql_backend="sqlite", llm_base_url="")
    assert s.governance_actions_enabled is False and s.sched_governance_s == 60
    assert s.governance_actions_config.name == "governance_actions.yaml"
    assert s.governance_actions_config.is_absolute()  # resolved once at load
    assert not job.enabled(s)


def test_the_job_needs_both_flags(tmp_path: Path) -> None:
    kw = {"sql_backend": "sqlite", "data_dir": tmp_path / "d", "llm_base_url": ""}
    assert not job.enabled(load_settings(**kw, governance_actions_enabled=True))
    assert not job.enabled(load_settings(**kw, governance_enabled=True))
    assert job.enabled(
        load_settings(**kw, governance_actions_enabled=True, governance_enabled=True)
    )


def test_no_route_is_mounted_with_the_flag_off() -> None:
    from tests.console.test_rbac_matrix import app_routes

    paths = {p for _, p, _ in app_routes()}
    assert not [p for p in paths if "incident" in p]
    assert not [p for p in app.openapi()["paths"] if "incident" in p]


@pytest.mark.parametrize(
    "path",
    [
        "/v1/incidents",
        "/v1/incidents/inc_000000000000000000000000",
        "/v1/incidents/inc_000000000000000000000000/transition",
        "/console/incidents",
        "/console/incidents/rows",
        "/console/incidents/inc_000000000000000000000000/drawer",
    ],
)
def test_the_urls_do_not_exist_with_the_flag_off(console: Console, path: str) -> None:
    for method in ("GET", "POST"):
        r = console.client.request(method, path, json={}, headers={"X-Dev-User": "reviewer.an"})
        assert r.status_code in (404, 405), (method, path, r.status_code)


def test_the_tables_stay_empty_and_the_ui_is_as_before(console: Console) -> None:
    for table in ("incident", "governance_event"):
        assert console.ctx.state.query(table) == []
    html = console.get("/console/?lang=en").text
    assert "/console/incidents" not in html
    for page in ("/console/cases", "/console/alerts"):
        assert "/console/incidents" not in console.get(page).text
    console.ctx.settings.console_nav_v3 = True
    assert "/console/incidents" not in console.get("/console/cases").text


def test_the_flag_does_nothing_to_the_page_flags_unless_governance_is_on() -> None:
    from supervisor.console.readmodels import ux3_pages

    s = load_settings(sql_backend="sqlite", llm_base_url="", governance_actions_enabled=True)
    assert ux3_pages(s)["incidents"] is False  # needs GOVERNANCE_ENABLED too
    s = load_settings(
        sql_backend="sqlite",
        llm_base_url="",
        governance_actions_enabled=True,
        governance_enabled=True,
    )
    assert ux3_pages(s)["incidents"] is True


def test_the_scheduler_lists_the_job_only_when_both_flags_are_on(rig: Rig) -> None:
    settings = rig.a.settings
    runtime = SimpleNamespace(adapters=rig.a, chain=rig.sink, settings=settings)
    ctx = MonitorContext.from_adapters(rig.a, rig.sink)

    def names() -> set[str]:
        return {j.name for j in build_jobs(settings, runtime, ctx)}

    settings.governance_actions_enabled = False
    assert "governance_actions" not in names()
    settings.governance_actions_enabled, settings.governance_enabled = True, False
    assert "governance_actions" not in names()
    settings.governance_enabled = True
    jobs = {j.name: j for j in build_jobs(settings, runtime, ctx)}
    assert jobs["governance_actions"].interval_s == 60 and jobs["governance_actions"].enabled
    # with the flag off the shipped job list is the one before WP-G5
    settings.governance_actions_enabled = False
    assert names() == {n for n in names() if n != "governance_actions"}


def test_the_scheduler_tick_runs_the_job_and_a_failure_is_recorded(rig: Rig) -> None:
    from supervisor.scheduler import FileLease

    settings = rig.a.settings
    runtime = SimpleNamespace(adapters=rig.a, chain=rig.sink, settings=settings)
    ctx = MonitorContext.from_adapters(rig.a, rig.sink)
    rig.alert("al_1", severity="critical")
    rig.system()
    jobs = [j for j in build_jobs(settings, runtime, ctx) if j.name == "governance_actions"]
    (spec,) = jobs
    sched = SupervisorScheduler(
        jobs, ctx=ctx, lease=FileLease(settings.data_dir / "lock.json", 60), clock=rig.a.clock
    )
    run = sched.run_job("governance_actions")
    assert run.status == "ok", run.error
    assert run.result["handled"] >= 1
    assert rig.a.state.query("incident")
    # a bad rules file is a failed run in the scheduler record, not a crash
    settings.governance_actions_config = settings.data_dir / "missing.yaml"
    assert sched.run_job(spec.name).status == "error"


def test_run_refuses_when_governance_is_off(rig: Rig) -> None:
    rig.a.settings.governance_enabled = False
    from supervisor.governance.model import GovernanceOff

    with pytest.raises(GovernanceOff):
        job.run(rig.ctx, rig.a.settings, rig.runner(only([rule("alert", ["create_incident"])])))


def test_command_line_is_skipped_when_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.delenv("GOVERNANCE_ACTIONS_ENABLED", raising=False)
    assert job.main([]) == 0
    out = capsys.readouterr().out
    assert "[SKIP]" in out and out.isascii()


def test_command_line_dry_run_prints_the_plan_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("GOVERNANCE_ENABLED", "1")
    monkeypatch.setenv("GOVERNANCE_ACTIONS_ENABLED", "1")
    # an empty store: the run reads every source and finds nothing
    assert job.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "[OK] governance_actions (dry run)" in out and out.isascii()
    assert "events=0" in out
    assert job.main([]) == 0
    assert "[OK] governance_actions:" in capsys.readouterr().out


def test_every_source_name_is_a_cursor_key(rig: Rig) -> None:
    rig.runner(only([rule("alert", ["create_incident"])])).run()
    cursors = {
        r["state_key"]
        for r in rig.a.state.query("monitor_state", {"monitor": "governance_actions"})
    }
    assert cursors == {f"cursor:{n}" for n in src.SOURCES}
