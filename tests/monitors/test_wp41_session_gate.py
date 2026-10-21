"""WP41 (D24, D25) at the gate: a noisy NO-GO detector next to the session monitor.

The benchmark's lenient classifier fired on 85 percent of the calls of clean runs, the session
`findings` signal counted all of it, and a clean run opened a case. Here a fake detector fires on
every call; its `mrm_status` decides whether the session sees it.
"""

from __future__ import annotations

from typing import Any

from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.config import load_settings
from supervisor.core.detectors import Finding
from supervisor.detectors import build_registry
from supervisor.detectors.config import ResolvedDetectors, parse_config
from supervisor.gateway.detector_gate import DetectorGate
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import StorePolicyProvider, deploy_policy
from supervisor.gateway.session_gate import SessionGate
from supervisor.monitors.common import MonitorContext
from supervisor.monitors.session import SessionConfig
from tests.detectors.fakes import FakeDetector
from tests.monitors.session_helpers import policy_with

SID = "conv-wp41-gate"


def _gateway(adapters: Any, evidence: Any, status_line: str) -> Gateway:
    """Gateway with a session gate and a detector gate; one fake detector 'noisy' that fires on
    every call, with the given ``mrm_status`` text in its config entry."""

    def fire(payload: Any, settings: Any, direction: str) -> list[Finding]:
        return [Finding("noisy", "noisy@1", "injection.noise", 9000, 5000)]

    reg = build_registry(VnRegexMasker(b"k", "t"))
    reg.register(FakeDetector("noisy", fire, sides=("input",)))
    cfg = parse_config(
        "version: 1\ndetectors:\n  noisy: {enabled: true, fail_closed: false" + status_line + "}\n",
        "t",
    )
    pol = policy_with({"k": 3, "case_threshold_bp": 2500, "pause_scope": []})
    deploy_policy(pol, adapters.state, adapters.clock)
    sg = SessionGate(
        load_settings(session_monitor_enabled=True),
        MonitorContext.from_adapters(adapters, evidence),
    )
    sg.sync_reload = True
    return Gateway(
        StorePolicyProvider(adapters.state, refresh_s=0),
        adapters.tables,
        adapters.state,
        evidence,
        adapters.clock,
        state_cache_ttl_s=0,
        session_gate=sg,
        detector_gate=DetectorGate(reg, ResolvedDetectors(cfg, reg)),
    )


def _run_clean(gw: Gateway, clock: Any) -> None:
    for _ in range(6):
        clock.advance(30)
        gw.check("payments", "1", "get_balance", {"account_id": "A-1"}, {"session_id": SID})
    gw.drain()


def _assess(gw: Gateway) -> Any:
    sg = gw.session_gate
    assert sg is not None
    turns = sg.engine.turns(SID, "payments")
    assert turns
    a = sg.engine.assess(SID, "payments", turns[-1].ts_ms, SessionConfig())
    assert a is not None
    return turns, a


def test_a_nogo_detector_fires_on_every_call_and_the_session_stays_quiet(
    adapters: Any, evidence: Any, clock: Any
) -> None:
    gw = _gateway(adapters, evidence, "")  # no mrm_status: NO-GO
    try:
        _run_clean(gw, clock)
        turns, a = _assess(gw)
        assert all(any(c.startswith("r:") for c in t.codes) for t in turns)
        assert not any(c.startswith("d:") for t in turns for c in t.codes)
        assert a.counts["findings"] == 0 and a.score_bp == 0 and not a.case_due
        cases = [c for c in adapters.state.query("cases") if c["case_type"] == "session_escalation"]
        assert cases == []
        # the findings are still recorded, and so are the session codes of the turn
        assert adapters.tables.query("finding", {"detector_slug": "noisy"}, limit=3)
        ev = adapters.tables.query("agent_event", {"event_type": "gate_decision"}, limit=20)
        assert any("injection.noise" in str(e.get("session_json")) for e in ev)
    finally:
        gw.close()


def test_the_same_detector_with_status_go_counts(adapters: Any, evidence: Any, clock: Any) -> None:
    gw = _gateway(adapters, evidence, ", mrm_status: GO")
    try:
        _run_clean(gw, clock)
        turns, a = _assess(gw)
        assert any(c.startswith("d:") for t in turns for c in t.codes)
        assert a.counts["findings"] >= 3 and a.strengths["findings"] == 10000
    finally:
        gw.close()
