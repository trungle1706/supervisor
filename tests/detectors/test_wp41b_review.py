"""WP41b review probes: D31 (a cut argument fails closed for any detector set) and D32 (an
over-budget pii_export argument never reaches the tool unmasked, in any configuration the loader
accepts)."""

from __future__ import annotations

import json
from typing import Any

import pytest
import yaml

from supervisor.core.detectors import DetectorRegistry, Finding
from supervisor.gateway.detector_gate import FAILED_RULE
from supervisor.gateway.policy import Policy, load_policy_texts
from supervisor.gateway.redact import over_budget
from tests.conftest import REPO_ROOT
from tests.detectors.conftest import GatewayFactory, make_gate
from tests.detectors.fakes import FakeDetector
from tests.detectors.test_wp41b import CLEAN, HUGE

PAN = "001203004567"


def _doc() -> dict[str, Any]:
    return yaml.safe_load((REPO_ROOT / "policies" / "baseline.yaml").read_text(encoding="utf-8"))


def _policy(doc: dict[str, Any]) -> Policy:
    return load_policy_texts([("p.yaml", yaml.safe_dump(doc))])


def _cfg(body: str, limits: str = "") -> str:
    return "version: 1\n" + (f"limits: {limits}\n" if limits else "") + "detectors:\n" + body


def _read(gw: Any) -> None:
    gw.check("credit_prequal", "1", "fetch_application", {"application_id": "A-1"})


def _quiet(slug: str) -> FakeDetector:
    def fn(payload: Any, settings: Any, direction: str) -> list[Finding]:
        return []

    return FakeDetector(slug, fn, sides=("input", "output"))


# ---------------------------------------------------------------------------- D31


ONLY_REGEX = _cfg(
    "  dlp_vn: {enabled: false}\n  injection_regex: {enabled: true, fail_closed: true}\n"
)
DLP_OPEN = _cfg(
    "  dlp_vn: {enabled: true, fail_closed: false}\n"
    "  injection_regex: {enabled: true, fail_closed: true}\n"
)


@pytest.mark.parametrize("tool", ["decide_prequal", "fetch_application"])
@pytest.mark.parametrize("cfg", [ONLY_REGEX, DLP_OPEN], ids=["only_regex", "dlp_open"])
def test_cut_argument_fails_closed_for_other_detector_sets(
    make_gateway: GatewayFactory, masker: Any, cfg: str, tool: str
) -> None:
    gw = make_gateway(gate=make_gate(masker, config_text=cfg))
    _read(gw)
    r = gw.check("credit_prequal", "1", tool, {"application_id": "A-1", "note": CLEAN})
    assert r["allow"] is False and r["rule_id"] == FAILED_RULE, r["reason"]


def test_cut_argument_with_a_classifier_only_set(make_gateway: GatewayFactory, masker: Any) -> None:
    """The classifier may not fail closed (R1): with nothing else enabled the cut stays coverage,
    and the answer says so (no false GO)."""
    cfg = _cfg("  injection_classifier: {enabled: true, fail_closed: false}\n")
    reg = DetectorRegistry([_quiet("injection_classifier")])
    gw = make_gateway(gate=make_gate(masker, registry=reg, config_text=cfg))
    _read(gw)
    r = gw.check("credit_prequal", "1", "decide_prequal", {"application_id": "A-1", "n": CLEAN})
    cut = [n for n in r["coverage"]["not_inspected"] if n["reason"] == "payload_too_large"]
    assert cut  # the gap is visible in the answer
    assert any(n["reason"] == "payload_too_large" for n in r["not_executed"])


def test_cut_argument_with_every_detector_disabled_for_the_agent(
    make_gateway: GatewayFactory,
) -> None:
    doc = _doc()
    doc["agents"]["credit_prequal"]["detectors"] = {"disable": ["dlp_vn", "injection_regex"]}
    gw = make_gateway(policy=_policy(doc))
    _read(gw)
    r = gw.check("credit_prequal", "1", "decide_prequal", {"application_id": "A-1", "n": CLEAN})
    # no detector runs, so nothing was cut by a budget: no false block, and no detector listed
    assert r["detectors"] == []


def test_output_direction_is_not_affected(make_gateway: GatewayFactory) -> None:
    gw = make_gateway()
    _read(gw)
    r = gw.check(
        "credit_prequal",
        "1",
        "decide_prequal",
        {"application_id": "A-1"},
        {"direction": "output", "output": CLEAN},
    )
    assert r["rule_id"] != FAILED_RULE


# ---------------------------------------------------------------------------- D32 gap


