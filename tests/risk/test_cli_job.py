"""WP29: the CLI (python -m supervisor.risk), the job (python -m supervisor.jobs.risk_evidence),
the scheduler entry and the settings (all off by default)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from supervisor.config import load_settings
from supervisor.jobs import risk_evidence as job
from supervisor.risk import __main__ as cli
from tests.conftest import REPO_ROOT

from .conftest import STARTERS, ListSink


def _on(monkeypatch: pytest.MonkeyPatch, on: bool = True) -> None:
    if on:
        monkeypatch.setenv("RISK_REGISTER_ENABLED", "1")
    else:
        monkeypatch.delenv("RISK_REGISTER_ENABLED", raising=False)
    monkeypatch.setenv("INVENTORY_ENABLED", "1")
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("LLM_BASE_URL", "")


def test_settings_default_off(tmp_path: Path) -> None:
    s = load_settings(sql_backend="sqlite", data_dir=tmp_path / "d", llm_base_url="")
    assert s.risk_register_enabled is False and s.console_risks_enabled is False
    assert s.sched_risk_evidence_s == 21600 and s.risk_evidence_window_days == 7
    assert s.risk_config == REPO_ROOT / "config" / "risk.yaml"
    assert s.risk_starter_dir == REPO_ROOT / "config" / "risks"


def test_cli_is_a_noop_when_off(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _on(monkeypatch, False)
    for argv in (["list"], ["score"], ["import", str(STARTERS)], ["export", "--out", "x"]):
        assert cli.main(argv) == 0
    assert capsys.readouterr().out.count("[SKIP]") == 4


def test_cli_import_list_score_export(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _on(monkeypatch)
    assert cli.main(["import", str(STARTERS), "--dry-run", "--source", "starter"]) == 0
    assert "dry run: created=0" in capsys.readouterr().out
    assert cli.main(["import", str(STARTERS), "--source", "starter"]) == 0
    assert "created=19" in capsys.readouterr().out
    assert cli.main(["import", str(STARTERS), "--source", "starter"]) == 0
    assert "unchanged=19" in capsys.readouterr().out

    assert cli.main(["list", "--agent", "payments", "--band", "critical"]) == 0
    out = capsys.readouterr().out
    assert "RSK-PAY-001" in out and "RSK-CRD-001" not in out and "[OK] 2 risk(s)" in out
    assert cli.main(["list"]) == 0
    assert "[OK] 19 risk(s)" in capsys.readouterr().out

    assert cli.main(["score"]) == 0
    out = capsys.readouterr().out
    assert "payments" in out and "critical" in out and "ILLUSTRATIVE" in out
    assert cli.main(["score", "--agent", "credit_prequal"]) == 0
    out = capsys.readouterr().out
    assert "credit_prequal" in out and "customer_service" not in out

    dest = tmp_path / "out"
    assert cli.main(["export", "--out", str(dest)]) == 0
    assert sorted(p.name for p in dest.iterdir()) == ["risk_links.csv", "risks.csv", "risks.json"]
    doc = json.loads((dest / "risks.json").read_text(encoding="utf-8"))
    assert len(doc["risks"]) == 19
    assert cli.main(["export", "--out", str(tmp_path / "j"), "--format", "json"]) == 0
    assert [p.name for p in (tmp_path / "j").iterdir()] == ["risks.json"]
    assert capsys.readouterr().out.isascii()


def test_cli_import_errors_are_ascii_and_exit_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _on(monkeypatch)
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "risks:\n  - {id: X-1, agent: payments, title: t, category: nope}\n", encoding="utf-8"
    )
    assert cli.main(["import", str(bad)]) == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out and "nothing was imported" in out and out.isascii()
    assert cli.main(["import", str(tmp_path / "missing.yaml")]) == 1
    assert "[FAIL]" in capsys.readouterr().out


def test_cli_import_writes_chain_records(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from supervisor.adapters.factory import build_adapters

    _on(monkeypatch)
    assert cli.main(["import", str(STARTERS), "--source", "starter"]) == 0
    a = build_adapters(load_settings())
    try:
        rows = a.tables.query("chain_entry", {"record_type": "risk_change"})
        assert len(rows) == 19  # one change record per created risk
    finally:
        a.close()


def test_job_is_a_noop_when_off(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _on(monkeypatch, False)
    assert job.main([]) == 0
    assert "[SKIP]" in capsys.readouterr().out


def test_job_standalone_writes_evidence_and_chain(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from supervisor.adapters.factory import build_adapters

    _on(monkeypatch)
    assert cli.main(["import", str(STARTERS), "--source", "starter"]) == 0
    capsys.readouterr()
    assert job.main([]) == 0
    out = capsys.readouterr().out
    assert "[OK] risk_evidence:" in out and "written=19" in out and out.isascii()
    assert job.main([]) == 0
    assert "written=0" in capsys.readouterr().out  # same window: nothing new
    a = build_adapters(load_settings())
    try:
        assert len(a.tables.query("risk_evidence")) == 19
        assert len(a.tables.query("chain_entry", {"record_type": "risk_evidence"})) == 19
    finally:
        a.close()


def test_scheduler_lists_the_job_only_when_on(adapters, sink: ListSink) -> None:  # type: ignore[no-untyped-def]
    from supervisor.monitors.common import MonitorContext
    from supervisor.scheduler import build_jobs

    runtime = SimpleNamespace(adapters=adapters, chain=sink, settings=adapters.settings)
    ctx = MonitorContext.from_adapters(adapters, sink)
    adapters.settings.risk_register_enabled = False
    jobs = {j.name: j for j in build_jobs(adapters.settings, runtime, ctx)}
    assert "risk_evidence" not in jobs  # off: not listed (like the inventory job)
    adapters.settings.risk_register_enabled = True
    jobs = {j.name: j for j in build_jobs(adapters.settings, runtime, ctx)}
    assert jobs["risk_evidence"].enabled is True and jobs["risk_evidence"].interval_s == 21600
    assert jobs["risk_evidence"].fn()["risks"] == 0  # nothing imported yet


def test_modules_have_help() -> None:
    for module in (cli, job):
        with pytest.raises(SystemExit) as stop:
            module.main(["--help"])
        assert stop.value.code == 0
