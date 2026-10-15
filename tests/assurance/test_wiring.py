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
from supervisor.assurance.loader import load_packs, manifest_sha256, pack_path
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


def full_ok(*replace: dict[str, Any]) -> list[dict[str, Any]]:
    """ok rows for every required agent pack, with the packs of ``replace`` swapped in."""
    given = {r["pack_id"] for r in replace}
    rows = [
        row(p.id, "ok")
        for p in PACKS
        if p.launch_gate == "required" and "agent" in p.targets and p.id not in given
    ]
    return rows + list(replace)


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


def test_only_structured_not_applicable_skip_is_a_note() -> None:
    na = row(
        "four_fifths_rule",
        "skip",
        reasons=["not applicable: target lacks decide"],
        details={"not_applicable": True},
    )
    assert assurance_launch_items([na], PACKS) == []
    notes = assurance_launch_notes([na], PACKS)
    assert len(notes) == 1 and "not applicable" in notes[0]
    # stored rows keep details as a JSON string
    stored = dict(na, details='{"not_applicable": true}')
    assert assurance_launch_items([stored], PACKS) == []
    # the free text alone no longer exempts anything
    text_only = row("pii_canary", "skip", reasons=["target lacks capability 'chat'"])
    assert assurance_launch_items([text_only], PACKS) == [
        "assurance pack pii_canary skipped (required): target lacks capability 'chat'"
    ]
    no_data = row("four_fifths_rule", "skip", reasons=["only 0 decisions, pack needs 100"])
    assert assurance_launch_items([no_data], PACKS) == [
        "assurance pack four_fifths_rule skipped (required): only 0 decisions, pack needs 100"
    ]


def test_manifests_use_requires_capabilities_only_for_decisions() -> None:
    with_caps = {p.id: p.requires_capabilities for p in PACKS if p.requires_capabilities}
    assert with_caps == {"fairness_metrics": ["decide"], "four_fifths_rule": ["decide"]}


def test_missing_required_pack_result_is_no_go() -> None:
    required = sorted(p.id for p in PACKS if p.launch_gate == "required" and "agent" in p.targets)
    assert len(required) > 3
    partial = [row(pid, "ok") for pid in required[:2]]
    # without expect_target_kind nothing is said about missing packs
    assert assurance_launch_items(partial, PACKS) == []
    items = assurance_launch_items(partial, PACKS, expect_target_kind="agent")
    assert items == [f"assurance pack {pid} has no result (required)" for pid in required[2:]]
    assert assurance_launch_items(full_ok(), PACKS, expect_target_kind="agent") == []


def test_launch_with_partial_results_lists_missing_packs(
    payments_policy,  # noqa: ANN001
    tmp_path: Path,
) -> None:
    r = launch(payments_policy, "payments", tmp_path, assurance=[row(REQUIRED, "ok")])
    assert not r.go
    assert "assurance pack truthfulqa_vi has no result (required)" in r.assurance_reasons
    assert not any("pii_canary" in x for x in r.assurance_reasons)


def test_advisory_and_warn_never_no_go() -> None:
    results = [row(ADVISORY, "fail", reasons=["x"]), row(REQUIRED, "warn", reasons=["w"])]
    assert assurance_launch_items(results, PACKS) == []
    notes = assurance_launch_notes(results, PACKS)
    assert len(notes) == 2 and all(n.startswith("assurance pack ") for n in notes)
    assert assurance_launch_items([row(REQUIRED, "ok")], PACKS) == []


# --------------------------------------------------------------------------- launch


