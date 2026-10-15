"""WP17 bias and fairness packs: manifests, importers, GOOD and BAD fake targets, skips."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.assurance.model import EvalPack, RunnerOutput, TargetReply
from supervisor.assurance.runners.fairness import (
    BbqRunner,
    BoldRunner,
    CounterfactualRunner,
    CrowsPairsRunner,
    FairnessMetricsRunner,
    FourFifthsRunner,
    StereoSetRunner,
    WinoBiasRunner,
)
from supervisor.assurance.runners.fairness_common import map_choice, read_jsonl, sdiv
from supervisor.assurance.runners.fairness_decisions import (
    build_applicants,
    build_messages,
    creditworthy,
    divergence_bp,
    region_of,
    swap_attribute,
)
from supervisor.assurance.runners.fairness_qa import (
    is_biased_answer,
    load_bbq_dir,
    load_wino_dir,
)
from supervisor.assurance.runners.fairness_text import (
    load_bold_dir,
    load_crows_csv,
    load_stereoset_dev,
    sentiment_bp,
)
from supervisor.assurance.textutil import tokens
from tests.assurance.fakes import FakeAgent, FakeTraces, ctx
from tests.conftest import REPO_ROOT

PACKS_DIR = REPO_ROOT / "src" / "supervisor" / "assurance" / "packs"
SYN = REPO_ROOT / "data" / "assurance" / "synthetic"
FIX = Path(__file__).parent / "fixtures"
IDS = (
    "bbq_vi",
    "winobias_vi",
    "bold_vi",
    "crows_pairs_vi",
    "stereoset_vi",
    "fairness_metrics",
    "four_fifths_rule",
    "counterfactual_vi",
)


def pack(pid: str) -> EvalPack:
    return EvalPack.model_validate(yaml.safe_load((PACKS_DIR / f"{pid}.yaml").read_text("utf-8")))


def meets_go(p: EvalPack, metrics: Mapping[str, int | None]) -> bool:
    for t in p.thresholds:
        v = metrics.get(t.metric)
        if v is None:
            return False
        higher = p.metric(t.metric).direction == "higher_better"
        if (v < t.go) if higher else (v > t.go):
            return False
    return True


def misses_no_go(p: EvalPack, metrics: Mapping[str, int | None]) -> bool:
    for t in p.thresholds:
        v = metrics.get(t.metric)
        if v is None:
            continue
        higher = p.metric(t.metric).direction == "higher_better"
        if (v < t.no_go) if higher else (v > t.no_go):
            return True
    return False


def no_float(obj: Any) -> bool:
    if isinstance(obj, float):
        return False
    if isinstance(obj, dict):
        return all(no_float(v) for v in obj.values())
    if isinstance(obj, list):
        return all(no_float(v) for v in obj)
    return True


def reply(text: str) -> TargetReply:
    return TargetReply(text=text, is_mock=True)


def letter_of(prompt: str, text: str) -> str:
    for m in re.finditer(r"^([A-C])\. (.*)$", prompt, re.M):
        if m.group(2).strip() == text.strip():
            return m.group(1)
    raise AssertionError(f"option {text!r} not in prompt")


def agent(fn: Any, **kw: Any) -> FakeAgent:
    return FakeAgent(respond_fn=lambda p, c, s: fn(p), **kw)


# --------------------------------------------------------------------------- manifests


@pytest.mark.parametrize("pid", IDS)
def test_manifest_valid(pid: str) -> None:
    p = pack(pid)
    assert p.id == pid and p.dimension == "bias_fairness"
    assert "bias_monitoring" in p.maps_to.regkb_duties
    if p.licence in ("CC-BY-SA-4.0", "CC-BY-4.0", "MIT"):
        assert p.source.licence_verified_on == "2026-10-15"
    if p.licence == "CC-BY-SA-4.0":
        assert "vendored_sample" not in p.data_modes


def test_launch_gates() -> None:
    for pid in ("counterfactual_vi", "fairness_metrics", "four_fifths_rule"):
        assert pack(pid).launch_gate == "required"
    for pid in ("bbq_vi", "winobias_vi", "bold_vi", "crows_pairs_vi", "stereoset_vi"):
        assert pack(pid).launch_gate == "advisory"


@pytest.mark.parametrize(
    "pid", ["bbq_vi", "winobias_vi", "bold_vi", "crows_pairs_vi", "stereoset_vi"]
)
def test_synthetic_files_enough_items(pid: str) -> None:
    assert len(read_jsonl(SYN / f"{pid}.jsonl")) >= pack(pid).min_items


# --------------------------------------------------------------------------- helpers


def test_sdiv_and_map_choice() -> None:
    assert sdiv(-3, 2) == -2 and sdiv(3, 2) == 2 and sdiv(-1, 3) == 0
    opts = ["Người phụ nữ", "Người đàn ông", "Không xác định"]
    order = [2, 0, 1]
    assert map_choice("A", opts, order) == 2
    assert map_choice("B. Người phụ nữ", opts, order) == 0
    assert map_choice("Đáp án: C", opts, order) == 1
    assert map_choice("Chắc là người đàn ông.", opts, order, unknown_index=2) == 1
    assert (
        map_choice(
            "Thông tin chưa đủ để kết luận, không thể xác định", opts, order, unknown_index=2
        )
        == 2
    )
    assert map_choice("Anh ấy làm việc ở ngân hàng", opts, order, unknown_index=2) is None


def test_sentiment_lexicon() -> None:
    assert sentiment_bp("Họ rất tốt và chăm chỉ") == 10000
    assert sentiment_bp("Họ lười và nguy hiểm") == -10000
    assert sentiment_bp("Họ không lười") == 10000
    assert sentiment_bp("Họ ngủ nhiều") == 0  # 'ngủ' is not 'ngu'
    assert sentiment_bp("lazy but honest") == 0


# --------------------------------------------------------------------------- BBQ


def _parse_bbq(prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = read_jsonl(SYN / "bbq_vi.jsonl")
    by_key = {(r["context"] + "|" + r["question"]): r for r in rows}
    ctx_line = prompt.split("\nCâu hỏi: ")[0]
    q = prompt.split("\nCâu hỏi: ")[1].split("\n")[0]
    return by_key[ctx_line + "|" + q], {}


def bbq_good(prompt: str) -> TargetReply:
    row, _ = _parse_bbq(prompt)
    return reply(letter_of(prompt, row[f"ans{row['label']}"]))


def bbq_bad(prompt: str) -> TargetReply:
    row, _ = _parse_bbq(prompt)
    for i in range(3):
        unk = row["answer_info"][f"ans{i}"][1] == "unknown"
        if not unk and is_biased_answer(row, i):
            return reply(letter_of(prompt, row[f"ans{i}"]))
    raise AssertionError("no biased answer")


def test_bbq_good_and_bad() -> None:
    p = pack("bbq_vi")
    good = BbqRunner().run(p, ctx(agent(bbq_good)))
    assert good.status == "ok" and good.n_items == 48 and good.data_mode == "synthetic"
    assert good.metrics["accuracy_ambig_bp"] == 10000
    assert good.metrics["accuracy_disambig_bp"] == 10000
    assert good.metrics["abs_bias_score_ambig_bp"] == 0
    assert meets_go(p, good.metrics) and no_float(good.details) and len(good.dataset_sha256) == 64
    bad = BbqRunner().run(p, ctx(agent(bbq_bad)))
    assert bad.metrics["accuracy_ambig_bp"] == 0
    assert bad.metrics["bias_score_ambig_bp"] == 10000
    assert bad.metrics["bias_score_disambig_bp"] > 0
    assert misses_no_go(p, bad.metrics) and not meets_go(p, bad.metrics)


def test_bbq_reproducible_and_capped() -> None:
    p = pack("bbq_vi")
    a = BbqRunner().run(p, ctx(agent(bbq_good), max_items=36))
    b = BbqRunner().run(p, ctx(agent(bbq_good), max_items=36))
    assert a.n_items == 36 and a.dataset_sha256 == b.dataset_sha256 and a.metrics == b.metrics


def test_bbq_unparsed_counts_wrong() -> None:
    out = BbqRunner().run(pack("bbq_vi"), ctx(agent(lambda p: reply("Tôi không muốn trả lời."))))
    assert out.metrics["accuracy_ambig_bp"] == 0 and out.details["n_unparsed"] == 48
    assert out.metrics["abs_bias_score_ambig_bp"] is None


def test_bbq_importer(tmp_path: Path) -> None:
    rows, notes = load_bbq_dir(FIX / "bbq_vi")
    assert len(rows) == 4 and notes["dropped_rows"] == 2
    amb = [r for r in rows if r["context_condition"] == "ambig"]
    assert all(is_biased_answer(r, 0) == (r["question_polarity"] == "neg") for r in amb)
    # original item shape runs through the runner (bank mode, 4 items < min_items -> skip)
    out = BbqRunner().run(pack("bbq_vi"), ctx(agent(bbq_good), data_root=FIX, data_mode="bank"))
    assert (
        out.status == "skip"
        and "needs" in out.skip_reason
        and out.data_mode == "bank_supplied_path"
    )


def test_bbq_bank_end_to_end(tmp_path: Path) -> None:
    d = tmp_path / "bbq_vi"
    d.mkdir()
    src = (FIX / "bbq_vi" / "Made_up_sample.jsonl").read_text("utf-8").splitlines()[:4]
    (d / "x.jsonl").write_text("\n".join(src * 10) + "\n", encoding="utf-8")  # 40 rows
    p = pack("bbq_vi")

    out = BbqRunner().run(p, ctx(agent(lambda prompt: reply("C")), data_root=tmp_path))
    assert out.status == "ok" and out.data_mode == "bank_supplied_path" and out.n_items == 40


# --------------------------------------------------------------------------- WinoBias


def wino_row(prompt: str) -> dict[str, Any]:
    sent = prompt.split("Câu: ")[1].split("\n")[0]
    return next(r for r in read_jsonl(SYN / "winobias_vi.jsonl") if r["sentence"] == sent)


def test_wino_good_and_bad() -> None:
    p = pack("winobias_vi")
    good = WinoBiasRunner().run(
        p, ctx(agent(lambda pr: reply(letter_of(pr, wino_row(pr)["referent"]))))
    )
    assert good.status == "ok" and good.n_items == 48
    assert good.metrics == {
        "accuracy_pro_bp": 10000,
        "accuracy_anti_bp": 10000,
        "pro_anti_gap_bp": 0,
    }
    assert meets_go(p, good.metrics)

    def stereo(pr: str) -> TargetReply:
        r = wino_row(pr)
        pick = r["referent"] if r["pronoun_gender"] == r["referent_stereotype"] else r["other"]
        return reply(letter_of(pr, pick))

    bad = WinoBiasRunner().run(p, ctx(agent(stereo)))
    assert bad.metrics["accuracy_pro_bp"] == 10000 and bad.metrics["accuracy_anti_bp"] == 0
    assert bad.metrics["pro_anti_gap_bp"] == 10000 and misses_no_go(p, bad.metrics)


def test_wino_importer(tmp_path: Path) -> None:
    rows, notes = load_wino_dir(FIX / "winobias_vi")
    assert len(rows) == 6 and notes["dropped_lines"] == 1
    pros = [r for r in rows if r["pro"]]
    first, second = pros[0], pros[1]
    assert (first["referent"], first["other"], first["pro"]) == ("welder", "florist", True)
    assert (second["referent"], second["other"], second["pronoun_gender"]) == (
        "florist",
        "welder",
        "female",
    )
    assert sum(1 for r in rows if not r["pro"]) == 3
    out = WinoBiasRunner().run(
        pack("winobias_vi"), ctx(agent(lambda pr: reply("A")), data_root=FIX, data_mode="bank")
    )
    assert out.status == "skip" and out.n_items == 6  # fewer than min_items: never a pass


# --------------------------------------------------------------------------- BOLD


def test_bold_good_and_bad() -> None:
    p = pack("bold_vi")
    good = BoldRunner().run(p, ctx(agent(lambda pr: reply("Họ sống và làm việc ở nhiều nơi."))))
    assert good.status == "ok" and good.n_items == 51
    assert good.metrics == {"max_group_sentiment_gap_bp": 0, "negative_reply_bp": 0}
    assert meets_go(p, good.metrics)
    low = ("Hà Giang", "H'Mông", "Phụ nữ", "Nông dân")

    def skewed(pr: str) -> TargetReply:
        return reply(
            "Họ lười và nguy hiểm."
            if any(k.lower() in pr.lower() for k in low)
            else "Họ rất tốt và giỏi."
        )

    bad = BoldRunner().run(p, ctx(agent(skewed)))
    assert bad.metrics["max_group_sentiment_gap_bp"] == 20000
    assert misses_no_go(p, bad.metrics)


def test_bold_importer(tmp_path: Path) -> None:
    rows, notes = load_bold_dir(FIX / "bold_vi")
    assert notes["files"] == ["made_up_prompt.json"] and len(rows) == 5
    assert {r["group"] for r in rows} == {"Group_One", "Group_Two"}
    assert rows[0]["domain"] == "made_up"
    out = BoldRunner().run(
        pack("bold_vi"), ctx(agent(lambda pr: reply("x")), data_root=FIX, data_mode="bank")
    )
    assert out.status == "skip"


# --------------------------------------------------------------------------- CrowS-Pairs


def test_crows_good_and_bad() -> None:
    p = pack("crows_pairs_vi")
    rows = read_jsonl(SYN / "crows_pairs_vi.jsonl")
    more = {r["sent_more"] for r in rows}
    state = {"n": 0}

    def alternate(pr: str) -> TargetReply:
        opts = re.findall(r"^([A-B])\. (.*)$", pr, re.M)
        want_more = state["n"] % 2 == 0
        state["n"] += 1
        for letter, text in opts:
            if (text in more) == want_more:
                return reply(letter)
        raise AssertionError

    good = CrowsPairsRunner().run(p, ctx(agent(alternate)))
    assert good.status == "ok" and good.n_items == 40
    assert good.metrics["stereotype_preference_bp"] == 5000 and meets_go(p, good.metrics)

    def stereo(pr: str) -> TargetReply:
        for letter, text in re.findall(r"^([A-B])\. (.*)$", pr, re.M):
            if text in more:
                return reply(letter)
        raise AssertionError

    bad = CrowsPairsRunner().run(p, ctx(agent(stereo)))
    assert bad.metrics["stereotype_preference_bp"] == 10000
    assert bad.metrics["deviation_from_parity_bp"] == 5000 and misses_no_go(p, bad.metrics)
    refuse = CrowsPairsRunner().run(p, ctx(agent(lambda pr: reply("Cả hai đều như nhau."))))
    assert refuse.metrics["stereotype_preference_bp"] == 5000


def test_crows_importer() -> None:
    rows, notes = load_crows_csv(FIX / "crows_pairs_vi")
    assert len(rows) == 3 and notes["dropped_rows"] == 1
    assert rows[0]["bias_type"] == "race-color" and rows[1]["stereo_antistereo"] == "antistereo"
    out = CrowsPairsRunner().run(
        pack("crows_pairs_vi"), ctx(agent(lambda pr: reply("A")), data_root=FIX, data_mode="bank")
    )
    assert out.status == "skip"


# --------------------------------------------------------------------------- StereoSet


def test_stereoset_good_and_bad() -> None:
    p = pack("stereoset_vi")
    label_of: dict[str, str] = {}
    for r in read_jsonl(SYN / "stereoset_vi.jsonl"):
        for k, v in r["options"].items():
            label_of[v] = k
    state = {"n": 0}

    def pick(pr: str, want: str) -> str:
        for letter, text in re.findall(r"^([A-C])\. (.*)$", pr, re.M):
            if label_of[text] == want:
                return letter
        raise AssertionError

    def alternate(pr: str) -> TargetReply:
        state["n"] += 1
        return reply(pick(pr, "stereotype" if state["n"] % 2 else "anti-stereotype"))

    good = StereoSetRunner().run(p, ctx(agent(alternate)))
    assert good.n_items == 36 and good.metrics["lms_bp"] == 10000
    assert (
        good.metrics["ss_bp"] == 5000
        and good.metrics["icat_bp"] == 10000
        and meets_go(p, good.metrics)
    )
    bad = StereoSetRunner().run(p, ctx(agent(lambda pr: reply(pick(pr, "stereotype")))))
    assert (
        bad.metrics["ss_bp"] == 10000
        and bad.metrics["icat_bp"] == 0
        and misses_no_go(p, bad.metrics)
    )
    junk = StereoSetRunner().run(p, ctx(agent(lambda pr: reply(pick(pr, "unrelated")))))
    assert (
        junk.metrics["lms_bp"] == 0
        and junk.metrics["icat_bp"] == 0
        and junk.metrics["ss_bp"] is None
    )


def test_stereoset_importer() -> None:
    rows, notes = load_stereoset_dev(FIX / "stereoset_vi")
    assert len(rows) == 2 and notes["dropped_items"] == 1
    assert rows[0]["options"]["unrelated"] == "The gardener was triangle."
    out = StereoSetRunner().run(
        pack("stereoset_vi"), ctx(agent(lambda pr: reply("A")), data_root=FIX, data_mode="bank")
    )
    assert out.status == "skip"


# --------------------------------------------------------------------------- skips


@pytest.mark.parametrize(
    "pid", ["bbq_vi", "winobias_vi", "bold_vi", "crows_pairs_vi", "stereoset_vi"]
)
def test_text_packs_skip_paths(pid: str, tmp_path: Path) -> None:
    runner = {
        "bbq_vi": BbqRunner,
        "winobias_vi": WinoBiasRunner,
        "bold_vi": BoldRunner,
        "crows_pairs_vi": CrowsPairsRunner,
        "stereoset_vi": StereoSetRunner,
    }[pid]()
    p = pack(pid)
    a = agent(lambda pr: reply("A"))
    no_bank = runner.run(p, ctx(a, data_mode="bank", data_root=tmp_path))
    assert no_bank.status == "skip" and "no bank data" in no_bank.skip_reason
    assert runner.run(p, ctx(a, data_mode="vendored")).status == "skip"
    no_chat = FakeAgent(capabilities=frozenset({"decide"}))
    assert runner.run(p, ctx(no_chat)).skip_reason == "target lacks capability 'chat'"
    few = runner.run(p, ctx(a, max_items=3))
    assert few.status == "skip" and "needs" in few.skip_reason
    assert runner.run(p, ctx(FakeTraces())).status == "skip"


# --------------------------------------------------------------------------- applicants


def test_applicants_deterministic_and_balanced() -> None:
    a1, a2 = build_applicants(20261015), build_applicants(20261015)
    assert a1 == a2 and len(a1) == 210
    assert a1 != build_applicants(7)
    from collections import Counter

    assert Counter(a["gender"] for a in a1) == {"female": 105, "male": 105}
    assert min(Counter(a["ethnicity"] for a in a1).values()) >= 20
    # balanced design: every group of every attribute has the same financial profiles
    fin = ("credit_score", "monthly_income_minor", "requested_amount_minor", "existing_debt_minor")
    for attr in ("gender", "age_band", "ethnicity", "province_region"):
        sets = {}
        for a in a1:
            g = region_of(a["province_code"]) if attr == "province_region" else a[attr]
            sets.setdefault(g, Counter())[tuple(a[k] for k in fin)] += 1
        n_groups = len(sets)
        base = {k: v * n_groups for k, v in next(iter(sets.values())).items()}
        for c in sets.values():
            assert {k: v * n_groups for k, v in c.items()} == base
    assert min(Counter(region_of(a["province_code"]) for a in a1).values()) >= 20
    assert sum(creditworthy(a) for a in a1) == 84
    assert "creditworthy" not in a1[0]


def test_swap_attribute_changes_only_one_thing() -> None:
    a = build_applicants(1)[0]
    fin = ("monthly_income_minor", "credit_score", "requested_amount_minor", "existing_debt_minor")
    for attr, keys in (
        ("gender", {"gender", "full_name"}),
        ("age_band", {"age_band"}),
        ("province", {"province", "province_code"}),
        ("ethnicity", {"ethnicity"}),
    ):
        b = swap_attribute(a, attr, 3)
        assert {k for k in a if a[k] != b[k]} == keys
        assert all(a[k] == b[k] for k in fin)
    g = swap_attribute(a, "gender")
    assert g["full_name"].split()[0] == a["full_name"].split()[0]


# --------------------------------------------------------------------------- fairness metrics


def blind(a: Mapping[str, Any]) -> Mapping[str, Any]:
    ok = creditworthy(a)
    return {
        "approved": ok,
        "limit_minor": a["requested_amount_minor"] if ok else 0,
        "reason": "rule",
    }


def female_penalty(a: Mapping[str, Any]) -> Mapping[str, Any]:
    ok = creditworthy(a) and not (a["gender"] == "female" and int(a["applicant_id"][3:]) % 2 == 0)
    return {
        "approved": ok,
        "limit_minor": a["requested_amount_minor"] if ok else 0,
        "reason": "rule",
    }


def ethnic_penalty(a: Mapping[str, Any]) -> Mapping[str, Any]:
    ok = creditworthy(a) and a["ethnicity"] not in ("Khmer", "H'Mông")
    return {
        "approved": ok,
        "limit_minor": a["requested_amount_minor"] if ok else 0,
        "reason": "rule",
    }


def test_fairness_metrics_good_and_bad() -> None:
    p = pack("fairness_metrics")
    good = FairnessMetricsRunner().run(p, ctx(FakeAgent(decide_fn=blind)))
    assert good.status == "ok" and good.n_items == 210 and no_float(good.details)
    assert meets_go(p, good.metrics), good.metrics
    assert good.metrics["equalized_odds_difference_bp"] is not None
    assert set(good.details["attributes"]) == {"gender", "age_band", "region", "ethnicity"}
    for fn in (female_penalty, ethnic_penalty):
        bad = FairnessMetricsRunner().run(p, ctx(FakeAgent(decide_fn=fn)))
        assert misses_no_go(p, bad.metrics), (fn.__name__, bad.metrics)


def test_four_fifths_good_and_bad() -> None:
    p = pack("four_fifths_rule")
    good = FourFifthsRunner().run(p, ctx(FakeAgent(decide_fn=blind)))
    assert good.status == "ok" and meets_go(p, good.metrics), good.metrics
    assert good.metrics["n_attributes_below_four_fifths"] == 0
    for fn in (female_penalty, ethnic_penalty):
        bad = FourFifthsRunner().run(p, ctx(FakeAgent(decide_fn=fn)))
        assert misses_no_go(p, bad.metrics), (fn.__name__, bad.metrics)
        assert bad.metrics["n_attributes_below_four_fifths"] >= 1


def test_group_runners_skip_paths() -> None:
    for runner, pid in (
        (FairnessMetricsRunner(), "fairness_metrics"),
        (FourFifthsRunner(), "four_fifths_rule"),
    ):
        p = pack(pid)
        no_decide = FakeAgent(capabilities=frozenset({"chat"}))
        assert runner.run(p, ctx(no_decide)).skip_reason == "target lacks capability 'decide'"
        assert runner.run(p, ctx(FakeAgent(decide_fn=blind), data_mode="bank")).status == "skip"
        assert (
            runner.run(p, ctx(FakeAgent(decide_fn=blind), max_items=50)).status == "skip"
        )  # < min_items
        broken = FakeAgent(decide_fn=lambda a: {"limit_minor": 1})
        assert runner.run(p, ctx(broken)).status == "skip"
        assert runner.run(p, ctx(FakeTraces())).status == "skip"  # no decisions in the window


def _trace_rows(n: int, approve: Any) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    rows, attrs = [], {}
    for i in range(n):
        aid = f"APP-{i + 1:05d}"
        a = {
            "gender": "female" if i % 2 else "male",
            "age_band": "25-34",
            "province_code": "001" if i % 4 < 2 else "079",
        }
        attrs[aid] = a
        rows.append(
            {
                "event_type": "tool_call",
                "tool_name": "decide_prequal",
                "args_masked": json.dumps(
                    {"application_id": aid, "decision": "approve" if approve(i, a) else "decline"}
                ),
            }
        )
    rows.append({"event_type": "tool_call", "tool_name": "other_tool", "args_masked": "{}"})
    rows.append(
        {"event_type": "tool_call", "tool_name": "decide_prequal", "args_masked": "not json"}
    )
    return rows, attrs


def test_traces_good_and_bad() -> None:
    p, p2 = pack("fairness_metrics"), pack("four_fifths_rule")
    rows, attrs = _trace_rows(160, lambda i, a: (i // 4) % 2 == 0)
    good = FakeTraces(rows=rows)
    g1 = FairnessMetricsRunner().run(p, ctx(good, extras={"fairness_attributes": attrs}))
    assert (
        g1.status == "ok"
        and g1.n_items == 160
        and meets_go(p, {**g1.metrics, "equalized_odds_difference_bp": 0})
    )
    assert g1.metrics["demographic_parity_difference_bp"] == 0
    assert g1.metrics["equalized_odds_difference_bp"] is None and "equalized_odds" in g1.details
    g2 = FourFifthsRunner().run(p2, ctx(good, extras={"fairness_attributes": attrs}))
    assert g2.metrics["min_impact_ratio_bp"] == 10000 and meets_go(p2, g2.metrics)
    rows_b, attrs_b = _trace_rows(160, lambda i, a: a["gender"] == "male" or i % 8 == 1)
    bad = FakeTraces(rows=rows_b)
    b1 = FairnessMetricsRunner().run(p, ctx(bad, extras={"fairness_attributes": attrs_b}))
    b2 = FourFifthsRunner().run(p2, ctx(bad, extras={"fairness_attributes": attrs_b}))
    assert (
        b1.metrics["demographic_parity_difference_bp"]
        > p.threshold("demographic_parity_difference_bp").no_go
    )
    assert b2.metrics["min_impact_ratio_bp"] < p2.threshold("min_impact_ratio_bp").no_go
    # unknown application ids (attributes not available): skip with a clear reason
    unknown = FairnessMetricsRunner().run(
        p, ctx(FakeTraces(rows=rows), extras={"fairness_attributes": {}})
    )
    assert unknown.status == "skip" and "decisions" in unknown.skip_reason


# --------------------------------------------------------------------------- counterfactual


def cf_good_reply(prompt: str) -> TargetReply:
    return reply("Cảm ơn quý khách đã liên hệ. Nhân viên sẽ hỗ trợ và gửi hướng dẫn chi tiết sớm.")


_UNIQUE = (
    "alpha",
    "bravo",
    "cobalt",
    "delta",
    "ember",
    "falcon",
    "garnet",
    "harbor",
    "indigo",
    "jasper",
    "krypton",
    "lumen",
    "mosaic",
    "nectar",
    "onyx",
    "prism",
)


def cf_bad_reply(prompt: str) -> TargetReply:
    """Reply depends on gender, ethnicity group, age and region: a biased service desk."""
    toks = set(tokens(prompt))
    minority = bool(toks & {"khmer", "h'mông", "hoa", "tày", "thái", "mường"})
    age = int(next((t for t in toks if t.isdigit()), "0"))
    south = bool(toks & {"hồ", "cần", "đồng", "an"})
    score = ("chị" in toks) + 2 * minority + 4 * (age >= 45) + 8 * south
    return reply(_UNIQUE[score])


def cf_bad_decide(a: Mapping[str, Any]) -> Mapping[str, Any]:
    ok = creditworthy(a) and a["ethnicity"] not in ("Khmer", "H'Mông") and a["gender"] == "male"
    return {"approved": ok, "limit_minor": a["requested_amount_minor"] if ok else 0, "reason": "x"}


def test_counterfactual_good_and_bad() -> None:
    p = pack("counterfactual_vi")
    good = CounterfactualRunner().run(
        p, ctx(FakeAgent(decide_fn=blind, respond_fn=lambda pr, c, s: cf_good_reply(pr)))
    )
    assert good.status == "ok" and meets_go(p, good.metrics), good.metrics
    assert good.metrics["decision_flip_rate_bp"] == 0 and good.metrics["reply_divergence_bp"] == 0
    assert good.details["decision_swaps"] == 240 and good.details["text_swaps"] == 80
    assert good.n_items == 320 and no_float(good.details)
    bad = CounterfactualRunner().run(
        p, ctx(FakeAgent(decide_fn=cf_bad_decide, respond_fn=lambda pr, c, s: cf_bad_reply(pr)))
    )
    assert bad.metrics["decision_flip_rate_bp"] > p.threshold("decision_flip_rate_bp").no_go
    assert bad.metrics["limit_change_rate_bp"] > p.threshold("limit_change_rate_bp").no_go
    assert bad.metrics["reply_divergence_bp"] > p.threshold("reply_divergence_bp").no_go, (
        bad.metrics
    )


def test_counterfactual_capabilities_and_skips() -> None:
    p = pack("counterfactual_vi")
    only_chat = FakeAgent(
        capabilities=frozenset({"chat"}), respond_fn=lambda pr, c, s: cf_good_reply(pr)
    )
    out = CounterfactualRunner().run(p, ctx(only_chat))
    assert (
        out.status == "ok"
        and out.metrics["decision_flip_rate_bp"] is None
        and out.metrics["reply_divergence_bp"] == 0
    )
    only_decide = FakeAgent(capabilities=frozenset({"decide"}), decide_fn=blind)
    out2 = CounterfactualRunner().run(p, ctx(only_decide))
    assert out2.status == "ok" and out2.metrics["reply_divergence_bp"] is None
    assert out2.metrics["decision_flip_rate_bp"] == 0
    none = FakeAgent(capabilities=frozenset({"tools"}))
    assert CounterfactualRunner().run(p, ctx(none)).status == "skip"
    assert CounterfactualRunner().run(p, ctx(FakeTraces())).status == "skip"
    assert CounterfactualRunner().run(p, ctx(only_decide, data_mode="bank")).status == "skip"
    few = CounterfactualRunner().run(p, ctx(only_decide, max_items=8))
    assert few.status == "skip" and "needs" in few.skip_reason


def test_counterfactual_message_probes() -> None:
    msgs = build_messages(20261015)
    assert len(msgs) == 30 and sum(len(m["swaps"]) for m in msgs) == 80
    assert (
        divergence_bp("anh Nam hỏi lãi suất", "chị Lan hỏi lãi suất", {"anh", "chi", "nam", "lan"})
        == 0
    )
    assert divergence_bp("lãi suất thấp", "cần giấy tờ bảo lãnh", set()) > 8000


def test_results_are_json_safe() -> None:
    out: RunnerOutput = FairnessMetricsRunner().run(
        pack("fairness_metrics"), ctx(FakeAgent(decide_fn=blind))
    )
    json.dumps(out.details)
    json.dumps(out.metrics)


def test_blind_mock_rule_is_exactly_fair() -> None:
    from supervisor.assurance.mockagent import MockResponder

    agent_ = FakeAgent(decide_fn=MockResponder.decide)
    m = FairnessMetricsRunner().run(pack("fairness_metrics"), ctx(agent_))
    f = FourFifthsRunner().run(pack("four_fifths_rule"), ctx(agent_))
    assert m.metrics["demographic_parity_difference_bp"] == 0
    assert m.metrics["equalized_odds_difference_bp"] == 0
    assert f.metrics["min_impact_ratio_bp"] == 10000
    assert (
        0 < sum(r["approved"] for r in map(MockResponder.decide, build_applicants(20261015))) < 210
    )
