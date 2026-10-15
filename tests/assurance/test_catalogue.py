"""Catalogue-level checks: every real manifest validates, is documented, and every real
runner runs offline on the synthetic path against the real demo targets without an error."""

from __future__ import annotations

from pathlib import Path

import pytest

from supervisor.assurance.engine import run_packs
from supervisor.assurance.loader import load_packs
from supervisor.assurance.model import RunContext
from supervisor.assurance.registry import resolve_runner
from supervisor.assurance.targets import DemoAgentTarget, MockJudgeTarget
from supervisor.assurance.taxonomy import REGKB_DUTIES
from tests.conftest import REPO_ROOT

PACKS = load_packs()
PLAN_DIMENSIONS = {
    "accuracy",
    "hallucination",
    "bias_fairness",
    "dependency",
    "security",
    "robustness",
}


def test_catalogue_covers_every_dimension_and_resolves_runners() -> None:
    assert len(PACKS) >= 30
    assert {p.dimension for p in PACKS} == PLAN_DIMENSIONS
    for p in PACKS:
        assert set(p.maps_to.regkb_duties) <= REGKB_DUTIES
        assert hasattr(resolve_runner(p), "run")
    assert {"agent", "traces", "judge"} <= {t for p in PACKS for t in p.targets}
    assert any(p.judge_gate for p in PACKS)
    assert any(p.launch_gate == "required" for p in PACKS)


def test_every_pack_is_in_the_docs_catalogue() -> None:
    doc = (REPO_ROOT / "docs" / "assurance.md").read_text(encoding="utf-8")
    missing = [p.id for p in PACKS if f"`{p.id}`" not in doc]
    assert missing == []


def test_share_alike_data_is_never_in_the_repo() -> None:
    for p in PACKS:
        if p.licence.startswith("CC-BY-SA"):
            assert "vendored_sample" not in p.data_modes
            assert not (REPO_ROOT / "data" / "assurance" / "vendored" / p.id).exists()


@pytest.mark.parametrize("agent_id", ["payments", "credit_prequal", "customer_service"])
def test_all_agent_packs_run_offline_on_synthetic_data(agent_id: str, tmp_path: Path) -> None:
    target = DemoAgentTarget(agent_id, tmp_path)
    try:
        ctx = RunContext(
            target=target,
            repo_root=REPO_ROOT,
            data_root=None,
            data_mode="synthetic",
            max_items=25,
        )
        summary = run_packs([p for p in PACKS if "agent" in p.targets], target, ctx)
    finally:
        target.close()
    errors = [(r.pack_id, r.reasons) for r in summary.results if r.status == "error"]
    assert errors == []
    assert all(r.is_mock for r in summary.results if r.status != "skip")
    for r in summary.results:
        assert all(v is None or type(v) is int for v in r.metrics.values())


def test_all_judge_packs_run_offline_on_the_mock_judge(tmp_path: Path) -> None:
    target = MockJudgeTarget()
    ctx = RunContext(target=target, repo_root=REPO_ROOT, data_root=None, data_mode="synthetic")
    summary = run_packs([p for p in PACKS if "judge" in p.targets], target, ctx)
    assert [r.pack_id for r in summary.results if r.status == "error"] == []
    gated = {r.pack_id for r in summary.results if r.judge_gate}
    assert gated == {p.id for p in PACKS if p.judge_gate}


def test_pack_duties_resolve_in_the_regkb_vocabulary() -> None:
    import yaml

    from supervisor.assurance.taxonomy import CORE_DUTIES, DUTIES_FILE

    duties = set(yaml.safe_load(DUTIES_FILE.read_text(encoding="utf-8"))["duties"])
    assert CORE_DUTIES <= duties
    assert REGKB_DUTIES == frozenset(duties)
    unknown = sorted({d for p in PACKS for d in p.maps_to.regkb_duties} - duties)
    assert unknown == []
