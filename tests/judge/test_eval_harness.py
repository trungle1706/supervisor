"""Eval harness: four sets, deterministic disjoint held-out split, report end to end."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.llm import jsonschema_lite
from supervisor.config import load_settings
from supervisor.judge.eval import (
    ascii_table,
    build_eval_sets,
    cohen_kappa_bp,
    heldout_digest,
    run_eval,
)
from supervisor.judge.eval.__main__ import main
from supervisor.judge.eval.datasets import INCIDENTS_PATH, INJECTION_PATH, load_jsonl
from supervisor.judge.mockjudge import MockJudgeChat
from supervisor.judge.router import JudgeRouter
from tests.conftest import REPO_ROOT
from tests.judge.conftest import assert_no_floats

GOLDEN = REPO_ROOT / "data" / "golden"
PROMPTS = REPO_ROOT / "src" / "supervisor" / "judge" / "prompts"


@pytest.fixture(scope="module")
def items() -> list[Any]:
    return build_eval_sets()


def mock_router() -> JudgeRouter:
    chats = {
        "t1": MockJudgeChat(1, model_id="mock-judge-t1"),
        "t2": MockJudgeChat(2, model_id="mock-judge-t2"),
    }
    return JudgeRouter.from_settings(load_settings(), chats=chats)


def test_four_sets_from_incidents_and_templates(items) -> None:
    sets = Counter(i.set for i in items)
    assert sets == {"planted": 90, "benign": 100, "injection": 64}
    assert {i.language for i in items} == {"vi", "en"}
    inj = [i for i in items if i.set == "injection"]
    assert {i.technique for i in inj} >= {
        "fake_verdict",
        "canary_exfil",
        "instruction_in_tool_result",
    }
    assert all(i.positive for i in inj) and not any(i.positive for i in items if i.set == "benign")


def test_heldout_split_is_deterministic_stratified_and_disjoint(items) -> None:
    again = build_eval_sets()
    assert [(i.id, i.split) for i in items] == [(i.id, i.split) for i in again]
    assert heldout_digest(items) == heldout_digest(again)
    held = {i.id for i in items if i.split == "heldout"}
    dev = {i.id for i in items if i.split == "dev"}
    assert held and dev and not held & dev
    # About 30 % per stratum (rounded) for the base sets.
    by_stratum: dict[str, list[str]] = {}
    for i in items:
        if i.set != "injection":
            by_stratum.setdefault(i.stratum, []).append(i.split)
    for splits in by_stratum.values():
        assert splits.count("heldout") == (len(splits) * 3000 + 5000) // 10000
    # Injection items never mix splits: base trace and template share the split.
    split_of = {i.id: i.split for i in items}
    for i in items:
        if i.set == "injection":
            assert split_of[i.base_id] == i.split
    # Held-out traces and dev traces share no trace id.
    held_traces = {e.trace_id for i in items if i.split == "heldout" for e in i.events}
    dev_traces = {e.trace_id for i in items if i.split == "dev" for e in i.events}
    assert not held_traces & dev_traces


def test_committed_report_matches_current_split(items) -> None:
    report = json.loads((GOLDEN / "eval_report.json").read_text(encoding="utf-8"))
    assert report["heldout"]["digest"] == heldout_digest(items)
    assert report["mock"] is True
    assert_no_floats(report)


def test_no_heldout_text_in_prompts(items) -> None:
    prompt_text = "\n".join(p.read_text(encoding="utf-8") for p in PROMPTS.glob("*.py")).lower()
    incidents = {c["id"]: c for c in load_jsonl(INCIDENTS_PATH)}
    templates = {t["id"]: t for t in load_jsonl(INJECTION_PATH)}
    for i in items:
        if i.split != "heldout":
            continue
        source = incidents.get(i.id, {}).get("input", {}).get("content")
        if i.set == "injection":
            source = templates[i.id.split("@")[0]]["payload"]
        if source:
            for k in range(0, max(1, len(source) - 40), 40):
                chunk = source[k : k + 40].lower()
                assert chunk not in prompt_text, f"held-out text of {i.id} found in prompts"


def test_eval_end_to_end_with_mockchat(items) -> None:
    subset = [i for i in items if i.id.endswith(("1", "5"))] or items
    report = run_eval(subset, mock_router, runs=2, threshold_bp=5000)
    assert report["mock"] is True and report["runs"] == 2
    assert report["models"]["t1"]["is_mock"] and "mock" in report["models"]["t1"]["model_id"]
    for split in ("heldout", "dev"):
        m = report["metrics"][split]
        for key in ("catch_rate_bp", "false_alarm_bp", "injection_move_rate_bp", "canary_leak_bp"):
            assert key in m
        assert m["stability"]["mean_variance_bp2"] == 0  # MockJudge is deterministic
    assert report["kappa"]["value_bp"] is None
    assert_no_floats(report)
    table = ascii_table(report)
    assert table.isascii() and "[MOCK]" in table


def test_gullible_model_shows_canary_and_lowering(items) -> None:
    subset = [i for i in items if i.set == "injection" or i.id in {x.base_id for x in items}]

    def gullible() -> JudgeRouter:
        chats = {
            "t1": MockJudgeChat(1, model_id="mock-g1", gullible=True),
            "t2": MockJudgeChat(2, model_id="mock-g2", gullible=True),
        }
        return JudgeRouter.from_settings(load_settings(), chats=chats)

    report = run_eval(subset, gullible, runs=1)
    for split in ("heldout", "dev"):
        m = report["metrics"][split]
        assert m["canary_leak_bp"] == 10000  # every leak caught by the canary check
        assert m["injection_detect_bp"] >= 8000  # injection floor keeps them flagged


def test_cli_writes_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "r.json"
    assert main(["--model", "mock", "--runs", "1", "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["mock"] is True and set(report["metrics"]) == {"heldout", "dev"}
    printed = capsys.readouterr().out
    assert printed.isascii() and "[OK]" in printed
    assert main(["--model", "mock", "--runs", "1", "--split", "dev", "--out", str(out)]) == 0
    assert set(json.loads(out.read_text(encoding="utf-8"))["metrics"]) == {"dev"}


def test_cohen_kappa_bp() -> None:
    assert cohen_kappa_bp(["a", "b", "a"], ["a", "b", "a"]) == 10000
    # Classic example: 20 items, p_o = 0.7, p_e = 0.5 -> kappa 0.4.
    a = ["y"] * 10 + ["n"] * 10
    b = ["y"] * 7 + ["n"] * 3 + ["y"] * 3 + ["n"] * 7
    assert cohen_kappa_bp(a, b) == 4000
    assert cohen_kappa_bp([], []) is None


def _resolve_refs(schema: Any, defs: dict[str, Any]) -> Any:
    if isinstance(schema, dict):
        if "$ref" in schema:
            return _resolve_refs(defs[schema["$ref"].rsplit("/", 1)[-1]], defs)
        return {k: _resolve_refs(v, defs) for k, v in schema.items() if k != "$defs"}
    if isinstance(schema, list):
        return [_resolve_refs(x, defs) for x in schema]
    return schema


def test_golden_set_skeleton_matches_schema() -> None:
    schema = json.loads((GOLDEN / "golden_set.schema.json").read_text(encoding="utf-8"))
    flat = _resolve_refs(schema, schema["$defs"])
    rows = load_jsonl(GOLDEN / "golden_set.jsonl")
    assert len(rows) == 10
    assert Counter(r["language"] for r in rows) == {"vi": 5, "en": 5}
    for r in rows:
        assert jsonschema_lite.errors(r, flat) == [], r["id"]
        # Masked: no long digit runs (CCCD, account, phone) outside integer amount fields.
        text = json.dumps(r, ensure_ascii=False)
        text = re.sub(r'amount_minor\\?"?: ?\d+', "", text)
        assert not re.search(r"\d{9,}", text), r["id"]


def test_injection_templates_file() -> None:
    rows = load_jsonl(INJECTION_PATH)
    assert len(rows) == 32 and Counter(r["language"] for r in rows) == {"vi": 16, "en": 16}
    assert sum(r["technique"] == "canary_exfil" for r in rows) >= 5
