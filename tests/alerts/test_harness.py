"""WP21 harness: precision / recall / dedupe / triage on the labelled fixture, with a regression
check against the recorded baseline (tests/fixtures/alerts/baseline.json).

Rubric (bank SOC analyst + detection engineer): every alert carries what the analyst needs to
triage in under two minutes; the planted incidents are all found (recall); nothing else fires
(precision); a repeat never makes a second alert inside the dedupe window (no flood)."""

from __future__ import annotations

import importlib.util
import json
import random

import pytest

from supervisor.alerts import evaluate, load_rules, read_jsonl
from supervisor.alerts import harness as H
from supervisor.alerts.service import ALERT_FIELDS
from supervisor.config import REPO_ROOT
from supervisor.core.schema import load_model

FIX = REPO_ROOT / "tests" / "fixtures" / "alerts"
RULES = REPO_ROOT / "config" / "alerts.yaml"
SPLITS = ("dev", "heldout")


def _generator():
    spec = importlib.util.spec_from_file_location("alerts_fixture_generate", FIX / "generate.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_committed_fixtures_are_what_the_generator_writes() -> None:
    gen = _generator()
    for split in SPLITS:
        for name, text in gen.render(split).items():
            assert (FIX / name).read_text(encoding="utf-8") == text, name


def test_fixture_shape_and_provenance() -> None:
    for split in SPLITS:
        sigs = read_jsonl(FIX / f"{split}.signals.jsonl")
        assert sum(1 for s in sigs if s.kind == "gate_decision") == 500
        exp = json.loads((FIX / f"{split}.expected.json").read_text("utf-8"))
        assert len(exp["incidents"]) == 6 and exp["n_gate_decisions"] == 500
        labels = {
            json.loads(line)["label"]
            for line in (FIX / f"{split}.signals.jsonl").read_text("utf-8").splitlines()
        }
        assert labels - {None} == {f"INC-{i}" for i in range(1, 7)}
    assert "synthetic" in (FIX / "README.md").read_text("utf-8").lower()


@pytest.mark.parametrize("split", SPLITS)
def test_each_rule_fires_exactly_for_its_incident(split: str) -> None:
    rs = load_rules(RULES)
    out = H.run_split(FIX, split, rs)
    m = out["metrics"]
    assert m["precision_bp"] == 10000 and m["recall_bp"] == 10000
    assert m["false_positive"] == 0 and m["false_negative"] == 0
    assert m["true_positive"] == m["alerts_expected"] == 8
    for rid, c in out["by_rule"].items():
        assert c["fired"] == c["expected"] and c["false_positive"] == 0 and c["missed"] == 0, rid
    assert out["failure_taxonomy"]["false_negative"] == []
    assert out["failure_taxonomy"]["false_positive"] == []
    assert set(out["verdicts"].values()) == {"GO"}


@pytest.mark.parametrize("split", SPLITS)
def test_dedupe_collapses_repeats_exactly(split: str) -> None:
    rs = load_rules(RULES)
    sigs = read_jsonl(FIX / f"{split}.signals.jsonl")
    res = evaluate(rs, sigs)
    by_rule = {f.rule.id: f for f in res.fired}
    assert by_rule["AL-BLOCK-BURST"].suppressed_count == 3
    assert by_rule["AL-INGRESS-REJECT-BURST"].suppressed_count == 4
    assert by_rule["AL-INGRESS-REJECT-AGENT"].suppressed_count == 3
    assert by_rule["AL-CHAIN-VERIFY-FAIL"].suppressed_count == 1
    assert by_rule["AL-JOB-FAILURE"].suppressed_count == 1
    m = H.run_split(FIX, split, rs)["metrics"]
    assert m["dedupe_exact_bp"] == 10000 and m["suppressed_repeats"] == 12
    # no flood: about 100 matching signals became 8 alerts
    assert m["matching_signals"] // m["alerts_fired"] >= 10


@pytest.mark.parametrize("split", SPLITS)
def test_result_does_not_depend_on_input_order(split: str) -> None:
    rs = load_rules(RULES)
    sigs = read_jsonl(FIX / f"{split}.signals.jsonl")
    base = [(f.alert_id, f.window_count, f.suppressed_count) for f in evaluate(rs, sigs).fired]
    shuffled = list(sigs)
    random.Random(7).shuffle(shuffled)
    again = [(f.alert_id, f.window_count, f.suppressed_count) for f in evaluate(rs, shuffled).fired]
    assert sorted(base) == sorted(again)


def test_every_alert_carries_the_triage_fields() -> None:
    rs = load_rules(RULES)
    for split in SPLITS:
        res = evaluate(rs, read_jsonl(FIX / f"{split}.signals.jsonl"))
        for f in res.fired:
            assert H.triage_missing(f) == [], (f.rule.id, H.triage_missing(f))
            if f.rule.source in ("gate_decision", "gate_state_change"):
                assert f.agent_id and f.trigger.lane and f.trigger.entry_hash


def test_a_threshold_that_is_too_low_is_caught_as_false_positives() -> None:
    """The harness must be able to fail: a block-burst threshold of 4 trips on the near miss."""
    text = RULES.read_text("utf-8").replace("threshold: 5", "threshold: 4", 1)
    import yaml

    from supervisor.alerts import parse_rules

    rs = parse_rules(yaml.safe_load(text))
    out = H.run_split(FIX, "dev", rs)
    assert out["metrics"]["false_positive"] >= 1
    assert out["verdicts"]["precision"] == "NO-GO"
    assert any(x["rule_id"] == "AL-BLOCK-BURST" for x in out["failure_taxonomy"]["false_positive"])


def test_a_threshold_that_is_too_high_is_caught_as_a_miss() -> None:
    text = RULES.read_text("utf-8").replace("threshold: 5", "threshold: 9", 1)
    import yaml

    from supervisor.alerts import parse_rules

    out = H.run_split(FIX, "dev", parse_rules(yaml.safe_load(text)))
    assert out["metrics"]["false_negative"] == 1 and out["verdicts"]["recall"] == "NO-GO"


@pytest.mark.parametrize("split", SPLITS)
def test_no_regression_against_the_recorded_baseline(split: str) -> None:
    base = json.loads((FIX / "baseline.json").read_text("utf-8"))["results"][split]["metrics"]
    now = H.run_split(FIX, split, load_rules(RULES))["metrics"]
    for k in ("precision_bp", "recall_bp", "dedupe_exact_bp", "triage_complete_bp"):
        assert now[k] >= base[k], f"{split}: {k} dropped from {base[k]} to {now[k]}"
    assert now["false_positive"] <= base["false_positive"]
    assert now["false_negative"] <= base["false_negative"]
    assert now["alerts_fired"] <= base["alerts_fired"], "more alerts than the baseline: flood?"
    assert now["false_alert_rate_upper_bp"] <= base["false_alert_rate_upper_bp"]


def test_wilson_interval_is_sane() -> None:
    assert H.wilson_bp(7, 7) == (6456, 10000)
    lo, hi = H.wilson_bp(0, 570)
    assert lo == 0 and 0 < hi < 100
    assert H.wilson_bp(0, 0) == (0, 10000)


def test_stable_field_names() -> None:
    """The analyst's field names do not drift: alert columns, the SIEM attrs and the triage text."""
    cols = list(load_model().table("alert").column_names)
    assert set(cols) - set(ALERT_FIELDS) == {"row_version", "updated_at"}
    assert set(ALERT_FIELDS) <= set(cols)
    from supervisor.adapters.integrations.siem import event_from_alert
    from supervisor.alerts.service import triage_text

    row = {
        "alert_id": "x" * 32, "ts": "2026-10-19T08:00:00.000000Z", "dedupe_key": "R:a",
        "rule_id": "AL-X", "severity": "high", "agent_id": "a", "case_id": None,
        "chain_lane": "a", "chain_seq": 3, "entry_hash": "ab" * 32, "window_s": 600,
        "window_count": 5, "threshold": 5, "suppressed_count": 0, "title": "t", "group_value": "a",
        "first_ts": "2026-10-19T07:55:00.000000Z", "last_ts": "2026-10-19T08:00:00.000000Z",
    }  # fmt: skip
    ev = event_from_alert(row)
    assert sorted(ev.attrs or {}) == [
        "alert_id", "correlation_id", "dedupe_key", "severity_label", "suppressed_count",
        "threshold", "window_count", "window_s",
    ]  # fmt: skip
    subject, body = triage_text(row)
    keys = [line.split(":", 1)[0] for line in body.splitlines()]
    assert keys == [
        "alert_id", "rule_id", "severity", "title", "agent_id", "group", "window", "first_ts",
        "last_ts", "suppressed_repeats", "case", "chain", "entry_hash", "console",
    ]  # fmt: skip
    assert subject.startswith("[high] AL-X a")
    assert len(body.splitlines()) <= 14  # fits one screen: triage in under two minutes
