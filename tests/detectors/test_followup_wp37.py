"""WP37 follow-ups after review: F11 (reload validation), F12 (correlation id only with the flag),
F14 (skip_tools on risky tools refused)."""

from __future__ import annotations

import logging
from typing import Any

import pytest
import yaml

from supervisor.gateway.policy import (
    PolicyError,
    deploy_policy,
    load_policy_texts,
    policy_json_schema,
)
from supervisor.recorder.capture import AgentCapture, CapturePolicy
from supervisor.recorder.normalise import Normaliser, SpanData
from tests.conftest import REPO_ROOT
from tests.detectors.conftest import GatewayFactory

MONEY = {"amount_minor": 1000, "from_account_id": "ACC-1", "payee_id": "P-1", "customer_id": "C-1"}


def _doc() -> dict[str, Any]:
    return yaml.safe_load((REPO_ROOT / "policies" / "baseline.yaml").read_text(encoding="utf-8"))


def _policy(detectors: dict[str, Any] | None, agent: str = "payments") -> Any:
    doc = _doc()
    if detectors is not None:
        doc["agents"][agent]["detectors"] = detectors
    return load_policy_texts([("p.yaml", yaml.safe_dump(doc))])


# ---------------------------------------------------------------------------- F11


def test_a_bad_override_after_a_reload_is_rejected_and_the_old_policy_stays(
    make_gateway: GatewayFactory, adapters: Any, caplog: pytest.LogCaptureFixture
) -> None:
    gw = make_gateway(policy=_policy({"preset": "strict"}))
    gw.policy.validator = gw.detector_gate.check_policy  # as the composition root does
    old_hash = gw.policy.current().policy_hash
    ok = gw.check("payments", "1", "transfer", MONEY)
    assert ok["allow"] is True and ok["not_executed"] == []

    bad = _policy({"settings": {"dlp_vn": {"mode": "sideways"}}, "enable": ["nope"]})
    with caplog.at_level(logging.ERROR, logger="supervisor.gateway"):
        deploy_policy(bad, adapters.state, adapters.clock)
        r = gw.check("payments", "1", "transfer", MONEY)  # refresh_s=0: this call reloads
    assert gw.policy.current().policy_hash == old_hash  # the old policy is kept
    assert gw.policy.rejected_hash == bad.policy_hash
    reason = gw.policy.rejected_reason or ""
    assert reason.isascii() and "payments" in reason and "mode" in reason
    # a money call is not failed closed with invalid_config
    assert r["allow"] is True and r["rule_id"] is None and r["not_executed"] == []
    logged = [m for m in caplog.messages if "reload rejected" in m]
    assert len(logged) == 1 and logged[0].isascii()
    gw.check("payments", "1", "transfer", MONEY)
    assert len([m for m in caplog.messages if "reload rejected" in m]) == 1  # once per bad policy

    good = _policy({"preset": "lenient"})
    deploy_policy(good, adapters.state, adapters.clock)
    gw.check("payments", "1", "get_balance", {})
    assert gw.policy.current().policy_hash == good.policy_hash and gw.policy.rejected_hash is None


def test_the_first_load_of_a_bad_policy_raises_an_ascii_error(
    make_gateway: GatewayFactory,
) -> None:
    gw = make_gateway(policy=_policy({"settings": {"dlp_vn": {"mode": "sideways"}}}))
    fresh = type(gw.policy)(gw.policy.state, refresh_s=0)
    fresh.validator = gw.detector_gate.check_policy
    with pytest.raises(PolicyError) as exc:
        fresh.current()
    assert str(exc.value).isascii() and "payments" in str(exc.value)


def test_the_runtime_sets_the_validator_when_detectors_are_on(tmp_path: Any) -> None:
    from supervisor.config import load_settings
    from supervisor.wiring import build_runtime

    for on in (True, False):
        settings = load_settings(
            sql_backend="sqlite", data_dir=tmp_path / str(on), llm_base_url="", detectors_enabled=on
        )
        rt = build_runtime(settings)
        try:
            assert (rt.gateway.policy.validator is not None) is on
        finally:
            rt.close()


# ---------------------------------------------------------------------------- F12


def _span(attrs: dict[str, Any]) -> SpanData:
    return SpanData(
        trace_id="a" * 32,
        span_id="b" * 16,
        parent_span_id=None,
        name="execute_tool add_payee",
        kind="INTERNAL",
        start_ns=1_700_000_000_000_000_000,
        end_ns=1_700_000_000_100_000_000,
        attributes=attrs,
    )


ATTRS = {
    "supervisor.agent_id": "payments",
    "supervisor.event_type": "tool_call",
    "supervisor.tool_name": "add_payee",
    "supervisor.gate.correlation_id": "corr-from-sender",
}


def test_the_span_correlation_id_is_kept_only_with_the_flag() -> None:
    cap = CapturePolicy({"payments": AgentCapture("digest")})
    off = Normaliser(None, cap, "dev")
    assert off.keep_correlation_id is False
    assert off.normalise_many([_span(ATTRS)], "otel")[0].event.correlation_id is None
    on = Normaliser(None, cap, "dev", keep_correlation_id=True)
    assert on.normalise_many([_span(ATTRS)], "otel")[0].event.correlation_id == "corr-from-sender"


def test_the_recorder_service_follows_the_setting() -> None:
    import inspect

    from supervisor.recorder import service

    assert "keep_correlation_id=settings.detectors_enabled" in inspect.getsource(service)


# ---------------------------------------------------------------------------- F14


@pytest.mark.parametrize(
    ("tool", "cls"),
    [("transfer", "money"), ("decide_prequal", "credit"), ("add_payee", "pii_export")],
)
def test_skip_tools_on_a_risky_tool_is_refused_with_an_ascii_message(tool: str, cls: str) -> None:
    with pytest.raises(PolicyError) as exc:
        _policy({"skip_tools": ["get_balance", tool]})
    msg = str(exc.value)
    assert msg.isascii() and "payments" in msg and tool in msg and cls in msg


def test_skip_tools_on_read_only_and_unlisted_tools_is_fine() -> None:
    p = _policy({"skip_tools": ["get_balance", "list_payees", "not_a_tool"]})
    assert p.agent_detectors("payments").skip_tools[0] == "get_balance"


def test_the_policy_schema_documents_the_skip_rule() -> None:
    schema = policy_json_schema()
    text = str(schema["$defs"]["AgentDetectors"]["properties"]["skip_tools"])
    assert "money, credit or pii_export" in text


def test_docs_say_it() -> None:
    doc = (REPO_ROOT / "docs" / "detectors.md").read_text(encoding="utf-8")
    assert "skip_tools" in doc and "refuses" in doc
