"""Multi-agent split payment across callers (ADR D10) + REQUIRE_CALLER_ID fail-closed flag."""

from __future__ import annotations

from datetime import timedelta

import pytest

from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import StorePolicyProvider, deploy_policy, load_policy_dir
from supervisor.monitors.common import MonitorContext
from supervisor.monitors.multiagent import MultiAgentMonitor, SplitPaymentConfig
from supervisor.monitors.seed import as_rows, split_payment_events
from tests.conftest import REPO_ROOT
from tests.judge.conftest import assert_no_floats
from tests.monitors.conftest import T0


def _monitor(adapters, evidence) -> MultiAgentMonitor:
    return MultiAgentMonitor(MonitorContext.from_adapters(adapters, evidence))


def test_split_across_two_callers_opens_one_case_naming_both(adapters, clock, evidence) -> None:
    clock.advance(3600)
    adapters.tables.append("agent_event", as_rows(split_payment_events(T0 + timedelta(minutes=5))))
    clock.advance(1800)
    res = _monitor(adapters, evidence).run()
    assert len(res.cases_opened) == 1
    case = adapters.state.get("cases", {"case_id": res.cases_opened[0]})
    assert case["case_type"] == "multiagent" and case["severity"] == "high"
    assert "customer_service" in case["summary"] and "credit_prequal" in case["summary"]
    (p,) = evidence.of_type("case_opened")
    assert_no_floats(p)
    assert p["agents"] == ["credit_prequal", "customer_service", "payments"]
    assert p["callers"] == ["credit_prequal", "customer_service"]
    assert p["total_minor"] == 115_000_000 and p["limit_minor"] == 100_000_000
    # Next run: cursor moved on, the same pattern is not reported again.
    clock.advance(300)
    assert _monitor(adapters, evidence).run().cases_opened == []


def test_same_caller_or_under_limit_is_not_a_finding(adapters, clock, evidence) -> None:
    rows = as_rows(split_payment_events(T0, callers=("customer_service", "customer_service")))
    rows += as_rows(split_payment_events(T0, amounts=(40_000_000, 50_000_000), payee="P-2"))
    rows += as_rows(  # two callers, over the limit, but more than one hour apart
        split_payment_events(T0, payee="P-3", gap_s=4000)
    )
    adapters.tables.append("agent_event", rows)
    clock.advance(3 * 3600)
    assert _monitor(adapters, evidence).run().cases_opened == []


def test_scan_spans_runs_and_restarts(adapters, clock, evidence) -> None:
    """First transfer before the cursor, second after: the window is re-read."""
    ev = split_payment_events(T0 + timedelta(minutes=50), gap_s=1200)
    adapters.tables.append("agent_event", as_rows(ev[:1]))
    clock.advance(3600)  # T0+60m: run sees one transfer only
    assert _monitor(adapters, evidence).run().cases_opened == []
    adapters.tables.append("agent_event", as_rows(ev[1:]))  # at T0+70m
    clock.advance(1200)
    assert len(_monitor(adapters, evidence).run().cases_opened) == 1  # new process, new scanner


def test_end_to_end_through_real_gateway(adapters, clock, evidence) -> None:
    policy = load_policy_dir(REPO_ROOT / "policies")
    deploy_policy(policy, adapters.state, adapters.clock)
    gw = Gateway(StorePolicyProvider(adapters.state, refresh_s=0), adapters.tables,
                 adapters.state, evidence, adapters.clock, state_cache_ttl_s=0)  # fmt: skip
    try:
        args = {"from_account_id": "ACC-1", "payee_id": "PAYEE-9", "currency": "VND"}
        r1 = gw.check("payments", "1.0", "transfer", {**args, "amount_minor": 60_000_000},
                      {"caller_agent_id": "customer_service"})  # fmt: skip
        clock.advance(300)
        r2 = gw.check("payments", "1.0", "transfer", {**args, "amount_minor": 55_000_000},
                      {"caller_agent_id": "credit_prequal"})  # fmt: skip
    finally:
        gw.close()
    assert r1["allow"] and not r2["allow"]  # PAY-08 blocks inline; the monitor still sees it
    clock.advance(300)
    res = _monitor(adapters, evidence).run()
    assert len(res.cases_opened) == 1
    f = res.findings[0]
    assert f.total_minor == 115_000_000 and f.allowed_minor == 60_000_000


def test_config_from_settings() -> None:
    class S:
        multiagent_window_s = 60
        multiagent_limit_minor = 5

    cfg = SplitPaymentConfig.from_settings(S())
    assert (cfg.window_s, cfg.limit_minor) == (60, 5)


# --------------------------------------------------------------------- REQUIRE_CALLER_ID


@pytest.fixture
def make_gateway(adapters, evidence):
    deploy_policy(load_policy_dir(REPO_ROOT / "policies"), adapters.state, adapters.clock)
    made: list[Gateway] = []

    def _make(require: bool) -> Gateway:
        gw = Gateway(
            StorePolicyProvider(adapters.state, refresh_s=0),
            adapters.tables,
            adapters.state,
            evidence,
            adapters.clock,
            state_cache_ttl_s=0,
            require_caller_id=require,
        )
        made.append(gw)
        return gw

    yield _make
    for gw in made:
        gw.close()


TRANSFER = {"from_account_id": "ACC-7", "payee_id": "P-7", "amount_minor": 1_000_000}


def test_require_caller_id_off_is_unchanged(make_gateway) -> None:
    gw = make_gateway(False)
    r = gw.check("payments", "1.0", "transfer", TRANSFER, {"handoff": True})
    assert r["allow"] and r["rule_id"] != "GATE-NO-CALLER"


def test_require_caller_id_on_fails_closed_for_handoff_without_caller(make_gateway) -> None:
    gw = make_gateway(True)
    r = gw.check("payments", "1.0", "transfer", TRANSFER, {"handoff": True})
    assert not r["allow"] and r["action"] == "block" and r["rule_id"] == "GATE-NO-CALLER"
    r = gw.check("payments", "1.0", "transfer", TRANSFER,
                 {"handoff": True, "caller_agent_id": "  "})  # fmt: skip
    assert not r["allow"]
    # With the caller named, or not a handoff, or a read-only tool: normal path.
    r = gw.check("payments", "1.0", "transfer", TRANSFER,
                 {"handoff": True, "caller_agent_id": "customer_service"})  # fmt: skip
    assert r["allow"]
    assert gw.check("payments", "1.0", "transfer", TRANSFER, {})["allow"]
    r = gw.check("payments", "1.0", "get_balance", {"account_id": "ACC-7"}, {"handoff": True})
    assert r["allow"]


def test_late_ingested_event_is_not_lost(adapters, clock, evidence) -> None:
    """An event ingested after a run, with a ts just before that run, still counts."""
    ev = split_payment_events(T0 + timedelta(minutes=50), gap_s=570)  # 2nd at T0+59m30s
    adapters.tables.append("agent_event", as_rows(ev[:1]))
    clock.advance(3600)  # run at T0+60m; the spool still holds the 2nd event
    assert _monitor(adapters, evidence).run().cases_opened == []
    adapters.tables.append("agent_event", as_rows(ev[1:]))  # ingest catches up
    clock.advance(300)
    assert len(_monitor(adapters, evidence).run().cases_opened) == 1
