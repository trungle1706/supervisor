"""WP-D2: dlp_vn secrets group, custom rules, mask tokens, GATE-SECRET-IN-ARGS.

Every planted secret is built at run time (split literals), so this file does not trip
tests/test_no_secrets.py. The checks that matter most: a secret value never appears in a finding,
a record or the transformed payload; the default is report; bad settings fail at load.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
import yaml

from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.core.errors import ConfigError
from supervisor.core.secret_patterns import KINDS, PATTERNS
from supervisor.detectors import build_registry, dlp_extras
from supervisor.detectors.config import ResolvedDetectors, parse_config
from supervisor.detectors.dlp_extras import Extras, extras_problems, regex_problems
from supervisor.detectors.dlp_vn import DlpVnDetector
from supervisor.gateway.engine import Gateway
from supervisor.onboard import scrub
from tests.conftest import REPO_ROOT
from tests.detectors.conftest import GatewayFactory, make_gate
from tests.gateway.conftest import MemoryEvidence

AWS = "AK" + "IA" + "QWERTYUIOP123456"
GH = "gh" + "p_" + "A1b2C3d4E5" * 3 + "xyz123"
HF = "h" + "f_" + "AbCdEfGhIj" * 3 + "KLMN"
STRIPE = "s" + "k_live_" + "AbCdEfGhIj" * 2 + "KLMN"
ANT = "s" + "k-ant-" + "api03-" + "AbCdEfGhIj" * 3
OAI = "s" + "k-proj-" + "AbCdEfGhIj" * 3
PW = "Hunter2" + "Pass9"
META = {"tool_name": "add_payee", "risk_class": "pii_export"}
ON = {"secrets": {"enabled": True, "action": "report"}}


@pytest.fixture
def det() -> DlpVnDetector:
    return DlpVnDetector(VnRegexMasker(b"d2-key", "t"))


def run(det: DlpVnDetector, args: Any, settings: dict[str, Any], part: str = "args") -> list[Any]:
    payload = {part: args, "meta": META}
    return det.evaluate(
        payload,
        {**det.settings_schema.defaults(), "preset": "balanced", **settings},
        "output" if part == "output" else "input",
    )


def blob(found: list[Any]) -> str:
    return json.dumps(
        [[f.to_dict() for f in found], [f.transformed_payload for f in found]], default=str
    )


# ---------------------------------------------------------------------------- one pattern source


def test_scrubber_and_dlp_share_one_pattern_table() -> None:
    from supervisor.core import secret_patterns

    assert scrub.redact is secret_patterns.redact
    assert {k for k, _, _ in PATTERNS} == set(KINDS)
    assert {"gitlab_token", "huggingface_token", "stripe_key", "sendgrid_key", "npm_token"} <= set(
        KINDS
    )


@pytest.mark.parametrize(
    ("kind", "text"),
    [
        ("gitlab_token", "gl" + "pat-" + "AbCdEfGhIj1234567890"),
        ("huggingface_token", HF),
        ("stripe_key", STRIPE),
        ("sendgrid_key", "S" + "G." + "A" * 22 + "." + "B" * 43),
        ("npm_token", "np" + "m_" + "A1" * 18),
        ("vault_token", "h" + "vs." + "A1b2" * 7),
    ],
)
def test_the_scrubber_gets_the_new_kinds_too(kind: str, text: str) -> None:
    res = scrub.scrub_text(f"value {text} end")
    assert res.counts == {kind: 1} and text not in res.text


# ---------------------------------------------------------------------------- off by default


def test_secrets_are_off_by_default_and_the_value_passes_through(det: DlpVnDetector) -> None:
    assert not [f for f in run(det, {"n": f"key {AWS}"}, {}) if f.code.startswith("secret.")]
    off = run(det, {"n": f"key {AWS}"}, {"secrets": {"enabled": False, "action": "block"}})
    assert not [f for f in off if f.code.startswith("secret.")]


def test_defaults_in_the_schema() -> None:
    d = DlpVnDetector(VnRegexMasker(b"k", "t")).settings_schema.defaults()
    assert d["secrets"] == {"enabled": False, "action": "report"}
    assert d["custom_rules"] == [] and d["mask_tokens"] == {}


# ---------------------------------------------------------------------------- secrets


@pytest.mark.parametrize(
    ("code", "value"),
    [
        ("secret.aws_access_key", AWS),
        ("secret.github_token", GH),
        ("secret.huggingface_token", HF),
        ("secret.stripe_key", STRIPE),
        ("secret.anthropic_api_key", ANT),
        ("secret.openai_api_key", OAI),
    ],
)
def test_secret_finding_holds_a_hash_and_the_payload_holds_a_marker(
    det: DlpVnDetector, code: str, value: str
) -> None:
    found = run(det, {"note": f"use {value} please"}, ON)
    (f,) = [f for f in found if f.code == code]
    assert value not in blob(found)
    kind = code.split(".", 1)[1]
    assert f.entities[0].token.startswith(f"<SECRET:{kind}:") and f.masked_count == 1
    assert f.transformed_payload == {"args": {"note": f"use <SECRET:{kind}> please"}}
    assert f.action_hint == "transform" and f.score_bp == 10_000
    fr = f.fragments[0]
    assert fr.precision == "span" and fr.text == f"<SECRET:{kind}>"
    assert f.transformed_payload["args"]["note"][fr.start : fr.end] == fr.text


def test_the_secret_is_masked_before_the_pii_masker_and_both_are_reported(
    det: DlpVnDetector,
) -> None:
    found = run(det, {"n": f"{AWS} and phone 0912345678"}, ON)
    assert {f.code for f in found} == {"secret.aws_access_key", "pii.phone"}
    text = found[0].transformed_payload["args"]["n"]
    assert "<SECRET:aws_access_key>" in text and "0912345678" not in text


def test_report_mode_does_not_transform_but_still_reports(det: DlpVnDetector) -> None:
    found = run(det, {"n": AWS}, {**ON, "mode": "report"})
    assert [f.code for f in found] == ["secret.aws_access_key"]
    assert found[0].action_hint == "report" and found[0].transformed_payload is None


def test_base64_is_decoded_and_masked_as_a_whole(det: DlpVnDetector) -> None:
    enc = base64.b64encode(f"token={GH}".encode()).decode()
    found = run(det, {"blob": enc}, ON)
    assert [f.code for f in found] == ["secret.github_token"]
    assert enc not in blob(found) and GH not in blob(found)
    assert found[0].transformed_payload["args"]["blob"] == "<SECRET:github_token>"


def test_benign_base64_and_look_alikes_are_left_alone(det: DlpVnDetector) -> None:
    enc = base64.b64encode(b"A perfectly ordinary sentence for a customer.").decode()
    text = [enc, "AK" + "IA prefix only", "s" + "k-short", "api_key = settings.llm_api_key"]
    assert run(det, {"n": text}, ON) == []


def test_password_field_by_key_name(det: DlpVnDetector) -> None:
    found = run(det, {"user": "svc", "password": PW, "note": "hello there"}, ON)
    assert [f.code for f in found] == ["secret.password_field"]
    assert PW not in blob(found)
    assert found[0].transformed_payload["args"]["password"] == "<SECRET:password_field>"
    for benign in ("true", "${DB_PASSWORD}", "at least eight characters", "FILL-ME-password"):
        assert run(det, {"password": benign}, ON) == []


def test_secret_in_a_dict_key_value_pair_and_a_list(det: DlpVnDetector) -> None:
    found = run(det, {"a": {"b": [AWS, "ok"]}, "c": f"x {AWS}"}, ON)
    (f,) = found
    assert f.masked_count == 2 and f.entities[0].count == 2  # one value, two places
    assert all(fr.part == "args" for fr in f.fragments)


def test_a_sentinel_character_in_the_input_does_not_break_it(det: DlpVnDetector) -> None:
    text = f" {AWS}"
    found = run(det, {"n": text}, ON)
    (f,) = found
    assert AWS not in blob(found) and f.fragments[0].precision == "leaf"
    assert "<SECRET:aws_access_key>" in f.transformed_payload["args"]["n"]


def test_output_side_secret_is_reported(det: DlpVnDetector) -> None:
    found = run(det, f"here: {GH}", ON, part="output")
    assert [f.code for f in found] == ["secret.github_token"]
    assert GH not in blob(found)


def test_block_hint_only_for_a_secret_in_the_arguments(det: DlpVnDetector) -> None:
    sec = {"secrets": {"enabled": True, "action": "block"}}
    (f,) = run(det, {"n": AWS}, sec)
    assert f.action_hint == "block"
    out = det.evaluate(
        {"output": AWS, "meta": META},
        {**det.settings_schema.defaults(), "preset": "balanced", **sec},
        "output",
    )
    assert out[0].action_hint == "transform"  # not in the arguments: masked, not a block
    res = det.evaluate(
        {"args": {"id": "C-1"}, "tool_results": [AWS], "meta": META},
        {**det.settings_schema.defaults(), "preset": "balanced", **sec},
        "input",
    )
    assert res[0].action_hint == "transform"


# ---------------------------------------------------------------------------- custom rules


def test_keyword_rule_is_an_exact_substring_with_the_default_token(det: DlpVnDetector) -> None:
    rules = [{"id": "conf", "kind": "keyword", "pattern": "CONFIDENTIAL"}]
    (f,) = run(det, {"n": "this is CONFIDENTIAL stuff, not confidential"}, {"custom_rules": rules})
    assert f.code == "custom.conf" and f.masked_count == 1
    assert f.transformed_payload["args"]["n"] == "this is <CUSTOM:conf> stuff, not confidential"
    assert "CONFIDENTIAL" not in blob([f])


def test_regex_rule_with_a_mask_token_and_preserve_length(det: DlpVnDetector) -> None:
    rules = [
        {"id": "acct", "kind": "regex", "pattern": "INT-ACC-[0-9]{8}", "mask_token": "[ACCT]"},
        {"id": "emp", "kind": "regex", "pattern": "EMP[0-9]{5}", "preserve_length": True},
    ]
    found = run(det, {"n": "INT-ACC-12345678 and EMP00042"}, {"custom_rules": rules})
    assert {f.code for f in found} == {"custom.acct", "custom.emp"}
    assert found[0].transformed_payload["args"]["n"] == "[ACCT] and ********"
    assert "12345678" not in blob(found) and "EMP00042" not in blob(found)


def test_custom_rules_off_with_an_empty_list(det: DlpVnDetector) -> None:
    assert run(det, {"n": "CONFIDENTIAL"}, {"custom_rules": []}) == []


def test_a_rule_over_budget_is_a_note_not_a_failure() -> None:
    ticks = iter(range(0, 10**10, 20_000_000))  # every clock read is 20 ms later
    x = Extras(
        {"custom_rules": [{"id": "slow", "kind": "regex", "pattern": "A+B"}]},
        clock=lambda: next(ticks),
    )
    x.scan("AAAB", None)
    assert x.over_budget == {"slow"}


def test_over_budget_rule_adds_a_coverage_note(
    det: DlpVnDetector, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dlp_extras, "RULE_BUDGET_NS", 0)
    rules = [{"id": "slow", "kind": "regex", "pattern": "A+B"}]
    found = run(det, {"n": "AAAB"}, {"custom_rules": rules})
    note = [f for f in found if f.code == "coverage_note.cut"]
    assert len(note) == 1 and "slow" in note[0].detail and note[0].not_executed_reason is None
    assert not note[0].fired


# ---------------------------------------------------------------------------- mask tokens


def test_per_entity_mask_token_replaces_the_pseudonym_in_the_payload_only(
    det: DlpVnDetector,
) -> None:
    found = run(det, {"n": "call 0912345678 now"}, {"mask_tokens": {"pii.phone": "<PHONE>"}})
    (f,) = found
    assert f.transformed_payload["args"]["n"] == "call <PHONE> now"
    assert f.entities[0].token.startswith("<PHONE:")  # the finding keeps the pseudonym


# ---------------------------------------------------------------------------- settings checks


@pytest.mark.parametrize(
    "pattern",
    [
        "(a+)+b",
        "(a*)*",
        "(a|a)*c",
        "(.*)*x",
        "(\\d+)*$",
        "(a|b+)+c",
        "(a)\\1",
        "x" * 201,
        "a{1,5000}",
        "",
        "(",
    ],
)
def test_refused_patterns(pattern: str) -> None:
    assert regex_problems(pattern), pattern


@pytest.mark.parametrize(
    "pattern", ["PRJ-[0-9]{4}-[A-Z]{2}", "\\bEMP\\d{5}\\b", "(?:ab){1,3}c", "a|b"]
)
def test_accepted_patterns(pattern: str) -> None:
    assert regex_problems(pattern) == []


def test_empty_matching_regex_is_refused() -> None:
    assert any("empty" in p for p in regex_problems("a*"))


def test_settings_problems() -> None:
    assert extras_problems({}) == [] and extras_problems(ON) == []
    bad = extras_problems(
        {
            "secrets": {"enabled": "yes", "action": "pause", "x": 1},
            "custom_rules": [
                {"id": "A b", "kind": "regex", "pattern": "x"},
                {"id": "ok", "kind": "fuzzy", "pattern": "x"},
                {"id": "ok2", "kind": "keyword", "pattern": ""},
                {"id": "ok2", "kind": "keyword", "pattern": "y", "mask_token": "<ABC:abcd>"},
                {"id": "ok3", "kind": "regex", "pattern": "(a+)+", "extra": 1},
                "nope",
            ],
            "mask_tokens": {"phone": "<P>", "pii.email": "", "pii.cccd": "x" * 41},
        }
    )
    text = "; ".join(bad)
    for needle in (
        "secrets.enabled",
        "secrets.action",
        "secrets.x",
        "custom_rules[0].id",
        "custom_rules[1].kind",
        "custom_rules[2].pattern",
        "used twice",
        "pseudonym",
        "nested repeats",
        "custom_rules[3].mask_token",
        "custom_rules[4].extra",
        "custom_rules[5]",
        "mask_tokens",
    ):
        assert needle in text, needle
    assert extras_problems(
        {"custom_rules": [{"id": f"r{i}", "kind": "keyword", "pattern": "k"} for i in range(33)]}
    )


def _config(settings: dict[str, Any]) -> str:
    cfg = yaml.safe_load((REPO_ROOT / "config" / "detectors.yaml").read_text(encoding="utf-8"))
    cfg["detectors"]["dlp_vn"]["settings"].update(settings)
    return yaml.safe_dump(cfg)


def test_a_bad_regex_fails_at_load(masker: VnRegexMasker) -> None:
    reg = build_registry(masker)
    ok = {"custom_rules": [{"id": "a", "kind": "regex", "pattern": "PRJ-[0-9]{4}"}], **ON}
    ResolvedDetectors(parse_config(_config(ok), "t"), reg)
    bad = {"custom_rules": [{"id": "a", "kind": "regex", "pattern": "(a+)+"}]}
    with pytest.raises(ConfigError, match="nested repeats"):
        ResolvedDetectors(parse_config(_config(bad), "t"), reg)
    with pytest.raises(ConfigError, match="secrets.action"):
        ResolvedDetectors(parse_config(_config({"secrets": {"action": "pause"}}), "t"), reg)


# ---------------------------------------------------------------------------- the gate


def _gate_gateway(make_gateway: GatewayFactory, masker: VnRegexMasker, action: str) -> Gateway:
    cfg = _config({"secrets": {"enabled": True, "action": action}, "mode": "transform"})
    return make_gateway(gate=make_gate(masker, config_text=cfg))


CALLS = [
    ("customer_service", "read_ticket", {"ticket_id": "T1", "note": f"key {AWS}"}),  # read_only
    (
        "payments",
        "transfer",
        {
            "amount_minor": 1000,
            "from_account_id": "ACC-1",
            "payee_id": "P-1",
            "customer_id": "C-1",
            "memo": f"k {AWS}",
        },
    ),  # money
    (
        "payments",
        "add_payee",
        {"customer_id": "C-1", "payee_name": "Linh", "note": f"k {AWS}"},
    ),  # pii_export
]


@pytest.mark.parametrize(("agent", "tool", "args"), CALLS)
def test_block_action_blocks_every_tool_class(
    make_gateway: GatewayFactory,
    masker: VnRegexMasker,
    evidence: MemoryEvidence,
    agent: str,
    tool: str,
    args: dict[str, Any],
) -> None:
    gw = _gate_gateway(make_gateway, masker, "block")
    r = gw.check(agent, "1", tool, dict(args), {"trace_id": "t-d2"})
    assert r["allow"] is False and r["rule_id"] == "GATE-SECRET-IN-ARGS"
    assert r["status"] == "block" and r["fail_mode"] == "closed"
    assert "transformed_args" not in r and r["transformed_payload"] is None
    assert [f["code"] for f in r["findings"]] == ["secret.aws_access_key"]
    gw.drain()
    everything = json.dumps(
        [
            r,
            gw.tables.query("finding", {}),
            gw.tables.query("agent_event", {}),
            gw.tables.query("verdict", {}),
        ]
        + [p for _, _, p in evidence.entries],
        default=str,
    )
    assert AWS not in everything


def test_report_is_the_default_and_the_call_goes_through_masked(
    make_gateway: GatewayFactory, masker: VnRegexMasker, evidence: MemoryEvidence
) -> None:
    gw = _gate_gateway(make_gateway, masker, "report")
    args = {"customer_id": "C-1", "payee_name": "Linh", "note": f"k {AWS}"}
    r = gw.check("payments", "1", "add_payee", args, {"trace_id": "t-d2"})
    assert r["allow"] is True and r["rule_id"] != "GATE-SECRET-IN-ARGS"
    assert r["status"] == "transform"
    assert "<SECRET:aws_access_key>" in json.dumps(r["transformed_payload"])
    gw.drain()
    assert AWS not in json.dumps(
        [r, gw.tables.query("finding", {})] + [p for _, _, p in evidence.entries], default=str
    )
    read = gw.check(
        "customer_service", "1", "read_ticket", {"ticket_id": "T1", "note": f"k {AWS}"}, {}
    )
    assert read["allow"] is True and read["status"] == "report"
    assert [f["action_hint"] for f in read["findings"]] == ["report"]


def test_secret_only_in_a_tool_result_does_not_block(
    make_gateway: GatewayFactory, masker: VnRegexMasker
) -> None:
    gw = _gate_gateway(make_gateway, masker, "block")
    r = gw.check(
        "customer_service", "1", "read_ticket", {"ticket_id": "T1"}, {"tool_results": [{"b": AWS}]}
    )
    assert r["allow"] is True and r["rule_id"] != "GATE-SECRET-IN-ARGS"


def test_inline_redaction_does_not_leave_the_secret_in_transformed_args(
    make_gateway: GatewayFactory, masker: VnRegexMasker
) -> None:
    cfg = _config({"secrets": {"enabled": True, "action": "report"}, "mode": "transform"})
    gw = make_gateway(gate=make_gate(masker, config_text=cfg), masker=masker, inline_redaction=True)
    args = {"customer_id": "C-1", "payee_name": "NGUYEN VAN THU", "note": f"k {AWS}"}
    r = gw.check("payments", "1", "add_payee", args, {})
    assert r["allow"] is True
    assert AWS not in json.dumps(r["transformed_args"]) and "NGUYEN VAN THU" not in json.dumps(
        r["transformed_args"]
    )


def test_default_config_has_no_secret_findings(
    make_gateway: GatewayFactory, masker: VnRegexMasker
) -> None:
    gw = make_gateway()
    r = gw.check(
        "customer_service", "1", "read_ticket", {"ticket_id": "T1", "note": f"k {AWS}"}, {}
    )
    assert r["allow"] is True and not [f for f in r["findings"] if f["code"].startswith("secret.")]
