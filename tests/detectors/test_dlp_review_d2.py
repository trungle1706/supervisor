# ruff: noqa: F811  (the gw_for fixture is imported from the WP38 review tests)
"""WP-D2 review fixes: risky regexes, keyed digest, observe mode, base64 next to a plain secret,
password key names, secret as a dict key, leaf cap and coverage notes."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.core.detectors import DetectorSetting, RunConfig
from supervisor.detectors import build_registry
from supervisor.detectors.dlp_extras import (
    RULE_LEAF_CHARS,
    extras_problems,
    make_digest,
    regex_problems,
)
from supervisor.detectors.dlp_vn import DlpVnDetector
from supervisor.gateway.engine import Gateway
from tests.detectors.conftest import make_gate
from tests.detectors.test_dlp_secrets_d2 import AWS, GH, ON, PW, _config, blob, run
from tests.gateway.test_review_wp38 import APPROVED, OBSERVE, gw_for, make, text  # noqa: F401

# ---------------------------------------------------------------------------- H1


@pytest.mark.parametrize(
    "pattern",
    [
        ".*.*.*.*x",
        "\\w+\\w+\\w+\\w+!",
        "a?" * 22 + "a" * 22,
        "(a?)+b",
        "x*y*z*w*",
        "\\d+\\s*\\d+",
    ],
)
def test_polynomial_and_exponential_patterns_are_refused(pattern: str) -> None:
    assert regex_problems(pattern), pattern
    assert extras_problems({"custom_rules": [{"id": "r", "kind": "regex", "pattern": pattern}]})


@pytest.mark.parametrize("pattern", ["PRJ-\\d+-[A-Z]{2}", "EMP[0-9]{5}", "(?:ab)?c\\d+", "k.*x"])
def test_ordinary_patterns_still_load(pattern: str) -> None:
    assert regex_problems(pattern) == []


def test_a_regex_reads_only_the_first_characters_of_a_text(det: DlpVnDetector) -> None:
    rules = [{"id": "ref", "kind": "regex", "pattern": "REF-[0-9]{4}"}]
    text_ = "a" * (RULE_LEAF_CHARS + 500) + " REF-1234"
    found = run(det, {"n": text_}, {"custom_rules": rules})
    assert [f.code for f in found] == ["coverage_note.cut"]  # the match is past the cap
    assert "first 2000" in found[0].detail and not found[0].fired
    early = "REF-5678 " + "a" * (RULE_LEAF_CHARS + 500)
    found = run(det, {"n": early}, {"custom_rules": rules})
    assert {f.code for f in found} == {"custom.ref", "coverage_note.cut"}


def test_a_cut_never_fails_a_money_call_closed(make_gateway: Any, masker: VnRegexMasker) -> None:
    rules = [{"id": "ref", "kind": "regex", "pattern": "REF-[0-9]{4}"}]
    gw: Gateway = make_gateway(gate=make_gate(masker, config_text=_config({"custom_rules": rules})))
    big = "a" * (RULE_LEAF_CHARS + 500)
    money = {
        "amount_minor": 1000,
        "from_account_id": "ACC-1",
        "payee_id": "P-1",
        "customer_id": "C-1",
    }
    r = gw.check("payments", "1", "transfer", {**money, "memo": big}, {})
    assert r["allow"] is True and r["rule_id"] != "GATE-DETECTOR-FAILED"
    assert r["coverage"]["notes"][0]["reason"] == "cut"
    assert r["not_executed"] == []


# ---------------------------------------------------------------------------- H2


def test_digest_is_keyed() -> None:
    a = make_digest(VnRegexMasker(b"key-one", "t"))
    b = make_digest(VnRegexMasker(b"key-two", "t"))
    assert a(PW) == a(PW) and a(PW) != b(PW) and len(a(PW)) == 12
    import hashlib

    assert a(PW) != hashlib.sha256(PW.encode()).hexdigest()[:12]
    assert a(PW) != hashlib.sha256(("secret:" + PW).encode()).hexdigest()[:12]
    anon = make_digest(None)  # no keyed_hash: a per-process random key, still not unkeyed
    assert anon(PW) == anon(PW) and anon(PW) != hashlib.sha256(PW.encode()).hexdigest()[:12]


def test_finding_token_changes_with_the_masker_key() -> None:
    d1 = DlpVnDetector(VnRegexMasker(b"key-one", "t"))
    d2 = DlpVnDetector(VnRegexMasker(b"key-two", "t"))
    t1 = run(d1, {"n": AWS}, ON)[0].entities[0].token
    t2 = run(d2, {"n": AWS}, ON)[0].entities[0].token
    assert t1 != t2 and AWS not in t1


# ---------------------------------------------------------------------------- M1


def _observe_gateway(gw_for_: Any, masker: VnRegexMasker) -> Gateway:
    cfg = _config({"secrets": {"enabled": True, "action": "block"}, "mode": "transform"})
    policy = make(text(payer=("RUNNING", OBSERVE + APPROVED), helper=("RUNNING", OBSERVE)))
    return gw_for_(policy, make_gate(masker, config_text=cfg))


@pytest.mark.parametrize(
    ("agent", "tool", "args"),
    [
        ("helper", "lookup", {"tag": "ok", "note": f"k {AWS}"}),  # read_only
        ("payer", "pay", {"amount_minor": 5, "note": f"k {AWS}"}),  # money, two approvals
    ],
)
def test_observe_lifts_the_secret_block_but_sends_masked_arguments(
    gw_for: Any, masker: VnRegexMasker, agent: str, tool: str, args: dict[str, Any]
) -> None:
    gw = _observe_gateway(gw_for, masker)
    r = gw.check(agent, "1", tool, dict(args), {})
    assert r["allow"] is True and r["status"] == "report"
    assert AWS not in json.dumps(r["transformed_args"])
    assert "<SECRET:aws_access_key>" in json.dumps(r["transformed_args"])
    assert r["transformed_args"]["note"] == "k <SECRET:aws_access_key>"
    assert AWS not in json.dumps(r)


def test_observe_does_not_lift_the_secret_block_on_a_pii_export_tool(
    gw_for: Any, masker: VnRegexMasker
) -> None:
    gw = _observe_gateway(gw_for, masker)
    r = gw.check("payer", "1", "export", {"tag": "ok", "note": f"k {AWS}"}, {})
    assert r["allow"] is False and r["rule_id"] == "GATE-SECRET-IN-ARGS"


# ---------------------------------------------------------------------------- M2


def test_base64_secret_next_to_a_plain_secret_is_masked_too(det: DlpVnDetector) -> None:
    enc = base64.b64encode(f"token={GH}".encode()).decode()
    found = run(det, {"n": f"k {AWS} and {enc}"}, ON)
    assert {f.code for f in found} == {"secret.aws_access_key", "secret.github_token"}
    out = found[0].transformed_payload["args"]["n"]
    assert out == "k <SECRET:aws_access_key> and <SECRET:github_token>"
    assert enc not in blob(found)


# ---------------------------------------------------------------------------- M3 and M4


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("passwordPolicy", "Hunter2Pass9x"),
        ("password_changed_at", "2026-10-22T10:00:00Z"),
        ("apiKeyName", "production-key-01"),
        ("privateKeyType", "rsa2048x"),
        ("secrets_manager", "vault-prod-01"),
        ("client_secret_id", "b3f1c2d4e5f6"),
        ("pwd_reset_url", "https://example.invalid/reset/abc"),
        ("passphrase_required", "yes please"),
        ("token", "none"),
        ("secret", "enabled"),
        ("version_token", "1.2.3"),
        ("password", "2026-10-22"),
    ],
)
def test_metadata_names_and_non_values_are_not_password_fields(
    det: DlpVnDetector, key: str, value: str
) -> None:
    assert run(det, {key: value}, ON) == []


@pytest.mark.parametrize(
    "key",
    ["password", "passwd", "pwd", "passphrase", "client_secret", "apiKey", "api_key",
     "accessToken", "mat_khau", "matkhau", "mật_khẩu", "MatKhau", "pin", "pw", "mk", "db.password"],
)  # fmt: skip
def test_password_field_names_including_vietnamese_and_short_ones(
    det: DlpVnDetector, key: str
) -> None:
    value = "4821" if key == "pin" else PW
    found = run(det, {key.split(".")[-1]: value}, ON)
    assert [f.code for f in found] == ["secret.password_field"], key
    assert value not in blob(found)


def test_a_pin_must_be_digits(det: DlpVnDetector) -> None:
    assert run(det, {"pin": "abcd"}, ON) == []


# ---------------------------------------------------------------------------- L1


def test_a_secret_used_as_a_dict_key_is_found_and_masked(det: DlpVnDetector) -> None:
    found = run(det, {AWS: "x", "ok": "y"}, ON)
    assert [f.code for f in found] == ["secret.aws_access_key"]
    assert AWS not in blob(found)
    assert found[0].transformed_payload == {"args": {"<SECRET:aws_access_key>": "x", "ok": "y"}}
    assert found[0].fragments[0].part == "args"


def test_registry_note_reaches_coverage(masker: VnRegexMasker) -> None:
    reg = build_registry(masker)
    rules = [{"id": "ref", "kind": "regex", "pattern": "REF-[0-9]{4}"}]
    cfg = RunConfig({"dlp_vn": DetectorSetting(True, {"custom_rules": rules})})
    payload = {"args": {"n": "a" * (RULE_LEAF_CHARS + 10)}, "meta": {"tool_name": "t"}}
    res = reg.run(payload, "input", cfg)
    assert res.coverage["notes"] == [
        {"detector": "dlp_vn", "reason": "cut", "detail": "custom rule ref: first 2000 characters"}
    ]
    assert res.findings == [] and res.not_executed == []


def test_secret_block_survives_a_cut_payload(make_gateway: Any, masker: VnRegexMasker) -> None:
    """A read-only tool with 100 KB of arguments: dlp_vn reads only max_scan_bytes, the secret in
    the first 1 KB is found, and the block stands."""
    cfg = _config({"secrets": {"enabled": True, "action": "block"}, "mode": "transform"})
    gw: Gateway = make_gateway(gate=make_gate(masker, config_text=cfg))
    big = f"key {AWS} " + "a" * 70_000
    r = gw.check("customer_service", "1", "read_ticket", {"ticket_id": "T1", "note": big}, {})
    assert r["allow"] is False and r["rule_id"] == "GATE-SECRET-IN-ARGS"
    assert r["status"] == "block" and AWS not in json.dumps(r)


@pytest.fixture
def det() -> DlpVnDetector:
    return DlpVnDetector(VnRegexMasker(b"d2-key", "t"))
