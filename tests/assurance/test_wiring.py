"""WP17 wiring: Launch NO-GO items, launch artefacts, judge enablement gate, CLI context."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.assurance.cli import tool_baseline_of
from supervisor.assurance.gates import (
    JudgeNotValidatedError,
    assurance_launch_items,
    assurance_launch_notes,
    judge_enablement_problems,
)
from supervisor.assurance.loader import load_packs
from supervisor.config import load_settings
from supervisor.judge.router import JudgeModel, JudgeRouter
from supervisor.judge.service import JudgeService
from supervisor.onboard.instrument import render_policy, validate_policy
from supervisor.onboard.launch import launch
from supervisor.onboard.plan import plan
from supervisor.onboard.render import assurance_md
from tests.judge.conftest import MemoryTables
from tests.onboard.conftest import discoveries, profiles  # noqa: F401

PACKS = load_packs()
BY_ID = {p.id: p for p in PACKS}
T = datetime(2026, 10, 15, tzinfo=UTC)


def row(pack_id: str, status: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "pack_id": pack_id,
        "dimension": BY_ID[pack_id].dimension,
        "target_kind": "agent",
        "target_id": "payments",
        "status": status,
        "metrics": {},
        "metric_status": {},
        "reasons": [],
        "n_items": 20,
        "data_mode": "synthetic",
        "is_mock": True,
    }
    base.update(kw)
    return base


REQUIRED = "pii_canary"
ADVISORY = "groundedness_monitor"


def test_pack_gates_as_assumed() -> None:
    assert BY_ID[REQUIRED].launch_gate == "required"
    assert BY_ID[ADVISORY].launch_gate == "advisory"


def test_required_fail_is_no_go_with_exact_reason() -> None:
    r = row(
        REQUIRED,
        "fail",
        metrics={"leak_rate_bp": 900, "unmasked_pii_count": 0},
        metric_status={"leak_rate_bp": "fail", "unmasked_pii_count": "pass"},
    )
    items = assurance_launch_items([r], PACKS)
    assert items == ["assurance pack pii_canary failed: leak_rate_bp 900 vs no-go 500"]
    assert items == assurance_launch_items([r], PACKS)  # deterministic


def test_required_error_and_skip_are_no_go() -> None:
    items = assurance_launch_items(
        [
            row(REQUIRED, "error", reasons=["ValueError: boom"]),
            row("prefilter_evasion", "skip", reasons=["no data"]),
        ],
        PACKS,
    )
    assert "assurance pack pii_canary errored: ValueError: boom" in items
    assert "assurance pack prefilter_evasion skipped (required): no data" in items


def test_advisory_and_warn_never_no_go() -> None:
    results = [row(ADVISORY, "fail", reasons=["x"]), row(REQUIRED, "warn", reasons=["w"])]
    assert assurance_launch_items(results, PACKS) == []
    notes = assurance_launch_notes(results, PACKS)
    assert len(notes) == 2 and all(n.startswith("assurance pack ") for n in notes)
    assert assurance_launch_items([row(REQUIRED, "ok")], PACKS) == []


# --------------------------------------------------------------------------- launch


@pytest.fixture(scope="module")
def payments_policy(discoveries, profiles):  # noqa: ANN001, ANN201, F811
    inv = discoveries["payments"].inventory
    mp, _ = plan(inv, profiles["payments"])
    return validate_policy(render_policy(inv, profiles["payments"], mp))


def test_launch_flag_off_is_unchanged(payments_policy, tmp_path: Path) -> None:  # noqa: ANN001
    assert load_settings().assurance_launch_enabled is False
    r = launch(payments_policy, "payments", tmp_path)
    assert r.assurance_enabled is False and r.assurance == [] and r.assurance_reasons == []
    assert r.go


def test_launch_with_explicit_results(payments_policy, tmp_path: Path) -> None:  # noqa: ANN001
    bad = row(
        REQUIRED, "fail", metrics={"leak_rate_bp": 900}, metric_status={"leak_rate_bp": "fail"}
    )
    r = launch(payments_policy, "payments", tmp_path / "a", assurance=[bad])
    assert r.assurance_enabled and not r.go
    assert r.reasons == ["assurance pack pii_canary failed: leak_rate_bp 900 vs no-go 500"]
    assert r.assurance[0]["pack_id"] == "pii_canary" and r.assurance[0]["launch_gate"] == "required"
    md = assurance_md(r)
    assert "NO-GO" in md and "pii_canary" in md
    adv = launch(payments_policy, "payments", tmp_path / "b", assurance=[row(ADVISORY, "fail")])
    assert adv.go and adv.assurance_reasons == []
    skip = launch(
        payments_policy,
        "payments",
        tmp_path / "c",
        assurance=[row(REQUIRED, "skip", reasons=["no data"])],
    )
    assert not skip.go and skip.assurance_reasons == [
        "assurance pack pii_canary skipped (required): no data"
    ]


# --------------------------------------------------------------------------- judge gate


class FakeChat:
    is_mock = False
    family = "vendorx"

    def __init__(self, model_id: str, family: str) -> None:
        self.model_id = model_id
        self.family = family

    def complete_json(self, messages: Any, json_schema: Any, timeout_s: Any = None) -> Any:
        raise NotImplementedError


def _router(*, mock: bool = False) -> JudgeRouter:
    if mock:
        return JudgeRouter.from_settings(load_settings())
    t1 = JudgeModel(1, "primary", FakeChat("judge-small-2026-01-01", "fam-a"), "local")
    t2 = JudgeModel(2, "primary", FakeChat("judge-large-2026-01-01", "fam-b"), "local")
    return JudgeRouter(t1, t2, agent_families={})


def _gate_rows(status: str = "ok", version: int | None = None, is_mock: bool = False) -> list[dict]:
    out = []
    for p in PACKS:
        if p.judge_gate:
            out.append(
                {
                    "run_id": "r1",
                    "ts": T,
                    "pack_id": p.id,
                    "pack_version": version or p.version,
                    "target_kind": "judge",
                    "target_id": "judge:judge-small-2026-01-01",
                    "status": status,
                    "is_mock": is_mock,
                }
            )
    return out


def _from_settings(monkeypatch: pytest.MonkeyPatch, tables: Any, router: JudgeRouter, **kw: Any):
    monkeypatch.setattr(JudgeRouter, "from_settings", classmethod(lambda cls, *a, **k: router))
    settings = load_settings(judge_enabled=True, **kw)
    return JudgeService.from_settings(
        settings, FixedClock(T), tables=tables if tables is not None else MemoryTables()
    )


def test_real_judge_without_results_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(JudgeNotValidatedError) as exc:
        _from_settings(monkeypatch, MemoryTables(), _router())
    assert "judge_golden_set" in str(exc.value) and "judge:judge-small-2026-01-01" in str(exc.value)


def test_real_judge_with_passing_rows_is_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    tables = MemoryTables()
    tables.append("eval_result", _gate_rows("ok"))
    assert _from_settings(monkeypatch, tables, _router()) is not None
    tables2 = MemoryTables()
    tables2.append("eval_result", _gate_rows("warn"))
    assert _from_settings(monkeypatch, tables2, _router()) is not None


def test_real_judge_failing_stale_or_mock_rows_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    for kw in ({"status": "fail"}, {"version": 99}, {"is_mock": True}):
        tables = MemoryTables()
        tables.append("eval_result", _gate_rows(**kw))
        with pytest.raises(JudgeNotValidatedError):
            _from_settings(monkeypatch, tables, _router())


def test_gate_flag_off_and_mock_exempt(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_router = _router(mock=True)
    assert judge_enablement_problems(MemoryTables(), mock_router) == []
    assert (
        _from_settings(monkeypatch, MemoryTables(), _router(), assurance_judge_gate_enabled=False)
        is not None
    )


# --------------------------------------------------------------------------- cli context


def test_tool_baseline_of_reads_latest_version() -> None:
    tables = MemoryTables()
    assert tool_baseline_of(tables, "payments") is None
    tables.append(
        "agent_version",
        [{"agent_id": "payments", "version": "1", "tool_manifest_hash": "ab" * 32}],
    )
    assert tool_baseline_of(tables, "payments") == "ab" * 32
    assert tool_baseline_of(None, "payments") is None


def test_launch_runs_agent_packs_with_its_own_policy(
    payments_policy,  # noqa: ANN001
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag on: the agent packs run in the launch sandbox with the SAME policy, so the
    red-team pack agrees with launch on false alarms."""
    monkeypatch.setenv("ASSURANCE_LAUNCH_ENABLED", "1")
    r = launch(payments_policy, "payments", tmp_path)
    assert r.assurance_enabled and r.assurance
    assert {x["pack_id"] for x in r.assurance} >= {"owasp_agentic_redteam"}
    assert all(x["target_id"] == "payments" and x["is_mock"] for x in r.assurance)
    rt = next(x for x in r.assurance if x["pack_id"] == "owasp_agentic_redteam")
    if rt["status"] != "skip":
        assert rt["metrics"]["false_alarm_bp"] == (r.false_alarm_bp or 0)
        assert rt["metrics"]["catch_rate_bp"] >= r.min_catch_rate_bp
    assert r.assurance_reasons == [x for x in r.reasons if x.startswith("assurance pack ")]
