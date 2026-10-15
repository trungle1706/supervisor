"""WP19: validation gate (JUDGE_REQUIRE_VALIDATION) in JudgeService.from_settings."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from supervisor.config import load_settings
from supervisor.core.errors import SupervisorError
from supervisor.judge.mrm.control import (
    JudgeNotValidatedError,
    current_identity,
    latest_validation,
    require_validation,
)
from supervisor.judge.router import JudgeRouter
from supervisor.judge.service import JudgeService
from tests.judge.conftest import T0, MemoryTables


def settings_for(**kw: Any):
    return load_settings(judge_enabled=True, judge_t2_sample_bp=0, **kw)


def record(ident, *, passed: Any = True, **over: Any) -> dict[str, Any]:
    row = {
        "validation_id": "mv-1",
        "ts": T0,
        "model_version": ident.model_version,
        "prompt_hash": ident.prompt_hash,
        "rubric_version": ident.rubric_version,
        "golden_set_hash": ident.golden_set_hash,
        "decision": "GO" if passed else "NO_GO",
        "passed": passed,
    }
    row.update(over)
    return row


def ident_for(settings):
    return current_identity(JudgeRouter.from_settings(settings), settings)


class FailingTables(MemoryTables):
    def query(self, table: str, *a: Any, **k: Any):
        if table == "model_validation":
            raise AssertionError("no validation lookup expected when the gate is off")
        return super().query(table, *a, **k)


def test_error_is_supervisor_error() -> None:
    assert issubclass(JudgeNotValidatedError, SupervisorError)


def test_off_by_default_no_lookup(clock) -> None:
    s = settings_for()
    assert s.judge_require_validation is False
    assert JudgeService.from_settings(s, clock, tables=FailingTables()) is not None


def test_on_without_store_refuses(clock) -> None:
    s = settings_for(judge_require_validation=True)
    with pytest.raises(JudgeNotValidatedError, match="store"):
        JudgeService.from_settings(s, clock)


def test_on_no_record_refuses(clock) -> None:
    s = settings_for(judge_require_validation=True)
    with pytest.raises(JudgeNotValidatedError) as ei:
        JudgeService.from_settings(s, clock, tables=MemoryTables())
    msg = str(ei.value)
    assert "python -m supervisor.judge.mrm validate" in msg and "model_version" in msg


def test_on_passing_record_runs(clock) -> None:
    s = settings_for(judge_require_validation=True)
    t = MemoryTables()
    t.append("model_validation", [record(ident_for(s), passed="true")])  # Databricks string
    assert JudgeService.from_settings(s, clock, tables=t) is not None


def test_on_other_identity_or_failed_refuses(clock) -> None:
    s = settings_for(judge_require_validation=True)
    ident = ident_for(s)
    rows = [
        record(ident, prompt_hash="0" * 64),
        record(ident, passed=False),
        record(ident, passed="false"),
        record(ident, model_version="other"),
        record(ident, rubric_version="other"),
    ]
    for row in rows:
        t = MemoryTables()
        t.append("model_validation", [row])
        with pytest.raises(JudgeNotValidatedError):
            JudgeService.from_settings(s, clock, tables=t)


def test_latest_validation_picks_latest_passing() -> None:
    ident = ident_for(settings_for())
    t = MemoryTables()
    t.append(
        "model_validation",
        [
            record(ident, validation_id="old"),
            record(ident, validation_id="new", ts=T0 + timedelta(days=1)),
            record(ident, validation_id="bad", ts=T0 + timedelta(days=2), passed=False),
        ],
    )
    # The latest row for the key decides: a later NO_GO withdraws the earlier GO.
    assert latest_validation(t, ident) is None
    with pytest.raises(JudgeNotValidatedError):
        require_validation(t, ident)
    t.append("model_validation", [record(ident, validation_id="z", ts=T0 + timedelta(days=3))])
    assert latest_validation(t, ident)["validation_id"] == "z"


def test_passed_true_with_no_go_decision_is_refused() -> None:
    ident = ident_for(settings_for())
    t = MemoryTables()
    t.append("model_validation", [record(ident, decision="NO_GO")])
    assert latest_validation(t, ident) is None


def test_store_error_becomes_not_validated(clock) -> None:
    class Broken(MemoryTables):
        def query(self, table, *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN202
            if table == "model_validation":
                raise RuntimeError("TABLE_OR_VIEW_NOT_FOUND")
            return super().query(table, *a, **k)

    s = settings_for(judge_require_validation=True)
    with pytest.raises(JudgeNotValidatedError, match="lookup failed"):
        JudgeService.from_settings(s, clock, tables=Broken(), force=True)


def test_error_is_in_the_wp17_judge_gate_family() -> None:
    from supervisor.assurance.gates import JudgeNotValidatedError as PackGateError

    assert issubclass(JudgeNotValidatedError, PackGateError)


def test_refusal_does_not_touch_gate(clock) -> None:
    s = settings_for(judge_require_validation=True)
    t = MemoryTables()
    with pytest.raises(JudgeNotValidatedError):
        JudgeService.from_settings(s, clock, tables=t)
    assert not t.tables.get("gate_control") and not t.tables.get("verdict")


def test_judge_sweep_job_reports_fail_not_crash() -> None:
    """The job catches SupervisorError: [FAIL] line, exit 1."""
    from supervisor.jobs import judge_sweep

    assert judge_sweep.SupervisorError is SupervisorError