GAP_CONFIGS = {
    "dlp_open_regex_closed": DLP_OPEN,
    "all_open": _cfg(
        "  dlp_vn: {enabled: true, fail_closed: false}\n"
        "  injection_regex: {enabled: true, fail_closed: false}\n"
    ),
    "pii_export_not_closed": _cfg(
        "  dlp_vn: {enabled: true, fail_closed: true}\n", "{fail_closed_risk_classes: [money]}"
    ),
}


@pytest.mark.parametrize("cfg", list(GAP_CONFIGS.values()), ids=list(GAP_CONFIGS))
def test_big_pii_export_argument_is_never_sent_unmasked(
    make_gateway: GatewayFactory, masker: Any, cfg: str
) -> None:
    gw = make_gateway(gate=make_gate(masker, config_text=cfg), masker=masker, inline_redaction=True)
    r = gw.check("credit_prequal", "1", "fetch_application", {"customer_id": "C-1", "n": HUGE})
    if r["allow"]:
        assert r["transformed_args"] is not None and PAN not in r["transformed_args"]["n"]
    else:
        assert r.get("transformed_args") is None
    assert PAN not in json.dumps(r, ensure_ascii=False)


def test_big_pii_export_argument_with_detectors_disabled_for_the_agent(
    make_gateway: GatewayFactory, masker: Any
) -> None:
    doc = _doc()
    doc["agents"]["credit_prequal"]["detectors"] = {"disable": ["dlp_vn", "injection_regex"]}
    gw = make_gateway(policy=_policy(doc), masker=masker, inline_redaction=True)
    r = gw.check("credit_prequal", "1", "fetch_application", {"customer_id": "C-1", "n": HUGE})
    if r["allow"]:
        assert r["transformed_args"] is not None and PAN not in r["transformed_args"]["n"]


def test_observe_mode_never_lets_a_big_pii_export_argument_out_unmasked(
    make_gateway: GatewayFactory, masker: Any
) -> None:
    doc = _doc()
    doc["agents"]["credit_prequal"]["mode"] = "observe"
    doc["agents"]["credit_prequal"]["observe_approvals"] = ["risk.lead", "compliance.officer"]
    gw = make_gateway(policy=_policy(doc), masker=masker, inline_redaction=True)
    r = gw.check("credit_prequal", "1", "fetch_application", {"customer_id": "C-1", "n": HUGE})
    assert r["allow"] is False and r["rule_id"] == FAILED_RULE  # never lifted on pii_export
    assert PAN not in json.dumps(r, ensure_ascii=False)


# ---------------------------------------------------------------------------- over_budget


@pytest.mark.parametrize(
    ("value", "limit", "want"),
    [
        ("x" * 101, 100, True),  # a bare string
        ("x" * 100, 100, False),
        ({"a": {"b": {"c": "x" * 101}}}, 100, True),  # nested dict
        (["x" * 50, "y" * 51], 100, True),  # list of strings
        (("x" * 50, "y" * 50), 100, False),  # tuple
        ({"a": b"x" * 500}, 100, False),  # bytes are not text the masker reads
        ({"a": bytearray(500)}, 100, False),
        ({"a": "\ud800" * 101}, 100, True),  # not valid UTF-8 (lone surrogate)
        ({"a": "ạ" * 34}, 100, True),  # 3 bytes per character: 102 bytes
        ({"a": "ạ" * 33}, 100, False),  # 99 bytes
    ],
)
def test_over_budget_on_every_input_shape(value: Any, limit: int, want: bool) -> None:
    assert over_budget(value, limit) is want


def test_over_budget_does_not_walk_past_the_limit() -> None:
    seen: list[int] = []

    class Spy(dict):  # type: ignore[type-arg]
        def values(self):  # type: ignore[no-untyped-def]
            for i, v in enumerate(super().values()):
                seen.append(i)
                yield v

    big = Spy({f"k{i}": "x" * 100 for i in range(10_000)})
    assert over_budget(big, 250) is True
    assert len(seen) == 3  # stops at the third leaf


# ---------------------------------------------------------------------------- WP24b unchanged


def test_dlp_vn_off_masks_the_full_text_byte_for_byte_as_wp24b(
    make_gateway: GatewayFactory, masker: Any
) -> None:
    from supervisor.gateway.redact import redact_args

    args = {"customer_id": "C-1", "n": HUGE}
    want, n = redact_args(masker, args)
    gw = make_gateway(
        gate=make_gate(masker, config_text=ONLY_REGEX),
        masker=masker,
        inline_redaction=True,
        timeout_s=30.0,  # not a timing test (slow CI runner)
    )
    r = gw.check("credit_prequal", "1", "fetch_application", args)
    # dlp_vn off: nothing limits the masker; the call is still refused by the cut (D31) and the
    # masker output, had it been allowed, is the WP24b one
    assert r["rule_id"] == FAILED_RULE
    assert gw._pre_redact("fetch_application", args, {"declared_risk_class": "pii_export"}) == (
        want,
        n,
    )
