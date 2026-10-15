"""WP17 accuracy + hallucination packs: manifests, importers, runners with good/bad fakes."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
import yaml

from supervisor.assurance.model import EvalPack, RunnerOutput, TargetReply
from supervisor.assurance.runners.accuracy import (
    HaluEvalRunner,
    RagasTriadRunner,
    SelfCheckRunner,
    SimpleQARunner,
    TruthfulQARunner,
    grade_simpleqa,
    qa_trace,
)
from supervisor.assurance.runners.accuracy_common import (
    classify_reply,
    load_halueval,
    load_simpleqa,
    load_truthfulqa,
)
from supervisor.assurance.runners.accuracy_judge import (
    JudgeGoldenSetRunner,
    golden_rows_to_items,
)
from supervisor.assurance.textutil import numbers, overlap_bp
from supervisor.config import load_settings
from supervisor.judge.mockjudge import MockJudgeChat, _reply
from supervisor.judge.router import JudgeRouter
from tests.assurance.fakes import FakeAgent, FakeJudge, FakeTraces, ctx
from tests.conftest import REPO_ROOT

PACKS = REPO_ROOT / "src" / "supervisor" / "assurance" / "packs"
SYN = REPO_ROOT / "data" / "assurance" / "synthetic"
FIX = REPO_ROOT / "tests" / "assurance" / "fixtures"
IDS = (
    "truthfulqa_vi",
    "simpleqa_vi",
    "halueval_vi",
    "ragas_rag_triad",
    "selfcheck_consistency",
    "judge_golden_set",
)
ABSTAIN = "Tôi không có đủ thông tin để trả lời."


def pack(pack_id: str, **over: Any) -> EvalPack:
    p = EvalPack.model_validate(yaml.safe_load((PACKS / f"{pack_id}.yaml").read_text("utf-8")))
    return p.model_copy(update=over) if over else p


def rows(name: str) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (SYN / name).read_text("utf-8").splitlines() if x.strip()]


def no_floats(value: Any) -> None:
    assert not isinstance(value, float)
    if isinstance(value, Mapping):
        for v in value.values():
            no_floats(v)
    elif isinstance(value, list | tuple):
        for v in value:
            no_floats(v)


def verdict(p: EvalPack, out: RunnerOutput, metric: str) -> str:
    """'go' (meets go), 'fail' (misses no_go) or 'warn', as the engine would say."""
    assert out.status == "ok", out.skip_reason
    no_floats(out.metrics)
    no_floats(out.details)
    v = out.metrics[metric]
    th = p.threshold(metric)
    assert th is not None and v is not None
    if p.metric(metric).direction == "higher_better":
        return "go" if v >= th.go else ("fail" if v < th.no_go else "warn")
    return "go" if v <= th.go else ("fail" if v > th.no_go else "warn")


def agent(fn) -> FakeAgent:
    return FakeAgent(respond_fn=fn)


def reply(text: str) -> TargetReply:
    return TargetReply(text=text, is_mock=True)


# --------------------------------------------------------------------------- manifests


@pytest.mark.parametrize("pack_id", IDS)
def test_manifest_validates(pack_id: str) -> None:
    p = pack(pack_id)
    assert p.id == pack_id
    assert p.source.licence_verified_on == "2026-10-15" or p.licence == "own"
    assert "synthetic" in p.data_modes and "bank_supplied_path" in p.data_modes
    assert p.thresholds, "illustrative thresholds expected"


def test_gates_and_dimensions() -> None:
    assert pack("truthfulqa_vi").launch_gate == "required"
    assert pack("ragas_rag_triad").launch_gate == "required"
    assert pack("halueval_vi").judge_gate and pack("judge_golden_set").judge_gate
    assert pack("halueval_vi").dimension == "hallucination"
    assert pack("judge_golden_set").dimension == "accuracy"
    assert set(pack("ragas_rag_triad").targets) == {"agent", "traces"}


# --------------------------------------------------------------------------- data files


def test_kb_and_sets_shape() -> None:
    kb = rows("kb_vi.jsonl")
    assert len(kb) == 40 and {"id", "topic", "question", "answer"} <= set(kb[0])
    assert len({r["id"] for r in kb}) == 40
    assert len(rows("truthfulqa_vi.jsonl")) == 40
    assert len(rows("halueval_vi.jsonl")) == 40
    for r in rows("truthfulqa_vi.jsonl"):
        assert r["correct_answers"] and r["incorrect_answers"] and r["category"]
    for r in rows("halueval_vi.jsonl"):
        assert r["right_answer"] != r["hallucinated_answer"]


def test_classify_reply() -> None:
    assert classify_reply("Tôi không có đủ thông tin để trả lời.") == "abstain"
    assert classify_reply("I have no comment.") == "abstain"
    assert classify_reply("Xin lỗi, tôi không thể hỗ trợ yêu cầu này.") == "refusal"
    assert classify_reply(TargetReply(text="ok", refused=True)) == "refusal"
    assert classify_reply("") == "abstain"
    assert classify_reply("Phí là 100.000 đồng mỗi năm.") == "answer"


def test_grade_simpleqa() -> None:
    assert grade_simpleqa("Phí thường niên là 100.000 đồng mỗi năm.", "100.000 đồng")
    assert grade_simpleqa("Là 100000 đồng.", "100.000 đồng")
    assert not grade_simpleqa("Phí thường niên là 200.000 đồng mỗi năm.", "100.000 đồng")
    assert grade_simpleqa("Ngân hàng nghỉ ngày Chủ Nhật", "Chủ nhật")


# --------------------------------------------------------------------------- TruthfulQA


def test_truthfulqa_good_and_bad() -> None:
    p = pack("truthfulqa_vi")
    items = {r["question"]: r for r in rows("truthfulqa_vi.jsonl")}
    good = agent(lambda q, c, s: reply(items[q]["best_answer"]))
    out = TruthfulQARunner().run(p, ctx(good))
    assert verdict(p, out, "truthful_bp") == "go"
    assert verdict(p, out, "truthful_informative_bp") == "go"
    assert out.n_items == 40 and out.data_mode == "synthetic" and out.is_mock
    assert len(out.dataset_sha256) == 64

    bad = agent(lambda q, c, s: reply(items[q]["incorrect_answers"][0]))
    out = TruthfulQARunner().run(p, ctx(bad))
    assert verdict(p, out, "truthful_bp") == "fail"

    # Always refusing is truthful but not informative: the second metric catches it.
    mute = agent(lambda q, c, s: reply("Xin lỗi, tôi không thể hỗ trợ yêu cầu này."))
    out = TruthfulQARunner().run(p, ctx(mute))
    assert out.metrics["truthful_bp"] == 10000 and out.metrics["informative_bp"] == 0
    assert verdict(p, out, "truthful_informative_bp") == "fail"


def test_truthfulqa_skips() -> None:
    p = pack("truthfulqa_vi")
    a = agent(lambda q, c, s: reply("x"))
    out = TruthfulQARunner().run(p, ctx(a, data_mode="bank"))
    assert out.status == "skip" and "no bank data" in out.skip_reason
    assert TruthfulQARunner().run(p, ctx(a, data_mode="vendored")).status == "skip"
    assert TruthfulQARunner().run(p, ctx(FakeJudge(score_fn=lambda e: {}))).status == "skip"
    nochat = FakeAgent(capabilities=frozenset({"tools"}))
    assert TruthfulQARunner().run(p, ctx(nochat)).status == "skip"
    few = TruthfulQARunner().run(pack("truthfulqa_vi", min_items=41), ctx(a))
    assert few.status == "skip" and "needs 41" in few.skip_reason


def test_truthfulqa_importer_and_bank_run() -> None:
    items = load_truthfulqa(FIX / "truthfulqa_vi")
    assert len(items) == 3
    assert items[0]["correct_answers"][0] == "Nothing in particular happens"
    assert items[0]["incorrect_answers"] == [
        "It stays in the stomach for seven years",
        "It turns into stone",
    ]
    assert items[1]["category"] == "Law"
    p = pack("truthfulqa_vi", min_items=1)
    a = agent(lambda q, c, s: reply("I have no comment"))
    out = TruthfulQARunner().run(p, ctx(a, data_root=FIX))
    assert out.status == "ok" and out.data_mode == "bank_supplied_path" and out.n_items == 3
    assert out.metrics["truthful_bp"] == 10000 and out.metrics["informative_bp"] == 0
    capped = TruthfulQARunner().run(p, ctx(a, data_root=FIX, max_items=2))
    assert capped.n_items == 2


# --------------------------------------------------------------------------- SimpleQA


def test_simpleqa_good_bad_abstain() -> None:
    p = pack("simpleqa_vi")
    kb = {r["id"]: r["answer"] for r in rows("kb_vi.jsonl")}
    by_q = {r["problem"]: r for r in rows("simpleqa_vi.jsonl")}
    good = agent(lambda q, c, s: reply(kb[by_q[q]["kb_id"]]))
    out = SimpleQARunner().run(p, ctx(good))
    assert out.metrics["correct_bp"] == 10000 and out.metrics["f_score_bp"] == 10000
    assert verdict(p, out, "correct_bp") == "go" and verdict(p, out, "incorrect_bp") == "go"

    ids = sorted(kb)
    wrong = agent(lambda q, c, s: reply(kb[ids[(ids.index(by_q[q]["kb_id"]) + 1) % 40]]))
    out = SimpleQARunner().run(p, ctx(wrong))
    assert verdict(p, out, "correct_bp") == "fail" and verdict(p, out, "incorrect_bp") == "fail"

    shy = agent(lambda q, c, s: reply(ABSTAIN))
    out = SimpleQARunner().run(p, ctx(shy))
    assert out.metrics["not_attempted_bp"] == 10000 and out.metrics["incorrect_bp"] == 0
    assert out.metrics["correct_given_attempted_bp"] is None and out.metrics["f_score_bp"] is None
    assert verdict(p, out, "correct_bp") == "fail"


def test_simpleqa_importer_and_skip() -> None:
    items = load_simpleqa(FIX / "simpleqa_vi")
    assert [i["answer"] for i in items] == ["88", "Lena Marlowe", "1.987"]
    a = agent(lambda q, c, s: reply("88"))
    p = pack("simpleqa_vi", min_items=1)
    out = SimpleQARunner().run(p, ctx(a, data_root=FIX))
    assert out.metrics["correct_bp"] == 3333 and out.metrics["incorrect_bp"] == 6666
    out = SimpleQARunner().run(pack("simpleqa_vi"), ctx(a, data_root=FIX))
    assert out.status == "skip"
    assert SimpleQARunner().run(p, ctx(a, data_mode="bank")).status == "skip"


# --------------------------------------------------------------------------- HaluEval


def _reply_and_result(events: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    text = result = ""
    for e in events:
        if e.get("tool_name") == "reply":
            text = json.loads(e["args_masked"])["text"]
        elif e.get("result_masked"):
            result = e["result_masked"]
    return text, result


def good_judge_score(events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    text, result = _reply_and_result(events)
    invented = not numbers(text) <= numbers(result) or any(
        w in text and w not in result for w in ("cam kết", "đảm bảo")
    )
    return {"score_bp": 9000 if invented else 500, "label": "hallucination", "tier": 1}


def test_halueval_good_and_bad_judge() -> None:
    p = pack("halueval_vi")
    out = HaluEvalRunner().run(p, ctx(FakeJudge(score_fn=good_judge_score)))
    assert out.n_items == 40 and out.data_mode == "synthetic"
    assert out.metrics["false_alarm_bp"] == 0
    assert verdict(p, out, "hallucination_recall_bp") == "go"
    assert verdict(p, out, "accuracy_bp") == "go"
    bad = FakeJudge(score_fn=lambda e: {"score_bp": 0, "label": "benign", "tier": 1})
    out = HaluEvalRunner().run(p, ctx(bad))
    assert out.metrics["hallucination_recall_bp"] == 0 and out.metrics["accuracy_bp"] == 5000
    assert verdict(p, out, "hallucination_recall_bp") == "fail"
    paranoid = FakeJudge(score_fn=lambda e: {"score_bp": 10000, "label": "x", "tier": 1})
    out = HaluEvalRunner().run(p, ctx(paranoid))
    assert verdict(p, out, "false_alarm_bp") == "fail"


def test_halueval_trace_shape_and_errors() -> None:
    ev = qa_trace("t1", "Kiến thức", "Câu hỏi?", "Trả lời")
    assert [e["event_type"] for e in ev] == ["message", "tool_call", "tool_call"]
    assert ev[1]["result_masked"] == "Kiến thức" and ev[2]["tool_name"] == "reply"
    p = pack("halueval_vi")
    broken = FakeJudge(score_fn=lambda e: {"label": "x"})
    out = HaluEvalRunner().run(p, ctx(broken))
    assert out.details["judge_errors"] == 80 and out.metrics["hallucination_recall_bp"] == 0


def test_halueval_importer_skips() -> None:
    items = load_halueval(FIX / "halueval_vi")
    assert len(items) == 3 and items[0]["right_answer"] == "The Orchid Tower has 40 floors."
    j = FakeJudge(score_fn=good_judge_score)
    out = HaluEvalRunner().run(pack("halueval_vi", min_items=1), ctx(j, data_root=FIX))
    assert out.status == "ok" and out.n_items == 3 and out.data_mode == "bank_supplied_path"
    assert out.metrics["hallucination_recall_bp"] >= 6600
    assert (
        HaluEvalRunner().run(pack("halueval_vi"), ctx(agent(lambda q, c, s: reply("")))).status
        == "skip"
    )
    assert HaluEvalRunner().run(pack("halueval_vi"), ctx(j, data_mode="bank")).status == "skip"


# --------------------------------------------------------------------------- RAGAS


def extractive(question: str, contexts: Sequence[str], sample: int) -> TargetReply:
    if not contexts:
        return reply(ABSTAIN)
    return reply(max(contexts, key=lambda c: overlap_bp(question, c)))


def test_ragas_agent_good_and_bad() -> None:
    p = pack("ragas_rag_triad")
    out = RagasTriadRunner().run(p, ctx(agent(extractive)))
    assert verdict(p, out, "faithfulness_bp") == "go"
    assert verdict(p, out, "answer_relevance_bp") == "go"
    assert out.metrics["context_precision_bp"] is not None and out.n_items == 30
    invent = agent(
        lambda q, c, s: reply("Ngân hàng cam kết hoàn tiền gấp đôi và phí chỉ 999.999 đồng.")
    )
    out = RagasTriadRunner().run(p, ctx(invent))
    assert verdict(p, out, "faithfulness_bp") == "fail"
    shy = RagasTriadRunner().run(p, ctx(agent(lambda q, c, s: reply(ABSTAIN))))
    assert shy.status == "ok" and shy.metrics["faithfulness_bp"] is None
    assert shy.details["abstained"] == 30


def test_ragas_wrong_number_is_unfaithful() -> None:
    p = pack("ragas_rag_triad")
    item = rows("ragas_rag_triad.jsonl")[0]
    wrong = item["answer"].replace("100.000", "900.000")
    assert wrong != item["answer"]
    from supervisor.assurance.runners.accuracy import faithfulness_bp

    assert faithfulness_bp(item["answer"], item["contexts"]) == 10000
    assert faithfulness_bp(wrong, item["contexts"]) == 0
    assert p.metric("context_precision_bp").direction == "higher_better"


def test_ragas_traces_good_and_bad() -> None:
    p = pack("ragas_rag_triad")
    data = rows("halueval_vi.jsonl")
    good_rows, bad_rows = [], []
    for i, r in enumerate(data):
        good_rows += qa_trace(f"g{i}", r["knowledge"], r["question"], r["right_answer"])
        bad_rows += qa_trace(f"b{i}", r["knowledge"], r["question"], r["hallucinated_answer"])
    out = RagasTriadRunner().run(p, ctx(FakeTraces(rows=good_rows)))
    assert out.status == "ok" and out.metrics["context_precision_bp"] is None
    assert verdict(p, out, "faithfulness_bp") == "go"
    assert verdict(p, out, "answer_relevance_bp") == "go"
    out = RagasTriadRunner().run(p, ctx(FakeTraces(rows=bad_rows)))
    assert verdict(p, out, "faithfulness_bp") == "fail"
    empty = RagasTriadRunner().run(p, ctx(FakeTraces(rows=[])))
    assert empty.status == "skip"


def test_ragas_skips_and_import() -> None:
    p = pack("ragas_rag_triad")
    assert RagasTriadRunner().run(p, ctx(FakeJudge(score_fn=lambda e: {}))).status == "skip"
    assert RagasTriadRunner().run(p, ctx(agent(extractive), data_mode="bank")).status == "skip"
    out = RagasTriadRunner().run(
        pack("ragas_rag_triad", min_items=1), ctx(agent(extractive), data_root=FIX)
    )
    assert out.status == "ok" and out.n_items == 2 and out.data_mode == "bank_supplied_path"
    assert out.metrics["faithfulness_bp"] == 10000


# --------------------------------------------------------------------------- SelfCheck


def _answers() -> tuple[dict[str, str], list[str]]:
    kb = {r["id"]: r["answer"] for r in rows("kb_vi.jsonl")}
    by_q = {r["problem"]: kb[r["kb_id"]] for r in rows("simpleqa_vi.jsonl")}
    return by_q, sorted(kb.values())


def test_selfcheck_consistent_vs_random() -> None:
    p = pack("selfcheck_consistency")
    by_q, pool = _answers()
    steady = agent(lambda q, c, s: reply(by_q.get(q, ABSTAIN)))
    out = SelfCheckRunner().run(p, ctx(steady))
    assert out.metrics["mean_inconsistency_bp"] == 0 and out.metrics["flagged_sentence_bp"] == 0
    assert verdict(p, out, "mean_inconsistency_bp") == "go"
    assert out.details["abstained"] == 10 and out.n_items == 30

    def wobbly(q: str, c: Sequence[str], s: int) -> TargetReply:
        base = pool.index(by_q[q]) if q in by_q else 0
        return reply(pool[(base + s * 7) % len(pool)])

    out = SelfCheckRunner().run(p, ctx(agent(wobbly)))
    assert verdict(p, out, "mean_inconsistency_bp") == "fail"
    assert verdict(p, out, "flagged_sentence_bp") == "fail"


def test_selfcheck_skips_and_import() -> None:
    p = pack("selfcheck_consistency")
    a = agent(lambda q, c, s: reply("Phí là 50.000 đồng."))
    assert SelfCheckRunner().run(p, ctx(FakeTraces())).status == "skip"
    assert SelfCheckRunner().run(p, ctx(a, data_mode="bank")).status == "skip"
    out = SelfCheckRunner().run(
        pack("selfcheck_consistency", min_items=1),
        ctx(a, data_root=FIX, extras={"selfcheck_samples": 2}),
    )
    assert out.status == "ok" and out.n_items == 3 and out.details["samples"] == 2


# --------------------------------------------------------------------------- judge golden


def mock_factory():
    def make() -> JudgeRouter:
        chats = {
            "t1": MockJudgeChat(1, model_id="mock-judge-t1"),
            "t2": MockJudgeChat(2, model_id="mock-judge-t2"),
        }
        return JudgeRouter.from_settings(load_settings(), chats=chats)

    return make


class BlindChat(MockJudgeChat):
    def complete_json(self, messages, json_schema, timeout_s=None):  # type: ignore[no-untyped-def]
        return _reply(0, "benign")


def blind_factory():
    def make() -> JudgeRouter:
        chats = {
            "t1": BlindChat(1, model_id="mock-judge-t1"),
            "t2": BlindChat(2, model_id="mock-judge-t2"),
        }
        return JudgeRouter.from_settings(load_settings(), chats=chats)

    return make


def test_judge_golden_mock_good_and_blind_bad() -> None:
    p = pack("judge_golden_set")
    good = FakeJudge(score_fn=lambda e: {}, factory=mock_factory())
    out = JudgeGoldenSetRunner().run(p, ctx(good))
    assert out.status == "ok" and out.data_mode == "synthetic" and out.is_mock
    assert verdict(p, out, "catch_rate_bp") == "go"
    assert verdict(p, out, "false_alarm_bp") == "go"
    assert out.metrics["n_heldout_items"] == out.n_items > 50
    assert out.details["runs"] == 1 and out.details["harness_mock"] is True

    bad = FakeJudge(score_fn=lambda e: {}, factory=blind_factory())
    out = JudgeGoldenSetRunner().run(p, ctx(bad, max_items=30))
    assert out.metrics["catch_rate_bp"] < 2500  # the injection floor still flags a few
    assert verdict(p, out, "catch_rate_bp") == "fail"
    assert out.n_items == 30


def test_judge_golden_skips_and_import() -> None:
    p = pack("judge_golden_set")
    assert JudgeGoldenSetRunner().run(p, ctx(agent(lambda q, c, s: reply("")))).status == "skip"
    nofac = FakeJudge(score_fn=lambda e: {}, factory=None)
    assert JudgeGoldenSetRunner().run(p, ctx(nofac)).status == "skip"
    j = FakeJudge(score_fn=lambda e: {}, factory=mock_factory())
    assert JudgeGoldenSetRunner().run(p, ctx(j, data_mode="bank")).status == "skip"
    # Fixture: two usable held-out rows, one dev row dropped (reviewers disagree).
    lines = (FIX / "judge_golden_set" / "golden_set.jsonl").read_text("utf-8").splitlines()
    items, dropped = golden_rows_to_items([json.loads(x) for x in lines])
    assert len(items) == 2 and dropped == 1
    assert {i.id: i.positive for i in items} == {"GS-9001": False, "GS-9002": True}
    out = JudgeGoldenSetRunner().run(pack("judge_golden_set", min_items=1), ctx(j, data_root=FIX))
    assert out.status == "ok" and out.data_mode == "bank_supplied_path" and out.n_items == 2
    assert out.metrics["catch_rate_bp"] == 10000 and out.metrics["false_alarm_bp"] == 0
    few = JudgeGoldenSetRunner().run(p, ctx(j, data_root=FIX))
    assert few.status == "skip" and "held-out" in few.skip_reason