@pytest.fixture(autouse=True)
def _accept_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests judge hand-made rows with is_mock=True (or run the mock demo agent) and
    need a GO to be possible; the mock-only NO-GO item has its own tests below, which unset
    this flag."""
    monkeypatch.setenv("ASSURANCE_ACCEPT_MOCK_FOR_LAUNCH", "1")


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
    r = launch(payments_policy, "payments", tmp_path / "a", assurance=full_ok(bad))
    assert r.assurance_enabled and not r.go
    assert r.reasons == ["assurance pack pii_canary failed: leak_rate_bp 900 vs no-go 500"]
    pii = next(x for x in r.assurance if x["pack_id"] == "pii_canary")
    assert pii["launch_gate"] == "required"
    md = assurance_md(r)
    assert "NO-GO" in md and "pii_canary" in md
    adv = launch(
        payments_policy, "payments", tmp_path / "b", assurance=full_ok(row(ADVISORY, "fail"))
    )
    assert adv.go and adv.assurance_reasons == []
    skip = launch(
        payments_policy,
        "payments",
        tmp_path / "c",
        assurance=full_ok(row(REQUIRED, "skip", reasons=["no data"])),
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


def _gate_rows(
    status: str = "ok",
    version: int | None = None,
    is_mock: bool = False,
    manifest_sha: str | None = None,
) -> list[dict]:
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
                    "manifest_sha256": manifest_sha or manifest_sha256(pack_path(p.id)),
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


def test_stale_manifest_hash_refuses_an_old_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    tables = MemoryTables()
    tables.append("eval_result", _gate_rows("ok", manifest_sha="0" * 64))
    problems = judge_enablement_problems(tables, _router())
    assert problems and all("manifest changed" in p for p in problems)
    with pytest.raises(JudgeNotValidatedError):
        _from_settings(monkeypatch, tables, _router())


class MockChat(FakeChat):
    is_mock = True


def test_mixed_real_t1_mock_t2_is_gated() -> None:
    t1 = JudgeModel(1, "primary", FakeChat("judge-small-2026-01-01", "fam-a"), "local")
    t2 = JudgeModel(2, "primary", MockChat("mock-t2", "fam-b"), "local")
    mixed = JudgeRouter(t1, t2, agent_families={})
    assert judge_enablement_problems(MemoryTables(), mixed)  # no results -> refused
    tables = MemoryTables()
    tables.append("eval_result", _gate_rows("ok"))
    assert judge_enablement_problems(tables, mixed) == []


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


# ------------------------------------------------------------ mock labelling (W3-assure M1)


def _launch_rows(
    policy: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, accept: str, mock_flags: dict
) -> Any:
    """Launch on full_ok rows; ``mock_flags`` maps pack id -> is_mock (default: all mock)."""
    monkeypatch.setenv("ASSURANCE_ACCEPT_MOCK_FOR_LAUNCH", accept)
    rows = [{**r, "is_mock": mock_flags.get(r["pack_id"], True)} for r in full_ok()]
    return launch(policy, "payments", tmp_path, assurance=rows)


def test_mock_only_flag_off_is_no_go(payments_policy, tmp_path, monkeypatch) -> None:  # noqa: ANN001
    r = _launch_rows(payments_policy, tmp_path, monkeypatch, "0", {})
    assert not r.go and r.assurance_mock == "all"
    assert r.assurance_reasons == ["assurance results are mock only"]
    assert "assurance results are mock only" in r.reasons
    assert "NO-GO (MOCK: mock results only)" in assurance_md(r)


def test_mock_only_flag_on_is_go_with_mock_label(
    payments_policy,  # noqa: ANN001
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = _launch_rows(payments_policy, tmp_path, monkeypatch, "1", {})
    assert r.go and r.assurance_reasons == []
    assert any(x.startswith("assurance (MOCK): ") for x in r.reasons)
    assert "GO (MOCK: mock results only)" in assurance_md(r)


def test_mixed_run_has_label_but_no_mock_only_item(
    payments_policy,  # noqa: ANN001
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flags = {x["pack_id"]: False for x in full_ok()[1:]}  # one mock row, the rest real
    r = _launch_rows(payments_policy, tmp_path, monkeypatch, "0", flags)
    assert r.go and r.assurance_mock == "mixed" and r.assurance_reasons == []
    assert any(x.startswith("assurance (MOCK): ") for x in r.reasons)
    assert "(MOCK: some results are mock)" in assurance_md(r)


def test_all_real_has_no_label(payments_policy, tmp_path, monkeypatch) -> None:  # noqa: ANN001
    flags = {x["pack_id"]: False for x in full_ok()}
    r = _launch_rows(payments_policy, tmp_path, monkeypatch, "0", flags)
    assert r.go and r.assurance_mock == "none"
    assert any(x.startswith("assurance: ") for x in r.reasons)
    assert not any("MOCK" in x for x in r.reasons) and "MOCK" not in assurance_md(r)


def test_mock_state_ignores_skips_and_errors() -> None:
    from supervisor.assurance.gates import assurance_mock_items, assurance_mock_state

    assert assurance_mock_state([]) == "none"
    skipped = [row(REQUIRED, "skip", is_mock=True)]
    assert assurance_mock_state(skipped) == "mixed"  # mock but nothing evaluated
    assert assurance_mock_items(skipped, accept_mock=False) == []
    real_ok = row(ADVISORY, "ok", is_mock=False)
    assert assurance_mock_state([row(REQUIRED, "error", is_mock=True), real_ok]) == "mixed"
    assert assurance_mock_state([row(REQUIRED, "ok"), row(ADVISORY, "warn")]) == "all"
