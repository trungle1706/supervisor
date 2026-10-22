"""WP37 detector contract: settings schema, Finding, registry, status precedence."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.core import detectors as D
from supervisor.core.detectors import (
    DetectorRegistry,
    DetectorSetting,
    Finding,
    RunConfig,
    derive_status,
)
from supervisor.detectors import build_registry
from tests.detectors.fakes import SETTING_SCHEMA, FakeDetector, boom, hint, slow

OK = {"must": "yes"}


def _cfg(*slugs: str, **settings: Any) -> RunConfig:
    return RunConfig(
        detectors={
            s: DetectorSetting(True, {"preset": "balanced", **settings.get(s, {})}) for s in slugs
        }
    )


# ---------------------------------------------------------------------------- settings schema


def test_schema_defaults_and_valid_values() -> None:
    clean, errors = SETTING_SCHEMA.validate({"must": "yes", "limit": 7, "tags": ["p"]})
    assert errors == []
    assert clean["limit"] == 7 and clean["mode"] == "a" and clean["nested"] == {"depth": 1}


@pytest.mark.parametrize(
    ("values", "fragment"),
    [
        ({}, "must: required"),
        ({**OK, "mode": "z"}, "mode: must be one of"),
        ({**OK, "limit": 11}, "limit: above 10"),
        ({**OK, "limit": True}, "limit: expected integer"),  # a bool is not an integer
        ({**OK, "on": "yes"}, "on: expected boolean"),
        ({**OK, "ratio": 9}, "ratio: above 5"),
        ({**OK, "name": "toolong"}, "name: longer than"),
        ({**OK, "tags": ["z"]}, "tags[0]: must be one of"),
        ({**OK, "tags": "p"}, "tags: expected array"),
        ({**OK, "nested": {"depth": 9}}, "nested.depth: above 3"),
        ({**OK, "nested": {"nope": 1}}, "nested.nope: unknown setting"),
        ({**OK, "extra": 1}, "extra: unknown setting"),
    ],
)
def test_schema_rejects(values: dict[str, Any], fragment: str) -> None:
    _, errors = SETTING_SCHEMA.validate(values)
    assert any(fragment in e for e in errors), errors


def test_schema_serialises_and_covers_every_field_type() -> None:
    doc = SETTING_SCHEMA.to_dict()
    assert {f["type"] for f in doc} == set(D.FIELD_TYPES)
    json.dumps(doc)  # plain JSON


# ---------------------------------------------------------------------------- finding


def test_finding_guards() -> None:
    with pytest.raises(ValueError, match="not_executed_reason"):
        Finding("a", "a@1", "c", not_executed_reason="nope")
    with pytest.raises(ValueError, match="action_hint"):
        Finding("a", "a@1", "c", action_hint="delete")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="score_bp"):
        Finding("a", "a@1", "c", score_bp=1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="score_bp"):
        Finding("a", "a@1", "c", score_bp=10_001)


def test_not_executed_reasons_are_the_fixed_list() -> None:
    assert set(D.NOT_EXECUTED_REASONS) == {
        "execution_failed",
        "invalid_config",
        "payload_too_large",
        "content_uninspectable",
        "not_applicable_for_direction",
        "timed_out",
        "budget_exhausted",  # WP-D4
    }
    assert "not_applicable_for_direction" not in D.FAILURE_REASONS


def test_finding_to_dict_and_digest_hold_no_transformed_payload() -> None:
    f = Finding(
        "a",
        "a@1",
        "c",
        score_bp=9000,
        threshold_bp=5000,
        entities=(D.Entity("PHONE", "<PHONE:abc123>"),),
        fragments=(D.Fragment("args", "$.x", 1, 15, "<PHONE:abc123>"),),
        transformed_payload={"args": {"x": "<PHONE:abc123>"}},
    )
    doc = f.to_dict()
    assert "transformed_payload" not in doc and doc["score_bp"] == 9000
    assert len(f.digest()) == 64
    # the digest does not change with the order of entities and holds no text
    assert "abc123" not in f.digest()


def test_fired_needs_threshold_unless_it_transformed() -> None:
    assert not Finding("a", "a@1", "c", score_bp=4000, threshold_bp=5000).fired
    assert Finding("a", "a@1", "c", score_bp=5000, threshold_bp=5000).fired
    assert Finding("a", "a@1", "c", score_bp=100, threshold_bp=5000, action_hint="transform").fired
    assert not D.not_executed("a", "a@1", "timed_out").fired


# ---------------------------------------------------------------------------- registry


def test_registry_rejects_bad_detectors() -> None:
    reg = DetectorRegistry([FakeDetector("one")])
    with pytest.raises(ValueError, match="twice"):
        reg.register(FakeDetector("one"))
    with pytest.raises(ValueError, match="sides"):
        reg.register(FakeDetector("two", sides=("sideways",)))
    bad = FakeDetector("three")
    bad.presets = {"strict": 1}
    with pytest.raises(ValueError, match="balanced"):
        reg.register(bad)


def test_catalogue_comes_from_code(masker: VnRegexMasker) -> None:
    cat = build_registry(masker).catalogue()
    slugs = [c["slug"] for c in cat]
    assert slugs == [
        "dlp_vn",
        "injection_regex",
        "injection_classifier",
        "judge_advisory",
        "judge_moderation",  # WP-D4
        "guard_model",  # WP-D3
        "document_intake",  # WP-D1
    ]
    for c in cat:
        assert set(c) >= {"slug", "name", "category", "sides", "protocols", "presets"}
        keys = [f["key"] for f in c["settings_schema"]]
        assert keys[:2] == ["preset", "threshold_bp"]  # the common fields come first
        assert c["detector_id"] == f"{c['slug']}@{c['version']}"
    dlp = next(c for c in cat if c["slug"] == "dlp_vn")
    assert dlp["sides"] == ["input", "output"]
    json.dumps(cat)


def test_registry_validates_settings(masker: VnRegexMasker) -> None:
    reg = build_registry(masker)
    clean, errs = reg.validate_settings("dlp_vn", {"mode": "report", "preset": "strict"})
    assert errs == [] and clean["mode"] == "report" and clean["preset"] == "strict"
    _, errs = reg.validate_settings("dlp_vn", {"preset": "extreme"})
    assert errs and "preset" in errs[0]
    _, errs = reg.validate_settings("dlp_vn", {"threshold_bp": 10_001})
    assert errs and "threshold_bp" in errs[0]


def test_run_only_the_detectors_whose_sides_include_the_direction() -> None:
    inp, out = (
        FakeDetector("in_only", sides=("input",)),
        FakeDetector("out_only", sides=("output",)),
    )
    reg = DetectorRegistry([inp, out])
    res = reg.run({"args": {"a": "x"}, "meta": {}}, "input", _cfg("in_only", "out_only"))
    assert (inp.calls, out.calls) == (1, 0)
    assert [(f.detector_slug, f.not_executed_reason) for f in res.not_executed] == [
        ("out_only", "not_applicable_for_direction")
    ]
    res = reg.run({"output": "x", "meta": {}}, "output", _cfg("in_only", "out_only"))
    assert (inp.calls, out.calls) == (1, 1)


def test_other_protocol_is_skipped_silently() -> None:
    d = FakeDetector("mcp_only", protocols=("mcp",))
    res = DetectorRegistry([d]).run({"args": {}, "meta": {}}, "input", _cfg("mcp_only"))
    assert d.calls == 0 and res.not_executed == []
    DetectorRegistry([d]).run({"args": {}, "meta": {}}, "input", _cfg("mcp_only"), protocol="mcp")
    assert d.calls == 1


def test_failures_become_not_executed_and_never_raise() -> None:
    reg = DetectorRegistry([FakeDetector("bad", boom), FakeDetector("good")])
    res = reg.run({"args": {"a": "x"}, "meta": {}}, "input", _cfg("bad", "good"))
    assert res.evaluated == ["good"]
    (ne,) = res.not_executed
    assert ne.not_executed_reason == "execution_failed" and ne.detail == "RuntimeError"
    assert "0912345678" not in json.dumps(ne.to_dict())  # the message is never copied


def test_invalid_config_and_timeout() -> None:
    reg = DetectorRegistry(
        [FakeDetector("cfg", schema=SETTING_SCHEMA), FakeDetector("slw", slow(30))]
    )
    cfg = RunConfig(
        {"cfg": DetectorSetting(True, {"preset": "balanced"}), "slw": DetectorSetting()},
        timeout_ms=10,
    )
    res = reg.run({"args": {"a": "x"}, "meta": {}}, "input", cfg)
    reasons = {f.detector_slug: f.not_executed_reason for f in res.not_executed}
    assert reasons == {"cfg": "invalid_config", "slw": "timed_out"}


def test_payload_too_large_and_uninspectable_coverage() -> None:
    reg = DetectorRegistry([FakeDetector("one")])
    big = {"args": {"a": "x" * 50}, "meta": {}}
    cfg = RunConfig({"one": DetectorSetting(True, {"preset": "balanced"})}, max_payload_chars=10)
    res = reg.run(big, "input", cfg)
    assert [f.not_executed_reason for f in res.not_executed] == ["payload_too_large"]
    assert {"part": "args", "reason": "payload_too_large"} in res.coverage["not_inspected"]
    assert res.coverage["inspected"] == []
    blob = {"args": {"a": "hi", "b": b"\x00\x01"}, "meta": {}}
    res = reg.run(blob, "input", _cfg("one"))
    assert any(n["reason"] == "content_uninspectable" for n in res.coverage["not_inspected"])
    assert any(f.not_executed_reason == "content_uninspectable" for f in res.not_executed)


def test_coverage_lists_every_part_with_a_reason() -> None:
    reg = DetectorRegistry([FakeDetector("one")])
    res = reg.run({"args": {"a": "x"}, "meta": {}}, "input", _cfg("one"))
    assert res.coverage["inspected"] == ["args"]
    assert res.coverage["not_inspected"] == [
        {"part": "tool_results", "reason": "not_provided"},
        {"part": "output", "reason": "not_applicable_for_direction"},
    ]
    res = reg.run({"args": {"a": "x"}, "tool_results": ["r"], "meta": {}}, "input", _cfg("one"))
    assert res.coverage["inspected"] == ["args", "tool_results"]
    res = reg.run({"output": "o", "meta": {}}, "output", _cfg("one"))
    assert res.coverage["inspected"] == ["output"]
    assert {n["part"] for n in res.coverage["not_inspected"]} == {"args", "tool_results"}


def test_subthreshold_findings_are_dropped_and_hints_pass_through() -> None:
    def low(p: Any, s: Any, d: str) -> list[Finding]:
        return [Finding("low", "low@1", "c", score_bp=100, threshold_bp=5000)]

    reg = DetectorRegistry([FakeDetector("low", low), hint("block")])
    res = reg.run({"args": {"a": "x"}, "meta": {}}, "input", _cfg("low", "hinter"))
    assert [f.code for f in res.findings] == ["hint.block"]  # the hint is kept for the record


def test_money_failure_is_fail_closed_only_where_configured() -> None:
    reg = DetectorRegistry([FakeDetector("bad", boom)])
    payload = {"args": {"a": "x"}, "meta": {}}
    cfg = RunConfig({"bad": DetectorSetting(True, {"preset": "balanced"}, fail_closed=True)})
    assert reg.run(payload, "input", cfg, risk_class="money").failed_closed
    assert reg.run(payload, "input", cfg, risk_class="credit").failed_closed
    assert reg.run(payload, "input", cfg, risk_class="pii_export").failed_closed
    assert not reg.run(payload, "input", cfg, risk_class="read_only").failed_closed
    assert not reg.run(payload, "input", cfg, risk_class=None).failed_closed
    soft = RunConfig({"bad": DetectorSetting(True, {"preset": "balanced"}, fail_closed=False)})
    assert not reg.run(payload, "input", soft, risk_class="money").failed_closed


def test_dict_keys_that_could_hold_personal_data_are_not_put_in_paths() -> None:
    leaves = list(D.walk_leaves("args", {"Nguyen Van Thu": "x", "ok_key": ["y"]}))
    assert [leaf.path for leaf in leaves] == ["$.*", "$.ok_key[0]"]


# ---------------------------------------------------------------------------- precedence


ORDER = ["allow", "report", "transform", "pause", "block"]


def test_precedence_is_block_pause_transform_report_allow() -> None:
    assert D.PRECEDENCE == tuple(ORDER)
    rep = [Finding("a", "a@1", "c", score_bp=9000, threshold_bp=5000)]
    base = {"allow": True, "action": "allow", "findings": [], "has_transform": False}
    assert derive_status(**base) == "allow"
    assert derive_status(**{**base, "findings": rep}) == "report"
    assert derive_status(**{**base, "action": "alert"}) == "report"
    assert derive_status(**{**base, "action": "log"}) == "report"
    assert derive_status(**{**base, "findings": rep, "has_transform": True}) == "transform"
    denied = {"allow": False, "findings": rep, "has_transform": True}
    assert derive_status(action="pause", **denied) == "pause"
    assert derive_status(action="block", **denied) == "block"
    # a block rule beats a pause rule even when the pause rule decided first
    assert derive_status(action="pause", matched_actions=["pause", "block"], **denied) == "block"


def test_skip_only_wins_over_an_allow() -> None:
    base = {"findings": [], "has_transform": False, "skipped": True}
    assert derive_status(allow=True, action="allow", **base) == "skip"
    assert derive_status(allow=True, action="alert", **base) == "skip"
    assert derive_status(allow=False, action="block", **base) == "block"
    assert derive_status(allow=False, action="pause", **base) == "pause"


def test_a_finding_hint_of_pause_or_block_never_raises_the_status() -> None:
    for action in ("pause", "block"):
        res = DetectorRegistry([hint(action)]).run(
            {"args": {"a": "x"}, "meta": {}}, "input", _cfg("hinter")
        )
        status = derive_status(
            allow=True, action="allow", findings=res.findings, has_transform=False
        )
        assert status == "report"


# ---------------------------------------------------------------------------- frozen presets


def test_presets_are_frozen_per_version(masker: VnRegexMasker) -> None:
    """Change a preset number and this fails; bump the detector version and update the pair."""
    reg = build_registry(masker)
    frozen = {
        "dlp_vn": {"strict": 5000, "balanced": 8000, "lenient": 9500},
        "injection_regex": {"strict": 5000, "balanced": 7000, "lenient": 8500},
        "judge_advisory": {"strict": 3000, "balanced": 5000, "lenient": 7000},
        "judge_moderation": {"strict": 3000, "balanced": 5000, "lenient": 7000},  # WP-D4
    }
    for slug, presets in frozen.items():
        det = reg.get(slug)
        assert det.version == "1.0.0", f"{slug}: version bumped, re-freeze the presets"
        assert dict(det.presets) == presets, f"{slug}: presets changed without a version bump"
        assert all(0 <= v <= 10_000 and type(v) is int for v in det.presets.values())
        assert det.presets["strict"] < det.presets["balanced"] < det.presets["lenient"]


# ---------------------------------------------------------------------------- architecture


def test_core_detectors_has_no_io_imports() -> None:
    tree = ast.parse(Path(D.__file__).read_text(encoding="utf-8"))
    names = {
        n.names[0].name.split(".")[0]
        if isinstance(n, ast.Import)
        else (n.module or "").split(".")[0]
        for n in ast.walk(tree)
        if isinstance(n, ast.Import | ast.ImportFrom)
    }
    assert not names & {"socket", "httpx", "requests", "urllib", "sqlite3", "subprocess", "openai"}
