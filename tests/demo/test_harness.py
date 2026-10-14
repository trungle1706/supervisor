"""WP11 demo harness: seed, inject, tamper, reset, replay fallback (fresh SQLite, MockChat)."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from supervisor.config import Settings
from supervisor.demo import fallback, inject, reset, runbook, seed, tamper
from supervisor.demo.session import (
    MARKER,
    DemoSession,
    build_session,
    demo_settings,
    open_session,
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return demo_settings(tmp_path / "demo", llm_base_url="")


@pytest.fixture
def seeded(settings: Settings) -> Settings:
    rep = seed.seed(settings, echo=lambda _l: None)
    assert rep.ok, "\n".join(rep.lines)
    return settings


@pytest.fixture
def session(seeded: Settings) -> Iterator[DemoSession]:
    s = build_session(seeded)
    try:
        yield s
    finally:
        s.close()


def test_demo_settings_keep_everything_under_the_data_dir(settings: Settings) -> None:
    d = Path(settings.data_dir)
    for p in (settings.sqlite_path, settings.signer_key_path, settings.console_export_dir):
        assert Path(str(p)).is_relative_to(d)
    assert Path(str(settings.anchor_path)).is_relative_to(d)
    assert settings.effective_sql_backend == "sqlite"


def test_seed_is_quiet_and_takes_a_snapshot(seeded: Settings) -> None:
    facts = reset.store_facts(seeded)
    assert facts["cases"] == 0 and facts["chain_entries"] > 0 and facts["gate_decisions"] > 50
    assert set(facts["agent_states"].values()) == {"RUNNING"}
    assert reset.has_snapshot(Path(seeded.data_dir))
    assert (Path(seeded.data_dir) / MARKER).is_file()


def test_seed_refuses_to_wipe_a_foreign_dir(tmp_path: Path) -> None:
    foreign = tmp_path / "real"
    foreign.mkdir()
    (foreign / "supervisor.db").write_text("not demo", encoding="utf-8")
    with pytest.raises(seed.SeedError, match="refusing to wipe"):
        seed.wipe(foreign)
    assert (foreign / "supervisor.db").exists()


@pytest.mark.parametrize(
    "n,rule,action",
    [
        (1, "PAY-07", "pause"),
        (2, "SVC-02", "block"),
        (3, "CRD-01", "block"),
        (4, "PAY-08", "block"),
    ],
)
def test_each_incident_is_stopped_by_a_real_rule_and_opens_a_case(
    session: DemoSession, n: int, rule: str, action: str
) -> None:
    rep = inject.inject(session, n, echo=lambda _l: None, auto_resume=True)
    text = "\n".join(rep.lines)
    assert rep.ok, text
    assert f"rule {rule} (real rule match)" in text
    verdicts = session.tables.query("verdict", {"rule_id": rule, "action": action})
    assert verdicts and all(v["tier"] == 0 and not v["is_mock"] for v in verdicts)
    assert rep.case_ids and all(session.cases.get(c) for c in rep.case_ids)
    assert all(line.isascii() for line in rep.lines)
    if action == "pause":
        assert "gate_state=PAUSED (read back from the store)" in text
        assert "resumed by two people" in text
    assert session.state.get("agent", {"agent_id": "payments"})["gate_state"] == "RUNNING"


def test_inject_refuses_when_the_agent_is_already_paused(session: DemoSession) -> None:
    rep = inject.inject(session, 1, echo=lambda _l: None)  # no auto resume: stays PAUSED
    assert rep.ok
    again = inject.inject(session, 4, echo=lambda _l: None)
    assert not again.ok
    assert any("payments is PAUSED" in line for line in again.lines)


def test_judge_beat_is_advisory_and_labelled_mock(session: DemoSession) -> None:
    rep = inject.inject(session, 2, echo=lambda _l: None)
    judge = [line for line in rep.lines if "judge" in line]
    assert judge and any("MOCK" in line for line in judge)
    assert any("never calls the gate" in line for line in judge)
    rows = session.tables.query("verdict", {"agent_id": "customer_service"})
    assert any(r["tier"] in (1, 2) and r["advisory"] and r["is_mock"] for r in rows)


def test_tamper_breaks_the_copy_and_never_the_original(session: DemoSession) -> None:
    inject.inject(session, 4, echo=lambda _l: None)
    rep = tamper.tamper(session, echo=lambda _l: None)
    assert rep.ok, "\n".join(rep.lines)
    assert "PAY-08 -> PAY-09" in rep.target
    assert rep.original_dir and rep.tampered_dir
    a = (rep.original_dir / "payloads.jsonl").read_bytes()
    b = (rep.tampered_dir / "payloads.jsonl").read_bytes()
    assert len(a) == len(b) and sum(x != y for x, y in zip(a, b, strict=True)) == 1
    assert any("verify TAMPERED copy: RESULT FAIL" in line for line in rep.lines)
    assert any("verifier: FAIL lane agent:payments" in line for line in rep.lines)


def test_reset_restores_the_snapshot(seeded: Settings) -> None:
    before = reset.store_facts(seeded)
    with open_session(seeded) as s:
        inject.inject(s, 1, echo=lambda _l: None)  # payments PAUSED, a case opened
    dirty = reset.store_facts(seeded)
    assert dirty["cases"] == 1 and dirty["agent_states"]["payments"] == "PAUSED"
    t0 = time.perf_counter()
    rep = reset.restore(seeded, echo=lambda _l: None)
    assert rep.ok and time.perf_counter() - t0 < 5
    assert reset.store_facts(seeded) == before


def test_reset_without_snapshot_names_the_fix(settings: Settings) -> None:
    Path(settings.data_dir).mkdir(parents=True)
    (Path(settings.data_dir) / MARKER).write_text("x", encoding="utf-8")
    with pytest.raises(reset.ResetError, match="demo seed"):
        reset.restore(settings, echo=lambda _l: None)


# ------------------------------------------------------------------ replay fallback


def test_deadline_reports_a_slow_step() -> None:
    slow = fallback.run_with_deadline(lambda: time.sleep(0.5), 0.05)
    assert not slow.ok and slow.timed_out
    boom = fallback.run_with_deadline(lambda: 1 / 0, 1.0)
    assert not boom.ok and "ZeroDivisionError" in str(boom.error)
    assert fallback.run_with_deadline(lambda: 7, 1.0).value == 7


@pytest.mark.parametrize("step", ["gate-DEMO-1", "pause-DEMO-1", "tamper", "chain"])
def test_controls_can_never_be_replayed(step: str, tmp_path: Path) -> None:
    assert not fallback.is_replayable(step)
    with pytest.raises(ValueError):
        fallback.load_twin(step, tmp_path)
    with pytest.raises(ValueError):
        fallback.record_twin(step, ["[OK] x"], source="test", replay_dir=tmp_path)


def test_committed_twin_is_labelled() -> None:
    twin = fallback.load_twin("judge-DEMO-2")
    assert twin is not None and "RECORDED" in twin["label"] and twin["recorded_at"]
    lines = fallback.replay_lines(twin)
    assert all(line.startswith("[REPLAY]") for line in lines)


def _break_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    from supervisor.judge import service

    def broken(*_a: object, **_k: object) -> None:
        raise RuntimeError("judge endpoint unreachable")

    monkeypatch.setattr(service.JudgeService, "from_settings", broken)


def test_judge_failure_without_replay_is_a_fail(
    session: DemoSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _break_judge(monkeypatch)
    rep = inject.inject(session, 2, echo=lambda _l: None)
    assert not rep.ok and any("--replay" in line for line in rep.lines)


def test_judge_failure_with_replay_uses_the_labelled_twin(
    session: DemoSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _break_judge(monkeypatch)
    rep = inject.inject(session, 2, echo=lambda _l: None, replay=True)
    assert rep.ok, "\n".join(rep.lines)
    assert rep.replayed == ["judge-DEMO-2"]
    replayed = [line for line in rep.lines if "judge" in line and "tier" in line]
    assert replayed and all(line.startswith("[REPLAY]") for line in replayed)
    # the gate block in the same incident is still live, never replayed
    assert any(line.startswith("[OK] gate BLOCKED") for line in rep.lines)


def test_record_twin_round_trip(tmp_path: Path) -> None:
    path = fallback.record_twin(
        "judge-DEMO-9", ["[OK] judge a", "[REPLAY] old"], source="t", replay_dir=tmp_path
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["lines"] == ["[OK] judge a"] and data["step"] == "judge-DEMO-9"


# ------------------------------------------------------------------ runbook


def test_runbook_one_run_passes_and_is_ascii(settings: Settings) -> None:
    lines: list[str] = []
    rep = runbook.run_once(settings, echo=lines.append)
    assert rep.ok, "\n".join(lines)
    assert all(line.isascii() for line in lines)
    assert lines[-1].startswith("[OK] demo run 1: PASS")
    assert not [ln for ln in lines if ln.startswith("[FAIL]")]
    assert {"seed", "inject-1", "inject-4", "tamper", "reset"} <= set(rep.step_seconds)


def test_runbook_reports_a_deviation(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """A gate that lets the attack through must turn the run red (exit non-zero)."""
    from supervisor.demo import replay as R
    from supervisor_agents.common.gate import AllowAllHook

    real = R.replay

    def no_gate(*a: object, **k: object) -> object:
        k["gate"] = AllowAllHook()
        return real(*a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(R, "replay", no_gate)
    lines: list[str] = []
    rep = runbook.run_once(settings, echo=lines.append)
    assert not rep.ok
    assert any(ln.startswith("[FAIL] DEMO-1 attack EXECUTED") for ln in lines)
    assert runbook.main(["--data-dir", str(settings.data_dir)]) == 1


def test_optional_packages_are_feature_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runbook, "module_present", lambda name: name == "supervisor.monitors")
    lines = runbook.optional_lines()
    assert any("supervisor.monitors present" in ln for ln in lines)
    assert any("supervisor.onboard not installed" in ln for ln in lines)
    assert all(ln.startswith("[SKIP]") for ln in lines)


def test_cli_inject_needs_a_number(settings: Settings, capsys: pytest.CaptureFixture[str]) -> None:
    assert runbook.main(["inject", "--data-dir", str(settings.data_dir)]) == 2
    assert runbook.main(["inject", "9", "--data-dir", str(settings.data_dir)]) == 2
    out = capsys.readouterr().out
    assert "[FAIL]" in out and out.isascii()
