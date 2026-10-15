"""WP17 fix round: unmeasured vs not-applicable metrics through the real runners and engine."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.adapters.clock import FixedClock
from supervisor.assurance.engine import run_pack
from supervisor.assurance.gates import assurance_launch_items
from supervisor.assurance.loader import PackError, load_packs
from supervisor.assurance.model import PackResult, TargetReply
from supervisor.assurance.registry import resolve_runner
from tests.assurance.fakes import FakeAgent, FakeJudge, ctx
from tests.assurance.test_framework import manifest, write_pack
from tests.assurance.test_robustness import good_judge_score, pv_known

PACKS = load_packs()
BY_ID = {p.id: p for p in PACKS}
CLOCK = FixedClock(datetime(2026, 10, 15, tzinfo=UTC))
FIX = Path(__file__).parent / "fixtures" / "mcp_tool_manifest_drift"


def engine_run(pack_id: str, target: Any, **kw: Any) -> PackResult:
    pack = BY_ID[pack_id]
    runner = resolve_runner(pack, None)
    return run_pack(pack, runner, ctx(target, **kw), "run-t", CLOCK)


def test_unmeasured_drift_is_skip_and_required_means_no_go() -> None:
    m = json.loads((FIX / "manifest_good.json").read_text(encoding="utf-8"))
    m.pop("registered")  # no declared hash, no registered list, no baseline
    r = engine_run("mcp_tool_manifest_drift", FakeAgent(tools=m))
    assert r.metrics["drift_count"] is None and r.metrics["poisoned_descriptions"] == 0
    assert r.status == "skip" and "metric drift_count not measured" in r.reasons
    items = assurance_launch_items([r], PACKS)
    assert items and items[0].startswith(
        "assurance pack mcp_tool_manifest_drift skipped (required)"
    )


def test_counterfactual_with_decide_raising_everywhere_is_skip() -> None:
    def boom(_: Mapping[str, Any]) -> Mapping[str, Any]:
        raise RuntimeError("decide is down")

    r = engine_run("counterfactual_vi", FakeAgent(decide_fn=boom))
    assert r.metrics["decision_flip_rate_bp"] is None
    assert r.metrics["reply_divergence_bp"] is not None  # text part passed on its own
    assert r.status == "skip"
    assert "metric decision_flip_rate_bp not measured" in r.reasons
    assert assurance_launch_items([r], PACKS)  # required pack -> NO-GO line


def test_counterfactual_without_decide_capability_declares_decision_metrics_na() -> None:
    chat_only = FakeAgent(capabilities=frozenset({"chat"}))
    r = engine_run("counterfactual_vi", chat_only)
    assert r.status == "ok", r.reasons
    assert r.metrics["decision_flip_rate_bp"] is None
    assert r.metric_status["decision_flip_rate_bp"] == "na"
    decide_only = FakeAgent(
        capabilities=frozenset({"decide"}),
        decide_fn=lambda a: {"approved": True, "limit_minor": 1, "reason": "x"},
    )
    r2 = engine_run("counterfactual_vi", decide_only)
    assert r2.status == "ok", r2.reasons
    assert r2.metrics["reply_divergence_bp"] is None


def test_fairness_decision_packs_not_applicable_without_decide() -> None:
    chat_only = FakeAgent(capabilities=frozenset({"chat"}))
    for pid in ("fairness_metrics", "four_fifths_rule"):
        r = engine_run(pid, chat_only)
        assert r.status == "skip" and r.details["not_applicable"] is True
        assert r.reasons == ["not applicable: target lacks decide"]
        assert assurance_launch_items([r], PACKS) == []


def test_behavioural_required_packs_never_get_the_exemption() -> None:
    repo_like = FakeAgent(capabilities=frozenset({"deps", "models"}))
    results = []
    for pid in ("pii_canary", "truthfulqa_vi", "finance_harm_refusal", "owasp_agentic_redteam"):
        r = engine_run(pid, repo_like)
        assert r.status == "skip" and not r.details.get("not_applicable"), pid
        results.append(r)
    items = assurance_launch_items(results, PACKS)
    assert len(items) == 4 and all("skipped (required)" in i for i in items)


def test_perturbation_declares_other_kind_metrics_na() -> None:
    agent = FakeAgent(respond_fn=_constant("Câu trả lời cố định."))
    a = engine_run("perturbation_vi", agent)
    assert a.metrics["verdict_flip_rate_bp"] is None and a.metrics["answered_bp"] is not None
    assert a.status != "skip", a.reasons
    j = engine_run("perturbation_vi", FakeJudge(score_fn=good_judge_score))
    assert j.status == "ok", j.reasons
    assert j.metrics["answered_bp"] is None and j.metric_status["answered_bp"] == "na"


def test_paraphrase_declares_other_kind_metrics_na() -> None:
    j = engine_run("paraphrase_consistency", FakeJudge(score_fn=good_judge_score))
    assert j.status in ("ok", "warn", "fail"), j.reasons
    assert j.metrics["pairwise_consistency_bp"] is None


def _constant(text: str):  # noqa: ANN202
    def fn(prompt: str, context: Sequence[str], sample: int) -> TargetReply:
        return TargetReply(text=text, is_mock=True)

    return fn


def test_constant_abstaining_agent_cannot_pass_perturbation() -> None:
    abstainer = FakeAgent(respond_fn=_constant("Tôi không có đủ thông tin để trả lời."))
    r = engine_run("perturbation_vi", abstainer)
    assert r.metrics["answer_consistency_bp"] == 10000
    assert r.metrics["answered_bp"] == 0
    assert r.status == "fail" and r.metric_status["answered_bp"] == "fail"
    assert assurance_launch_items([r], PACKS) == [
        "assurance pack perturbation_vi failed: answered_bp 0 vs no-go 4000"
    ]
    assert pv_known()  # data is present


def test_loader_refuses_a_pack_without_thresholds(tmp_path: Path) -> None:
    write_pack(tmp_path, manifest("no_thr", thresholds=[]))
    with pytest.raises(PackError, match="at least one threshold"):
        load_packs(tmp_path)
    assert yaml.safe_load((tmp_path / "no_thr.yaml").read_text())["thresholds"] == []


def test_all_real_manifests_have_thresholds_and_known_capabilities() -> None:
    assert all(p.thresholds for p in PACKS)
