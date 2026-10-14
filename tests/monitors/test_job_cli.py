"""Every WP7 job runs as ``python -m supervisor.jobs.<name>`` (main) with ASCII output."""

from __future__ import annotations

import importlib

import pytest

JOBS = {
    "drift": "[OK] drift:",
    "fairness": "[OK] fairness:",
    "metrics": "[OK] metrics:",
    "multiagent": "[OK] multiagent:",
    "judge_sweep": "[SKIP] judge_sweep: JUDGE_ENABLED is off",
    "quality": "[SKIP] quality: QUALITY_ENABLED is off",
}


@pytest.mark.parametrize("name", sorted(JOBS))
def test_job_main(name: str, capsys: pytest.CaptureFixture[str]) -> None:
    mod = importlib.import_module(f"supervisor.jobs.{name}")
    assert mod.main([]) == 0
    out = capsys.readouterr().out
    assert out.startswith(JOBS[name]), out
    out.encode("ascii")  # ASCII only


def test_fairness_bad_config_fails_cleanly(tmp_path, capsys) -> None:
    from supervisor.jobs import fairness

    bad = tmp_path / "f.yaml"
    bad.write_text("attributes:\n  religion: {permitted: true}\n", encoding="utf-8")
    assert fairness.main(["--config", str(bad)]) == 1
    assert capsys.readouterr().out.startswith("[FAIL] fairness:")


def test_judge_sweep_runs_with_mock_judges(monkeypatch, capsys) -> None:
    from supervisor.jobs import judge_sweep

    for k, v in {"JUDGE_ENABLED": "1", "LLM_MOCK": "1", "JUDGE_T1_FAMILY": "llama",
                 "JUDGE_T2_FAMILY": "mistral"}.items():  # fmt: skip
        monkeypatch.setenv(k, v)
    assert judge_sweep.main([]) == 0
    assert capsys.readouterr().out.startswith("[OK] judge_sweep:")
