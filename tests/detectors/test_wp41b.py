"""WP41b: D31 (a cut argument fails closed on money, credit and pii_export tools), D32 (the
fail-closed path does not mask the full text) and D26 (status ``pause`` for every pause source)."""

from __future__ import annotations

import os
import statistics
import time
from typing import Any

import pytest

from supervisor.adapters.integrations.siem import event_from_chain
from supervisor.analytics.decisions import status_of
from supervisor.core.detectors import DEFAULT_MAX_SCAN_BYTES
from supervisor.gateway.detector_gate import FAILED_RULE
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import StorePolicyProvider, deploy_policy
from supervisor.gateway.redact import over_budget
from supervisor.gateway.session_gate import SessionGate
from supervisor.monitors.common import MonitorContext
from tests.detectors.conftest import GatewayFactory, make_gate
from tests.detectors.test_injection_classifier_gate import MONEY, _gw, _pauser
from tests.monitors.session_helpers import policy_with

ROW = "Nguyen Van Thu, CCCD 001203004567, dien thoai 0912345678, STK 9704 2201 0101 7788. "
HUGE = ROW * (99_000 // len(ROW))
CLEAN = "Ghi chu noi bo ve ho so, khong co thong tin ca nhan. " * 1000  # about 54 KB

# one tool and one agent per risk class of the baseline policy
CLASSES = [
    (
        "money",
        "customer_service",
        "waive_fee",
        {"account_id": "ACC-9", "customer_id": "C-1", "amount_minor": 1000},
    ),
    ("credit", "credit_prequal", "decide_prequal", {"application_id": "A-1"}),
    ("pii_export", "credit_prequal", "fetch_application", {"customer_id": "C-1"}),
    ("read_only", "customer_service", "read_ticket", {"ticket_id": "T1"}),
]


# ---------------------------------------------------------------------------- D31


def _read_application(gw: Gateway) -> None:
    gw.check("credit_prequal", "1", "fetch_application", {"application_id": "A-1"})


@pytest.mark.parametrize(("risk", "agent", "tool", "base"), CLASSES)
def test_a_cut_argument_fails_closed_on_risky_tools_and_not_on_read_only(
    make_gateway: GatewayFactory, risk: str, agent: str, tool: str, base: dict[str, Any]
) -> None:
    gw = make_gateway()
    _read_application(gw)  # CRD-02: a decision needs the application read first
    r = gw.check(agent, "1", tool, {**base, "note": CLEAN})
    cut = [n for n in r["coverage"]["not_inspected"] if n["reason"] == "payload_too_large"]
    assert cut and cut[0]["part"] == "args" and cut[0]["bytes"] > cut[0]["scanned_bytes"]
    if risk == "read_only":
        assert r["allow"] is True and r["rule_id"] != FAILED_RULE  # coverage only
        assert r["status"] in ("allow", "report")
        return
    assert r["allow"] is False and r["action"] == "block" and r["status"] == "block"
    assert r["rule_id"] == FAILED_RULE
    assert "payload_too_large" in r["reason"]
    assert any(n["reason"] == "payload_too_large" for n in r["not_executed"])
    assert r["transformed_payload"] is None


@pytest.mark.parametrize(("risk", "agent", "tool", "base"), CLASSES[:3])
def test_a_small_argument_is_still_allowed_on_risky_tools(
    make_gateway: GatewayFactory, risk: str, agent: str, tool: str, base: dict[str, Any]
) -> None:
    gw = make_gateway()
    _read_application(gw)
    r = gw.check(agent, "1", tool, {**base, "note": "ghi chu ngan"})
    assert r["rule_id"] != FAILED_RULE and not r["coverage"].get("bytes")


def test_the_block_is_recorded_with_the_coverage_reason(
    make_gateway: GatewayFactory, evidence: Any
) -> None:
    gw = make_gateway()
    _read_application(gw)
    gw.check("credit_prequal", "1", "decide_prequal", {"application_id": "A-1", "note": CLEAN})
    rec = evidence.of_type("gate_decision")[-1]
    assert rec["status"] == "block" and rec["rule_id"] == FAILED_RULE
    assert any(n["reason"] == "payload_too_large" for n in rec["coverage"]["not_inspected"])
    assert "*:payload_too_large" in rec["not_executed"]


def test_a_cut_tool_result_on_a_credit_tool_stays_coverage_only(
    make_gateway: GatewayFactory,
) -> None:
    """Only a cut ARGUMENT fails closed (the rule is about what the tool receives)."""
    gw = make_gateway()
    _read_application(gw)
    r = gw.check(
        "credit_prequal",
        "1",
        "decide_prequal",
        {"application_id": "A-1"},
        {"tool_results": [CLEAN]},
    )
    assert r["allow"] is True and r["rule_id"] != FAILED_RULE


def test_a_cut_argument_does_not_block_with_detectors_off(gateway: Gateway) -> None:
    r = gateway.check("credit_prequal", "1", "decide_prequal", {"customer_id": "C-1", "n": CLEAN})
    assert "status" not in r and r["rule_id"] != FAILED_RULE


# ---------------------------------------------------------------------------- D32


def test_over_budget_stops_reading_at_the_limit() -> None:
    assert over_budget({"a": "x" * 100}, 99) is True
    assert over_budget({"a": "x" * 100}, 100) is False
    assert over_budget({"a": ["x" * 60, {"b": "y" * 60}]}, 100) is True
    assert over_budget({"a": 5, "b": None, "c": True}, 0) is False
    assert over_budget({"a": "à" * 60}, 100) is True  # UTF-8 bytes, not characters


def test_the_fail_closed_path_does_not_mask_the_full_text(
    make_gateway: GatewayFactory, masker: Any
) -> None:
    calls: list[int] = []
    real = masker.mask

    def counting(text: str) -> str:
        calls.append(len(text))
        return real(text)

    masker.mask = counting  # type: ignore[method-assign]
    gw = make_gateway(masker=masker, inline_redaction=True)
    r = gw.check("credit_prequal", "1", "fetch_application", {"customer_id": "C-1", "n": HUGE})
    assert r["allow"] is False and r["rule_id"] == FAILED_RULE
    assert max(calls, default=0) <= DEFAULT_MAX_SCAN_BYTES  # never beyond the budget
    # a payload inside the budget is still masked inline
    small = ROW * 5
    r2 = gw.check("credit_prequal", "1", "fetch_application", {"customer_id": "C-1", "n": small})
    assert r2["allow"] is True and r2["transformed_args"]["n"] != small


def test_inline_redaction_without_detectors_still_masks_the_full_text(
    adapters: Any, evidence: Any, baseline: Any, masker: Any
) -> None:
    """No detector gate, no scan budget: the WP24b behaviour is unchanged."""
    deploy_policy(baseline, adapters.state, adapters.clock)
    gw = Gateway(
        StorePolicyProvider(adapters.state, refresh_s=0),
        adapters.tables,
        adapters.state,
        evidence,
        adapters.clock,
        state_cache_ttl_s=0,
        masker=masker,
        inline_redaction=True,
        timeout_s=30.0,  # not a timing test: masking ~100 kB on a slow CI runner takes > 2 s
    )
    r = gw.check("credit_prequal", "1", "fetch_application", {"customer_id": "C-1", "n": HUGE})
    assert r["allow"] is True and "001203004567" not in r["transformed_args"]["n"]
    gw.close()


@pytest.mark.perf
@pytest.mark.skipif(os.environ.get("RUN_PERF") != "1", reason="timing test: set RUN_PERF=1")
def test_99kb_pii_export_argument_fails_closed_under_100ms_p50(
    make_gateway: GatewayFactory, masker: Any
) -> None:
    gw = make_gateway(masker=masker, inline_redaction=True)
    args = {"customer_id": "C-1", "n": HUGE}
    gw.check("credit_prequal", "1", "fetch_application", args)  # warm up
    took = []
    for _ in range(9):
        t0 = time.perf_counter()
        r = gw.check("credit_prequal", "1", "fetch_application", args)
        took.append((time.perf_counter() - t0) * 1000)
        assert r["rule_id"] == FAILED_RULE
    p50 = statistics.median(took)
    print(f"\n[INFO] 99 KB pii_export fail-closed: p50 {p50:.0f} ms, load {os.getloadavg()[0]:.1f}")
    assert p50 < 100


# ---------------------------------------------------------------------------- D26


def _assert_everywhere(r: dict[str, Any], gw: Gateway, evidence: Any) -> None:
    """The answer, the event row, the chain record and the SIEM event all say ``pause``."""
    assert r["status"] == "pause"
    row = gw.tables.query("agent_event", {"event_id": r["decision_id"]})[0]
    assert row["verdict_status"] == "pause" and status_of(row) == "pause"
    rec = [p for p in evidence.of_type("gate_decision") if p.get("decision_id") == r["decision_id"]]
    assert rec and rec[0]["status"] == "pause"
    entry = {"record_type": "gate_decision", "seq": 1, "ts": "2026-10-21T00:00:00Z"}
    ev = event_from_chain({**entry, "lane": "payments", "entry_hash": "0" * 64}, rec[0])
    assert ev is not None and ev.attrs and ev.attrs["status"] == "pause"


def test_pause_by_rule(make_gateway: GatewayFactory, evidence: Any) -> None:
    gw = make_gateway()
    args = {
        "amount_minor": 80_000_000,
        "from_account_id": "ACC-1",
        "payee_id": "P-1",
        "currency": "VND",
    }
    first = gw.check("payments", "1", "transfer", {**args, "payee_id": "P-2"})
    assert first["allow"] is True  # under the daily sum
    r = gw.check("payments", "1", "transfer", args)
    assert r["action"] == "pause" and r["agent_paused"] is True
    _assert_everywhere(r, gw, evidence)


def test_pause_by_classifier(make_gateway: GatewayFactory, masker: Any, evidence: Any) -> None:
    gw = _gw(make_gateway, masker, _pauser())
    r = gw.check("payments", "1", "transfer", MONEY)
    assert r["action"] == "pause"
    _assert_everywhere(r, gw, evidence)


def test_pause_by_state_the_old_action_field_stays_block(
    make_gateway: GatewayFactory, masker: Any, evidence: Any
) -> None:
    gw = _gw(make_gateway, masker, _pauser())
    gw.check("payments", "1", "transfer", MONEY)  # pauses the agent
    r = gw.check("payments", "1", "transfer", MONEY)
    assert r["rule_id"] == "GATE-PAUSED" and r["allow"] is False
    assert r["action"] == "block"  # contract v1 field unchanged
    _assert_everywhere(r, gw, evidence)


def test_pause_by_session(adapters: Any, evidence: Any, clock: Any, masker: Any) -> None:
    from tests.monitors.test_session import SESSION_CFG, SPLIT, feed

    deploy_policy(policy_with(SESSION_CFG), adapters.state, adapters.clock)
    from supervisor.config import load_settings

    sg = SessionGate(
        load_settings(session_monitor_enabled=True),
        MonitorContext.from_adapters(adapters, evidence),
    )
    sg.sync_reload = True
    gw = Gateway(
        StorePolicyProvider(adapters.state, refresh_s=0),
        adapters.tables,
        adapters.state,
        evidence,
        adapters.clock,
        state_cache_ttl_s=0,
        session_gate=sg,
        detector_gate=make_gate(masker),
    )
    feed(gw, clock, SPLIT)
    r = feed(gw, clock, [("transfer", MONEY | {"currency": "VND"}, "small one")])[0]
    assert r["rule_id"] == "GATE-SESSION-PAUSE" and r["allow"] is False
    assert r["action"] == "block"
    _assert_everywhere(r, gw, evidence)
    gw.close()


def test_a_block_rule_still_wins_over_a_pause(make_gateway: GatewayFactory) -> None:
    """Precedence block > pause: a quarantined agent stays ``block``, not ``pause``."""
    gw = make_gateway()
    gw.states.quarantine(
        "payments", "rule:test", "test", auth_method="local_system", actor_kind="system"
    )
    r = gw.check("payments", "1", "transfer", MONEY)
    assert r["rule_id"] == "GATE-QUARANTINED" and r["status"] == "block"
