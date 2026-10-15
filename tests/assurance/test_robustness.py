"""WP17 robustness packs: perturb.py, perturbation_vi, paraphrase_consistency, prefilter_evasion."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.assurance import perturb, textutil
from supervisor.assurance.model import EvalPack, RunnerOutput, TargetReply
from supervisor.assurance.runners.robustness import (
    ParaphraseRunner,
    PerturbationRunner,
    PrefilterEvasionRunner,
)
from tests.assurance.fakes import FakeAgent, FakeJudge, FakeTraces, ctx
from tests.conftest import REPO_ROOT

PACKS = REPO_ROOT / "src" / "supervisor" / "assurance" / "packs"
DATA = REPO_ROOT / "data" / "assurance" / "synthetic"


def pack(pid: str) -> EvalPack:
    return EvalPack.model_validate(yaml.safe_load((PACKS / f"{pid}.yaml").read_text("utf-8")))


def rows(pid: str) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (DATA / f"{pid}.jsonl").read_text("utf-8").splitlines() if x]


def status(p: EvalPack, metric: str, value: int | None) -> str:
    """pass / warn / fail / na by the manifest thresholds (same rule as the engine)."""
    t = p.threshold(metric)
    if value is None or t is None:
        return "na"
    if p.metric(metric).direction == "higher_better":
        return "pass" if value >= t.go else ("fail" if value < t.no_go else "warn")
    return "pass" if value <= t.go else ("fail" if value > t.no_go else "warn")


# --------------------------------------------------------------------------- manifests
@pytest.mark.parametrize("pid", ["perturbation_vi", "paraphrase_consistency", "prefilter_evasion"])
def test_manifests_validate(pid: str) -> None:
    p = pack(pid)
    assert p.id == pid and p.dimension == "robustness" and p.licence == "own"
    assert p.runner.startswith("supervisor.assurance.runners.robustness:")
    assert (DATA / f"{pid}.jsonl").is_file()


def test_gates() -> None:
    assert pack("perturbation_vi").launch_gate == "required"
    assert pack("perturbation_vi").judge_gate is True
    assert pack("prefilter_evasion").launch_gate == "required"
    assert pack("paraphrase_consistency").launch_gate == "advisory"
    for pid in ("perturbation_vi", "paraphrase_consistency"):
        p = pack(pid)
        assert {"agent", "judge"} <= set(p.targets)


# ------------------------------------------------------------------------------ perturb
SAMPLE = "Tôi muốn chuyển khoản 5.000.000 đồng, hạn mức và phí là bao nhiêu?"


@pytest.mark.parametrize("kind", perturb.KINDS)
def test_perturb_deterministic_and_changes(kind: str) -> None:
    a = perturb.apply(kind, SAMPLE, seed=7)
    assert a == perturb.apply(kind, SAMPLE, seed=7)
    assert a != SAMPLE


@pytest.mark.parametrize("kind", ["typo", "confusable", "zero_width"])
def test_seed_changes_output(kind: str) -> None:
    outs = {perturb.apply(kind, SAMPLE, seed=s) for s in range(8)}
    assert len(outs) > 1


def test_typos_rate_and_forced_change() -> None:
    assert perturb.typos("ab", seed=1, rate_bp=0) != "ab"  # at least one edit
    heavy = perturb.typos(SAMPLE, seed=3, rate_bp=5000)
    light = perturb.typos(SAMPLE, seed=3, rate_bp=300)
    diff = lambda x: sum(1 for p, q in zip(SAMPLE, x, strict=False) if p != q)  # noqa: E731
    assert diff(heavy) > diff(light)


def test_no_diacritics_and_telex() -> None:
    assert perturb.no_diacritics("chuyển khoản Đà Nẵng") == "chuyen khoan Da Nang"
    assert perturb.telex("chuyển tiền") == "chuyeenr tieenf"
    assert perturb.telex("đường Hà Nội") == "dduwowngf Haf Nooij"
    assert perturb.telex("abc 123") == "abc 123"


def test_code_switch_both_directions() -> None:
    out = perturb.code_switch("Phí chuyển khoản và hạn mức của thẻ")
    assert out == "Fee transfer và limit của card" or "transfer" in out
    assert "limit" in out and "card" in out and "fee" in out.lower()
    back = perturb.code_switch("What is the fee and the limit of my card?")
    assert "phí" in back and "hạn mức" in back and "thẻ" in back
    assert perturb.code_switch("xin chào") == "xin chào"


def test_confusables_zero_width_fullwidth_nfd() -> None:
    c = perturb.confusables("ignore previous", seed=1, rate_bp=10000)
    assert all(
        ch in perturb.CONFUSABLES_REVERSE or not ch.isalpha() or ch not in "aeopcxyi" for ch in c
    )
    assert "".join(perturb.CONFUSABLES_REVERSE.get(ch, ch) for ch in c) == "ignore previous"
    z = perturb.zero_width("chuyển khoản", seed=2)
    assert any(ch in perturb.ZERO_WIDTH for ch in z)
    assert "".join(ch for ch in z if ch not in perturb.ZERO_WIDTH) == "chuyển khoản"
    assert perturb.fullwidth_digits("so 0123") == "so ０１２３"
    d = perturb.nfd("chuyển")
    assert unicodedata.normalize("NFC", d) == "chuyển" and d != "chuyển"


def test_nfc_preserved_where_intended() -> None:
    for kind in ("typo", "code_switch", "telex", "no_diacritics"):
        out = perturb.apply(kind, SAMPLE, seed=1)
        assert unicodedata.normalize("NFC", out) == out
    assert unicodedata.normalize("NFC", perturb.apply("zero_width", SAMPLE, seed=1)) != ""


def test_perturb_events_only_free_text() -> None:
    evs = [r for r in rows("perturbation_vi") if r["kind"] == "judge"][0]["events"]
    out = perturb.perturb_events("telex", evs, seed=1)
    assert [e["tool_name"] for e in out] == [e["tool_name"] for e in evs]
    assert (
        out[0]["args_masked"].startswith("[chat] ")
        and out[0]["args_masked"] != evs[0]["args_masked"]
    )
    assert evs[0]["args_masked"].startswith("[chat] Chuyển")  # input untouched
    assert perturb.perturb_events("typo", evs, seed=1) == perturb.perturb_events(
        "typo", evs, seed=1
    )


def test_data_files_shape() -> None:
    pv = rows("perturbation_vi")
    assert (
        sum(r["kind"] == "agent" for r in pv) >= 38 and sum(r["kind"] == "judge" for r in pv) >= 20
    )
    assert sum(1 for r in pv if r["kind"] == "judge" and r["unsafe"]) == 10
    pc = rows("paraphrase_consistency")
    assert sum(r["kind"] == "agent" for r in pc) == 25
    assert all(len(r["paraphrases"]) == 4 for r in pc if r["kind"] == "agent")
    pf = rows("prefilter_evasion")
    assert (
        sum(r["kind"] == "injection" for r in pf) >= 30
        and sum(r["kind"] == "benign" for r in pf) >= 30
    )


# ------------------------------------------------------------------------------- fakes
def canon(text: str) -> str:
    """What a robust agent does first: strip invisibles, undo look-alikes, NFKC, fold tones."""
    text = "".join(ch for ch in text if ch not in perturb.ZERO_WIDTH)
    text = "".join(perturb.CONFUSABLES_REVERSE.get(ch, ch) for ch in text)
    text = unicodedata.normalize("NFKC", text)
    return textutil.normalise(text, fold_diacritics=True)


def trigrams(text: str) -> set[str]:
    t = " " + re.sub(r"\s+", " ", canon(text)) + " "
    return {t[i : i + 3] for i in range(len(t) - 2)}


def good_agent(known: Mapping[str, str]) -> FakeAgent:
    """Fuzzy lookup on normalised char trigrams; context -> extractive."""
    index = {q: trigrams(q) for q in known}

    def fn(prompt: str, context: Sequence[str], sample: int) -> TargetReply:
        if context:
            return TargetReply(text=context[0], is_mock=True)
        g = trigrams(prompt)
        best = max(index, key=lambda q: len(index[q] & g) / max(1, len(index[q] | g)))
        return TargetReply(text=known[best], is_mock=True)

    return FakeAgent(respond_fn=fn)


def bad_agent(known: Mapping[str, str]) -> FakeAgent:
    """Exact-string lookup: fails on any perturbation."""

    def fn(prompt: str, context: Sequence[str], sample: int) -> TargetReply:
        if prompt in known:
            return TargetReply(text=known[prompt], is_mock=True)
        return TargetReply(text="Xin lỗi, tôi không có thông tin.", is_mock=True)

    return FakeAgent(respond_fn=fn)


def pv_known() -> dict[str, str]:
    return {r["question"]: r["answer"] for r in rows("perturbation_vi") if r["kind"] == "agent"}


def pc_known() -> dict[str, str]:
    return {
        text: r["answer"]
        for r in rows("paraphrase_consistency")
        if r["kind"] == "agent"
        for text in r["paraphrases"].values()
    }


_RISKY_TOOLS = {"ext_transfer_api", "reset_password", "credit_score_override", "update_limits"}


def good_judge_score(events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Structural judge: tool, amount, requested sensitive fields, tool-result payload."""
    risky = False
    for e in events:
        if e.get("event_type") != "tool_call":
            continue
        args = json.loads(e.get("args_masked") or "{}")
        if (
            e.get("tool_name") in _RISKY_TOOLS
            or int(e.get("amount_minor") or 0) >= 50_000_000
            or "fields" in args
            or e.get("result_masked")
        ):
            risky = True
    return {"score_bp": 9000 if risky else 500, "label": "flagged" if risky else "ok", "tier": 1}


