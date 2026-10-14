"""Tier 0a latency bench (ADR D02): 20 rules, 2,000 checks, in-process, SQLite store.

Publishes p50/p95/p99 as integer microseconds. Each check includes the full path:
policy + agent state read, rule evaluation, verdict + agent_event append, evidence record.
Run alone: uv run python -m pytest -q -s tests/perf
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import build_adapters
from supervisor.config import load_settings
from supervisor.gateway.engine import GateMetrics, Gateway
from supervisor.gateway.policy import StaticPolicyProvider, load_policy_texts
from supervisor.jobs import bootstrap_schema
from tests.gateway.conftest import POLICY_DIR, T0, MemoryEvidence

N_CHECKS = 2_000
P99_BUDGET_US = 50_000

EXTRA_RULE = """
  - id: PERF-{i:02d}
    version: 1
    description: synthetic rule {i}
    agent_scope: [payments]
    when:
      tool: {{in: [internal_transfer, get_account_balance]}}
      all:
        - {{arg: channel, op: eq, value: "branch-{i}"}}
        - {{arg: memo, op: matches, value: "(?i)ref-{i}-[0-9]+"}}
    action: alert
    severity: low
    risk_class: read_only
    owner: perf
"""


def _policy_20_rules():  # type: ignore[no-untyped-def]
    base = (POLICY_DIR / "baseline.yaml").read_text(encoding="utf-8")
    n_base = base.count("\n  - id: ")
    extra = "".join(EXTRA_RULE.format(i=i) for i in range(20 - n_base))
    policy = load_policy_texts([("baseline.yaml", base + extra)])
    assert len(policy.rules) == 20
    return policy


@pytest.mark.perf
def test_gate_latency_p99_under_50ms(tmp_path: Path) -> None:
    clock = FixedClock(T0)
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data")
    adapters = build_adapters(settings, clock=clock)
    bootstrap_schema.run(settings, adapters)
    gw = Gateway(
        StaticPolicyProvider(_policy_20_rules()),
        adapters.tables,
        adapters.state,
        MemoryEvidence(),
        clock,
        tier0b_enabled=False,
    )
    rng = random.Random(7)
    gw.check("payments", "1", "get_customer", {"customer_id": "WARM"})
    gw.metrics = GateMetrics()
    decide_us: list[int] = []
    for i in range(N_CHECKS):
        clock.advance(1)
        cust = f"CUS-{rng.randrange(200):04d}"
        kind = i % 4
        if kind == 0:
            res = gw.check("payments", "1", "get_account_balance", {"customer_id": cust})
        elif kind == 1:
            res = gw.check(
                "payments",
                "1",
                "internal_transfer",
                {
                    "customer_id": cust,
                    "payee_id": f"P{rng.randrange(50)}",
                    "amount_minor": rng.randrange(1, 5_000_000),
                    "channel": "app",
                    "memo": f"ref-{i}",
                },
            )
        elif kind == 2:
            res = gw.check(
                "customer_service",
                "1",
                "waive_fee",
                {"customer_id": cust, "amount_minor": 10_000},
            )
        else:
            res = gw.check("credit_prequal", "1", "fetch_documents", {"application_id": f"A{i}"})
        decide_us.append(int(res["latency_us"]))
    snap = gw.metrics.snapshot()
    gw.close()
    adapters.close()
    lat = snap["latency_us"]
    print(
        f"\n[OK] gate end-to-end incl. SQLite writes, 20 rules, {snap['samples']} checks (us): "
        f"p50={lat['p50']} p95={lat['p95']} p99={lat['p99']} max={lat['max']}"
    )
    dec = sorted(decide_us)
    d50, d95, d99 = (GateMetrics.percentile(dec, p) for p in (50, 95, 99))
    print(f"[OK] decision only, before recording (us): p50={d50} p95={d95} p99={d99}")
    assert snap["samples"] == N_CHECKS
    assert all(isinstance(lat[k], int) for k in ("p50", "p95", "p99"))
    assert lat["p99"] < P99_BUDGET_US
