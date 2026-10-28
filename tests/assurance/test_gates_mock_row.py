"""WP-O3b: ``assurance.gates._row`` keeps ``is_mock`` of a ``PackResult`` object.

Before the fix the row of a ``PackResult`` had no ``is_mock`` key, so ``assurance_mock_state``
said "none" and the Launch "mock only" NO-GO never fired for real engine output.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from supervisor.assurance.gates import (
    MOCK_ONLY_ITEM,
    _row,
    assurance_mock_items,
    assurance_mock_state,
)
from supervisor.assurance.loader import load_packs
from supervisor.assurance.model import PackResult
from supervisor.onboard.instrument import render_policy, validate_policy
from supervisor.onboard.launch import launch
from supervisor.onboard.plan import plan
from tests.onboard.conftest import discoveries, profiles  # noqa: F401

PACKS = load_packs()
T = datetime(2026, 10, 15, tzinfo=UTC)


def pack_result(pack_id: str, *, is_mock: bool, status: str = "ok", **details: Any) -> PackResult:
    p = next(x for x in PACKS if x.id == pack_id)
    return PackResult(
        run_id="run-test",
        pack_id=p.id,
        pack_version=p.version,
        dimension=p.dimension,
        target_kind="agent",
        target_id="payments",
        status=status,  # type: ignore[arg-type]
        metrics={},
        metric_status={},
        reasons=[],
        n_items=20,
        data_mode="synthetic",
        dataset_id="x",
        dataset_sha256="",
        is_mock=is_mock,
        launch_gate=p.launch_gate,
        judge_gate=p.judge_gate,
        started_at=T,
        finished_at=T,
        details=dict(details),
    )


def required_results(is_mock: bool) -> list[PackResult]:
    return [
        pack_result(p.id, is_mock=is_mock)
        for p in PACKS
        if p.launch_gate == "required" and "agent" in p.targets
    ]


def test_row_of_a_pack_result_keeps_is_mock_and_the_reason() -> None:
    mock = _row(pack_result("pii_canary", is_mock=True))
    assert mock["is_mock"] is True and mock["mock_reason"]
    why = _row(pack_result("pii_canary", is_mock=True, mock_reason="demo sandbox"))
    assert why["mock_reason"] == "demo sandbox"
    real = _row(pack_result("pii_canary", is_mock=False))
    assert real["is_mock"] is False and real["mock_reason"] == ""


def test_mock_state_and_items_see_pack_result_objects() -> None:
    results = required_results(True)
    assert assurance_mock_state(results) == "all"
    assert assurance_mock_items(results, accept_mock=False) == [MOCK_ONLY_ITEM]
    assert assurance_mock_items(results, accept_mock=True) == []
    real = required_results(False)
    assert assurance_mock_state(real) == "none"
    mixed = [*real[:-1], pack_result(real[-1].pack_id, is_mock=True)]
    assert assurance_mock_state(mixed) == "mixed"
    assert assurance_mock_items(mixed, accept_mock=False) == []


@pytest.fixture
def payments_policy(discoveries, profiles):  # noqa: ANN001, ANN201, F811
    inv = discoveries["payments"].inventory
    mp, _ = plan(inv, profiles["payments"])
    return validate_policy(render_policy(inv, profiles["payments"], mp))


def test_launch_mock_only_path_triggers_for_pack_result_objects(
    payments_policy,  # noqa: ANN001
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSURANCE_ACCEPT_MOCK_FOR_LAUNCH", "0")
    r = launch(payments_policy, "payments", tmp_path / "a", assurance=required_results(True))
    assert not r.go and r.assurance_mock == "all"
    assert r.assurance_reasons == [MOCK_ONLY_ITEM]
    monkeypatch.setenv("ASSURANCE_ACCEPT_MOCK_FOR_LAUNCH", "1")
    ok = launch(payments_policy, "payments", tmp_path / "b", assurance=required_results(True))
    assert ok.go and ok.assurance_mock == "all" and ok.assurance_reasons == []
    monkeypatch.setenv("ASSURANCE_ACCEPT_MOCK_FOR_LAUNCH", "0")
    real = launch(payments_policy, "payments", tmp_path / "c", assurance=required_results(False))
    assert real.go and real.assurance_mock == "none"
