"""WP31 CLI and job: off by default, build writes a preview, the job signs and is idempotent."""

from __future__ import annotations

from pathlib import Path

import pytest

from supervisor.jobs import transparency as job
from supervisor.monitors.common import MonitorContext
from supervisor.transparency import __main__ as cli
from supervisor.transparency.harness import Env


def test_job_signs_running_agents_then_changes_nothing(env: Env) -> None:
    ctx = MonitorContext.from_adapters(env.adapters, env.rt.chain)
    first = job.run(ctx, env.settings)
    assert first["agents"] == 3 and first["made"] == 9 and first["failed"] == 0
    second = job.run(ctx, env.settings)
    assert second["made"] == 0 and second["unchanged"] == 9


def test_job_skips_a_retired_agent(env: Env) -> None:
    env.add_agent("probe_gone", status="retired")
    ctx = MonitorContext.from_adapters(env.adapters, env.rt.chain)
    assert job.run(ctx, env.settings)["agents"] == 3


def test_job_main_is_off_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.delenv("TRANSPARENCY_ENABLED", raising=False)
    assert job.main([]) == 0
    assert "[SKIP]" in capsys.readouterr().out


def test_cli_build_writes_files_and_never_overwrites(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("TRANSPARENCY_ENABLED", "1")
    out = tmp_path / "out"
    args = ["build", "payments", "--variant", "customer", "--format", "all", "--lang", "both"]
    # the agent is not registered in this empty store
    assert cli.main([*args, "--out", str(out)]) == 1
    assert "[FAIL]" in capsys.readouterr().out


def test_cli_build_for_a_registered_agent(
    env: Env, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATA_DIR", str(env.settings.data_dir))
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("TRANSPARENCY_ENABLED", "1")
    env.rt.chain.commit_root(force=True)
    out = tmp_path / "out"
    argv = ["build", "payments", "--variant", "regulator", "--format", "html", "--out", str(out)]
    assert cli.main(argv) == 0
    text = capsys.readouterr().out
    assert "[OK]" in text and text.isascii()
    assert (out / "transparency-payments-regulator.en.html").is_file()
    assert cli.main(argv) == 1  # the file exists: refused
    assert "refusing to overwrite" in capsys.readouterr().out


def test_cli_help() -> None:
    with pytest.raises(SystemExit) as stop:
        cli.main(["--help"])
    assert stop.value.code == 0


def test_scheduler_lists_the_job_only_when_on(env: Env) -> None:
    """Review of WP31: flag off, no scheduler job (like the risk register job)."""
    from types import SimpleNamespace

    from supervisor.monitors.common import MonitorContext
    from supervisor.scheduler import build_jobs

    runtime = SimpleNamespace(adapters=env.adapters, chain=env.rt.chain, settings=env.settings)
    ctx = MonitorContext.from_adapters(env.adapters, env.rt.chain)
    env.settings.transparency_enabled = False
    assert "transparency" not in {j.name for j in build_jobs(env.settings, runtime, ctx)}
    env.settings.transparency_enabled = True
    jobs = {j.name: j for j in build_jobs(env.settings, runtime, ctx)}
    assert jobs["transparency"].interval_s == env.settings.sched_transparency_s == 86400
