"""WP24b inline redaction: transformed_args at the gate, applied by the SDK and the MCP proxy.

Default OFF: the gate answer has no ``transformed_args`` and the tool gets the original
arguments. ON: a pii_export tool gets masked arguments, amounts stay intact, and the chain
holds hashes of the original and the transformed arguments, never the values.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.gateway import sdk
from supervisor.gateway.engine import Gateway
from supervisor.gateway.mcp_proxy import McpGateProxy
from supervisor.gateway.policy import Policy, StorePolicyProvider, deploy_policy
from supervisor.gateway.redact import redact_args
from supervisor.gateway.sdk import InProcessGate, supervised_tool
from tests.gateway.conftest import MemoryEvidence
from tests.gateway.test_mcp_proxy import FakeUpstream, call

NAME = "NGUYỄN VĂN THỬ"
CCCD = "001203004567"
ARGS = {
    "customer_id": "C-1",
    "payee_name": NAME,
    "cccd": CCCD,
    "note": "Chuyển 1.500.000.000 VND, địa chỉ Số 12 Nguyễn Huệ, Phường Bến Nghé, Quận 1, TP.HCM",
}


def _gw(adapters: Any, evidence: MemoryEvidence, baseline: Policy, **kw: Any) -> Gateway:
    deploy_policy(baseline, adapters.state, adapters.clock)
    return Gateway(
        StorePolicyProvider(adapters.state, refresh_s=0),
        adapters.tables,
        adapters.state,
        evidence,
        adapters.clock,
        state_cache_ttl_s=0,
        **kw,
    )


@pytest.fixture
def masker() -> VnRegexMasker:
    return VnRegexMasker(b"test-key", "t")


@pytest.fixture
def gw_on(
    adapters: Any, evidence: MemoryEvidence, baseline: Policy, masker: VnRegexMasker
) -> Iterator[Gateway]:
    gw = _gw(adapters, evidence, baseline, masker=masker, inline_redaction=True)
    yield gw
    gw.close()


@pytest.fixture(autouse=True)
def _reset_sdk() -> Iterator[None]:
    sdk.set_inline_redaction(None)
    sdk.set_default_gate(None)
    yield
    sdk.set_inline_redaction(None)
    sdk.set_default_gate(None)


def test_redact_args_masks_strings_keeps_numbers_and_amounts(masker: VnRegexMasker) -> None:
    out, n = redact_args(masker, {**ARGS, "amount_minor": 1_500_000_000, "ok": True, "k": [NAME]})
    assert n >= 4
    assert NAME not in json.dumps(out, ensure_ascii=False) and CCCD not in json.dumps(out)
    assert "1.500.000.000 VND" in out["note"]  # the amount reaches the tool intact
    assert out["amount_minor"] == 1_500_000_000 and out["ok"] is True
    assert out["payee_name"].startswith("<PERSON:")


def test_off_by_default_no_transformed_args(
    adapters: Any, evidence: MemoryEvidence, baseline: Policy
) -> None:
    gw = _gw(adapters, evidence, baseline)  # no masker, flag off
    try:
        r = gw.check("payments", "1", "add_payee", ARGS)
        assert r["allow"] is True and "transformed_args" not in r
        assert "inline_redaction" not in evidence.of_type("gate_decision")[-1]
    finally:
        gw.close()


def test_flag_off_with_masker_present_is_still_off(
    adapters: Any, evidence: MemoryEvidence, baseline: Policy, masker: VnRegexMasker
) -> None:
    gw = _gw(adapters, evidence, baseline, masker=masker, inline_redaction=False)
    try:
        assert "transformed_args" not in gw.check("payments", "1", "add_payee", ARGS)
    finally:
        gw.close()


def test_pii_export_tool_gets_transformed_args(gw_on: Gateway, evidence: MemoryEvidence) -> None:
    r = gw_on.check("payments", "1", "add_payee", ARGS)
    assert r["allow"] is True and r["risk_class"] == "pii_export"
    t = r["transformed_args"]
    assert NAME not in json.dumps(t, ensure_ascii=False) and CCCD not in json.dumps(t)
    assert "1.500.000.000 VND" in t["note"]
    assert r["redaction_count"] >= 3 and len(r["args_hmac_transformed"]) == 64


def test_read_only_tool_is_not_transformed(gw_on: Gateway) -> None:
    r = gw_on.check("payments", "1", "get_balance", {"account_id": "A-1", "who": NAME})
    assert r["allow"] is True and "transformed_args" not in r


def test_per_tool_flag_extends_to_other_tools(
    adapters: Any, evidence: MemoryEvidence, baseline: Policy, masker: VnRegexMasker
) -> None:
    gw = _gw(
        adapters,
        evidence,
        baseline,
        masker=masker,
        inline_redaction=True,
        redact_tools=frozenset({"get_balance"}),
    )
    try:
        r = gw.check("payments", "1", "get_balance", {"account_id": "A-1", "who": NAME})
        assert NAME not in json.dumps(r["transformed_args"], ensure_ascii=False)
    finally:
        gw.close()


def test_blocked_call_has_no_transformed_args(gw_on: Gateway) -> None:
    r = gw_on.check("payments", "1", "no_such_tool", ARGS)
    assert r["allow"] is False and "transformed_args" not in r


def test_chain_holds_hashes_never_values(gw_on: Gateway, evidence: MemoryEvidence) -> None:
    gw_on.check("payments", "1", "add_payee", ARGS)
    rec = evidence.of_type("gate_decision")[-1]
    assert rec["inline_redaction"] is True
    assert len(rec["args_hmac"]) == 64 and len(rec["args_hmac_transformed"]) == 64
    assert rec["args_hmac"] != rec["args_hmac_transformed"]
    assert rec["masker_version"].startswith("vn_regex-3")
    blob = json.dumps(rec, ensure_ascii=False)
    assert NAME not in blob and CCCD not in blob and "<PERSON:" not in blob


def test_sdk_applies_transformed_args_when_on(gw_on: Gateway) -> None:
    seen: list[dict[str, Any]] = []

    @supervised_tool("payments", "1", "add_payee", "pii_export", InProcessGate(gw_on))
    def add_payee(customer_id: str, payee_name: str, cccd: str, note: str = "") -> str:
        seen.append({"payee_name": payee_name, "cccd": cccd, "note": note})
        return "saved"

    sdk.set_inline_redaction(True)
    assert add_payee("C-1", NAME, CCCD, note=ARGS["note"]) == "saved"
    got = seen[0]
    assert NAME not in got["payee_name"] and got["payee_name"].startswith("<PERSON:")
    assert got["cccd"].startswith("<CCCD:") and "1.500.000.000 VND" in got["note"]


def test_sdk_ignores_transformed_args_when_off(gw_on: Gateway) -> None:
    seen: list[str] = []

    @supervised_tool("payments", "1", "add_payee", "pii_export", InProcessGate(gw_on))
    def add_payee(customer_id: str, payee_name: str, cccd: str, note: str = "") -> None:
        seen.append(payee_name)

    sdk.set_inline_redaction(False)
    add_payee("C-1", NAME, CCCD)
    assert seen == [NAME]  # off path: the tool gets the original argument


def test_sdk_env_switch(gw_on: Gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    @supervised_tool("payments", "1", "add_payee", "pii_export", InProcessGate(gw_on))
    def add_payee(customer_id: str, payee_name: str, cccd: str) -> None:
        seen.append(payee_name)

    monkeypatch.setenv("INLINE_REDACTION_ENABLED", "1")
    add_payee("C-1", NAME, CCCD)
    assert seen[0].startswith("<PERSON:")


def test_sdk_async_tool(gw_on: Gateway) -> None:
    import asyncio

    seen: list[str] = []

    @supervised_tool("payments", "1", "add_payee", "pii_export", InProcessGate(gw_on))
    async def add_payee(customer_id: str, payee_name: str, cccd: str) -> None:
        seen.append(payee_name)

    sdk.set_inline_redaction(True)
    asyncio.run(add_payee("C-1", NAME, CCCD))
    assert seen[0].startswith("<PERSON:")


def test_mcp_proxy_forwards_transformed_args(gw_on: Gateway) -> None:
    up = FakeUpstream()
    proxy = McpGateProxy(gw_on, "payments", "1", up, inline_redaction=True)
    proxy.handle(call(1, "add_payee", dict(ARGS)))
    sent = up.forwarded[0]["params"]["arguments"]
    assert NAME not in json.dumps(sent, ensure_ascii=False) and "1.500.000.000 VND" in sent["note"]


def test_mcp_proxy_default_forwards_original(gw_on: Gateway) -> None:
    up = FakeUpstream()
    proxy = McpGateProxy(gw_on, "payments", "1", up)  # flag off
    msg = call(1, "add_payee", dict(ARGS))
    proxy.handle(msg)
    assert up.forwarded == [msg]


def test_http_route_and_http_gate_carry_transformed_args(gw_on: Gateway) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from supervisor.gateway import wiring
    from supervisor.gateway.routes import router
    from supervisor.gateway.sdk import HttpGate

    app = FastAPI()
    app.include_router(router)
    wiring.set_gateway(gw_on)
    try:
        client = TestClient(app)

        def transport(url: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
            r = client.post("/gate/check", json=payload)
            assert r.status_code == 200
            return r.json()  # type: ignore[no-any-return]

        gate = HttpGate("http://testserver", transport=transport)
        seen: list[str] = []

        @supervised_tool("payments", "1", "add_payee", "pii_export", gate)
        def add_payee(customer_id: str, payee_name: str, cccd: str) -> None:
            seen.append(payee_name)

        sdk.set_inline_redaction(True)
        add_payee("C-1", NAME, CCCD)
        assert seen[0].startswith("<PERSON:")
    finally:
        wiring.set_gateway(None)


def test_settings_defaults_and_wiring_flags() -> None:
    from supervisor.adapters.factory import make_masker
    from supervisor.config import load_settings
    from supervisor.wiring import _redaction_masker

    s = load_settings()
    assert s.mask_amounts is False and s.inline_redaction_enabled is False
    assert s.inline_redaction_tool_set == frozenset()
    s2 = load_settings(mask_amounts=True, inline_redaction_tools=" a, b ,,c")
    assert s2.inline_redaction_tool_set == frozenset({"a", "b", "c"})
    m = make_masker(s2)
    assert getattr(m, "mask_version", "").endswith("+amt")
    assert getattr(make_masker(s), "mask_version", "").startswith("vn_regex-3:")
    # the gate masker never types amounts, whatever MASK_AMOUNTS says
    assert not getattr(_redaction_masker(s2), "mask_version", "").endswith("+amt")


# ---------------------------------------------------------------- review WP24b (Opus)
def test_shadow_mode_is_unaffected(gw_on: Gateway, evidence: MemoryEvidence) -> None:
    gw_on.states.set_mode("payments", "SHADOW", "reviewer.an")
    r = gw_on.check("payments", "1", "add_payee", ARGS)
    assert r["allow"] is True and r["agent_state"] == "SHADOW"
    assert "transformed_args" not in r
    assert "inline_redaction" not in evidence.of_type("gate_decision")[-1]


def test_paused_agent_is_blocked_without_transformed_args(gw_on: Gateway) -> None:
    gw_on.states.pause("payments", "reviewer.an", "review")
    r = gw_on.check("payments", "1", "add_payee", ARGS)
    assert r["allow"] is False and r["rule_id"] == "GATE-PAUSED"
    assert "transformed_args" not in r


def test_rules_see_the_original_arguments(gw_on: Gateway) -> None:
    """PAY-09 counts new payees per customer: the window keys on the ORIGINAL customer id,
    although the masker would turn this phone-shaped id into a pseudonym."""
    args = {**ARGS, "customer_id": "0912345678"}
    first = gw_on.check("payments", "1", "add_payee", args)
    assert "0912345678" not in json.dumps(first["transformed_args"])
    for _ in range(2):
        assert gw_on.check("payments", "1", "add_payee", args)["allow"] is True
    r = gw_on.check("payments", "1", "add_payee", args)
    assert r["allow"] is False and r["rule_id"] == "PAY-09"


def test_redaction_failure_fails_closed(gw_on: Gateway, evidence: MemoryEvidence) -> None:
    class Broken:
        mask_version = "broken"

        def mask(self, text: str) -> str:
            raise RuntimeError("boom")

    gw_on.masker = Broken()  # type: ignore[assignment]
    r = gw_on.check("payments", "1", "add_payee", ARGS)
    assert r["allow"] is False and r["rule_id"] == "GATE-REDACTION"
    assert "transformed_args" not in r
    assert evidence.of_type("gate_decision")[-1]["rule_id"] == "GATE-REDACTION"
    # the same on the pre-lock path (hinted tool, declared risk class)
    ctx = {"declared_risk_class": "pii_export"}
    assert gw_on.check("payments", "1", "add_payee", ARGS, ctx)["rule_id"] == "GATE-REDACTION"
    # a tool outside the redaction scope is not affected by a broken masker
    assert gw_on.check("payments", "1", "get_balance", {"account_id": "A-1"})["allow"] is True


def test_sdk_refuses_when_it_cannot_map_the_answer() -> None:
    import inspect

    def tool(a: str) -> None: ...

    sdk.set_inline_redaction(True)
    with pytest.raises(sdk.SupervisorBlocked):
        sdk.apply_transformed(
            inspect.signature(tool), ("x", "extra"), {}, {"transformed_args": {"a": "<PERSON:1>"}}
        )
    args, kwargs = sdk.apply_transformed(
        inspect.signature(tool), ("x",), {}, {"transformed_args": {"a": "<PERSON:1>"}}
    )
    assert args == ("<PERSON:1>",) and kwargs == {}


def test_pre_lock_pass_gives_the_same_answer(gw_on: Gateway) -> None:
    """The masker pass may run before the gate lock (hint) or under it: same result."""
    under = gw_on.check("payments", "1", "add_payee", ARGS)  # no hint yet: under the lock
    assert "add_payee" in gw_on._redact_hint
    pre = gw_on.check("payments", "1", "add_payee", ARGS)  # hinted: before the lock
    assert pre["transformed_args"] == under["transformed_args"]
    assert pre["args_hmac_transformed"] == under["args_hmac_transformed"]
    # a hint never widens the scope: the policy risk class decides under the lock
    r = gw_on.check(
        "payments", "1", "get_balance", {"who": NAME}, {"declared_risk_class": "pii_export"}
    )
    assert "transformed_args" not in r