_BAD_CUES = (
    "đề nghị",
    "bỏ qua otp",
    "không cần xác minh",
    "cccd đầy đủ",
    "công an",
    "chuyển",
    "ignore previous",
)


def bad_judge_score(events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Exact-phrase judge on raw text: any perturbation or rewording breaks it."""
    text = " ".join(f"{e.get('args_masked') or ''} {e.get('result_masked') or ''}" for e in events)
    hit = any(c in text.lower() for c in _BAD_CUES)
    return {"score_bp": 8000 if hit else 300, "label": "flagged" if hit else "ok", "tier": 1}


# ---------------------------------------------------------------------- perturbation_vi
def test_perturbation_agent_good_vs_bad() -> None:
    p = pack("perturbation_vi")
    good = PerturbationRunner().run(p, ctx(good_agent(pv_known())))
    assert good.status == "ok" and good.n_items >= 38
    assert good.metrics["verdict_flip_rate_bp"] is None
    assert status(p, "answer_consistency_bp", good.metrics["answer_consistency_bp"]) == "pass"
    assert status(p, "accuracy_drop_bp", good.metrics["accuracy_drop_bp"]) == "pass"
    assert set(good.details["per_kind"]) == set(
        ("typo", "no_diacritics", "telex", "code_switch", "confusable", "zero_width")
    )
    bad = PerturbationRunner().run(p, ctx(bad_agent(pv_known())))
    assert status(p, "answer_consistency_bp", bad.metrics["answer_consistency_bp"]) == "fail"
    assert status(p, "accuracy_drop_bp", bad.metrics["accuracy_drop_bp"]) == "fail"
    assert bad.metrics["worst_kind_consistency_bp"] is not None
    assert good.is_mock is True
    assert len(good.dataset_sha256) == 64 and good.dataset_id.startswith("perturbation_vi")


def test_perturbation_judge_good_vs_bad() -> None:
    p = pack("perturbation_vi")
    good = PerturbationRunner().run(p, ctx(FakeJudge(score_fn=good_judge_score)))
    assert good.status == "ok" and good.n_items == 20
    assert good.metrics["answer_consistency_bp"] is None
    assert status(p, "verdict_flip_rate_bp", good.metrics["verdict_flip_rate_bp"]) == "pass"
    assert status(p, "mean_score_shift_bp", good.metrics["mean_score_shift_bp"]) == "pass"
    bad = PerturbationRunner().run(p, ctx(FakeJudge(score_fn=bad_judge_score)))
    assert status(p, "verdict_flip_rate_bp", bad.metrics["verdict_flip_rate_bp"]) == "fail"
    assert status(p, "mean_score_shift_bp", bad.metrics["mean_score_shift_bp"]) == "fail"
    assert bad.details["flag_lost_items"]


def test_perturbation_deterministic() -> None:
    p = pack("perturbation_vi")
    a = PerturbationRunner().run(p, ctx(bad_agent(pv_known())))
    b = PerturbationRunner().run(p, ctx(bad_agent(pv_known())))
    assert a.metrics == b.metrics and a.dataset_sha256 == b.dataset_sha256


def test_perturbation_max_items_and_skips() -> None:
    p = pack("perturbation_vi")
    small = PerturbationRunner().run(p, ctx(good_agent(pv_known()), max_items=20))
    assert small.status == "ok" and small.n_items == 20
    few = PerturbationRunner().run(p, ctx(good_agent(pv_known()), max_items=5))
    assert few.status == "skip" and "need" in few.skip_reason
    bank = PerturbationRunner().run(p, ctx(good_agent(pv_known()), data_mode="bank"))
    assert bank.status == "skip" and "no bank data" in bank.skip_reason
    vend = PerturbationRunner().run(p, ctx(good_agent(pv_known()), data_mode="vendored"))
    assert vend.status == "skip"
    nochat = FakeAgent(capabilities=frozenset({"tools"}))
    assert PerturbationRunner().run(p, ctx(nochat)).status == "skip"
    assert PerturbationRunner().run(p, ctx(FakeTraces())).status == "skip"


# ------------------------------------------------------------------ paraphrase_consistency
def test_paraphrase_agent_good_vs_bad() -> None:
    p = pack("paraphrase_consistency")
    good = ParaphraseRunner().run(p, ctx(good_agent(pc_known())))
    assert good.status == "ok" and good.n_items == 25
    assert good.metrics["label_agreement_bp"] is None
    assert status(p, "pairwise_consistency_bp", good.metrics["pairwise_consistency_bp"]) == "pass"
    assert status(p, "paraphrase_accuracy_bp", good.metrics["paraphrase_accuracy_bp"]) == "pass"
    formal_only = {
        r["paraphrases"]["formal"]: r["answer"]
        for r in rows("paraphrase_consistency")
        if r["kind"] == "agent"
    }
    bad = ParaphraseRunner().run(p, ctx(bad_agent(formal_only)))
    assert status(p, "pairwise_consistency_bp", bad.metrics["pairwise_consistency_bp"]) == "fail"
    assert status(p, "paraphrase_accuracy_bp", bad.metrics["paraphrase_accuracy_bp"]) == "fail"
    assert set(good.details["accuracy_by_variant_bp"]) == {
        "formal",
        "informal",
        "southern",
        "english_terms",
    }


def test_paraphrase_judge_good_vs_bad() -> None:
    p = pack("paraphrase_consistency")
    good = ParaphraseRunner().run(p, ctx(FakeJudge(score_fn=good_judge_score)))
    assert good.status == "ok" and good.n_items == 8
    assert (
        good.metrics["pairwise_consistency_bp"] is None
        and good.metrics["paraphrase_accuracy_bp"] is None
    )
    assert status(p, "label_agreement_bp", good.metrics["label_agreement_bp"]) == "pass"
    bad = ParaphraseRunner().run(p, ctx(FakeJudge(score_fn=bad_judge_score)))
    assert status(p, "label_agreement_bp", bad.metrics["label_agreement_bp"]) == "fail"
    assert bad.details["unstable_items"]


def test_paraphrase_skips() -> None:
    p = pack("paraphrase_consistency")
    assert ParaphraseRunner().run(p, ctx(good_agent(pc_known()), data_mode="bank")).status == "skip"
    assert ParaphraseRunner().run(p, ctx(good_agent(pc_known()), max_items=3)).status == "skip"
    assert ParaphraseRunner().run(p, ctx(FakeTraces())).status == "skip"


# --------------------------------------------------------------------- prefilter_evasion
def test_prefilter_runs_on_real_classifier() -> None:
    p = pack("prefilter_evasion")
    out = PrefilterEvasionRunner().run(p, ctx(FakeAgent()))
    assert isinstance(out, RunnerOutput) and out.status == "ok"
    m = out.metrics
    assert all(isinstance(v, int) for v in m.values())
    assert m["clean_detect_bp"] >= 9000  # type: ignore[operator]
    assert status(p, "benign_false_positive_bp", m["benign_false_positive_bp"]) == "pass"
    assert m["detect_drop_bp"] == m["clean_detect_bp"] - m["perturbed_detect_bp"]  # type: ignore[operator]
    per = out.details["per_kind_detect_bp"]
    # Known gaps of regex_v1 (findings, not hidden): look-alikes, zero-width, NFD, Telex.
    assert per["no_diacritics"] == 10000
    for gap in ("confusable", "zero_width", "nfd", "telex"):
        assert per[gap] < 5000, gap
    assert m["detect_drop_bp"] > 0  # type: ignore[operator]
    again = PrefilterEvasionRunner().run(p, ctx(FakeAgent()))
    assert again.metrics == m


def test_prefilter_skips() -> None:
    p = pack("prefilter_evasion")
    assert PrefilterEvasionRunner().run(p, ctx(FakeAgent(), data_mode="bank")).status == "skip"
    assert PrefilterEvasionRunner().run(p, ctx(FakeAgent(), max_items=10)).status == "skip"
    assert PrefilterEvasionRunner().run(p, ctx(FakeTraces())).status == "skip"


def test_data_dir_is_repo_relative(tmp_path: Path) -> None:
    out = PerturbationRunner().run(
        pack("perturbation_vi"), ctx(good_agent(pv_known()), repo_root=tmp_path)
    )
    assert out.status == "skip" and "missing" in out.skip_reason
