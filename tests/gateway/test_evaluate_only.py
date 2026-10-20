"""WP-UX3: ``Gateway.evaluate_only`` is a dry run with no side effect.

The store, the evidence sink, the agent state, the windows and the metrics are the same before and
after, and the decision equals what ``check`` gives (except for window rules, which a dry run
cannot evaluate)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.core.schema import load_model
from supervisor.gateway.engine import Gateway

from .conftest import MemoryEvidence
from .helpers import call

A1 = "ACC-0001"


def store_fingerprint(adapters: Adapters) -> str:
    """SHA-256 over every row of every table (state and append-only), in key order."""
    h = hashlib.sha256()
    for name in sorted(load_model().tables):
        rows = adapters.executor.query(f'SELECT * FROM "{name}"')
        rows = sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, default=str))
        h.update(name.encode())
        h.update(json.dumps(rows, sort_keys=True, default=str).encode())
    return h.hexdigest()


def snapshot(gw: Gateway, adapters: Adapters, evidence: MemoryEvidence) -> dict[str, Any]:
    return {
        "store": store_fingerprint(adapters),
        "evidence": len(evidence.entries),
        "metrics": json.dumps(gw.metrics.snapshot(), sort_keys=True, default=str),
        "windows": {t: len(v) for t, v in gw.windows.by_tool.items()},
        "warm": gw.windows.warm,
        "state": {a: gw.states.get_state(a) for a in ("payments", "customer_service")},
        "hint": sorted(gw._redact_hint),  # noqa: SLF001
    }


def test_dry_run_writes_nothing(
    gateway: Gateway, adapters: Adapters, evidence: MemoryEvidence
) -> None:
    call(gateway, "payments", "transfer", from_account_id=A1, payee_id="P1", amount_minor=10)
    gateway.drain()  # something exists to compare against
    before = snapshot(gateway, adapters, evidence)
    cases = [
        ("payments", "transfer", {"from_account_id": A1, "payee_id": "P1", "amount_minor": 10}),
        ("payments", "transfer", {"from_account_id": A1, "payee_id": "P1"}),  # PAY-01 block
        ("payments", "ext_transfer_api", {"amount_minor": 5}),  # PAY-07 pause
        ("payments", "transfer", {"from_account_id": A1, "amount_minor": 999_000_000}),
        ("nobody", "transfer", {}),  # unknown agent
        ("payments", "no_such_tool", {}),
    ]
    for agent, tool, args in cases:
        res = gateway.evaluate_only(agent, "1.0", tool, args, {"trace_id": "t-dry"})
        assert res["dry_run"] is True and "error" not in res, res
    gateway.drain()
    assert snapshot(gateway, adapters, evidence) == before


def test_dry_run_decision_equals_check(gateway: Gateway) -> None:
    dry = gateway.evaluate_only(
        "payments", "1.0", "transfer", {"from_account_id": A1, "payee_id": "P1"}, {}
    )
    real = call(gateway, "payments", "transfer", from_account_id=A1, payee_id="P1")
    for key in ("allow", "action", "rule_id", "reason", "risk_class", "policy_hash"):
        assert dry[key] == real[key], key
    assert [m["rule_id"] for m in dry["matched_rules"]] == [
        m["rule_id"] for m in real["matched_rules"]
    ]
    assert dry["decision_id"] is None and real["decision_id"]


def test_pause_rule_says_would_pause_and_the_agent_stays_running(gateway: Gateway) -> None:
    res = gateway.evaluate_only("payments", "1.0", "ext_transfer_api", {"amount_minor": 5}, {})
    assert res["action"] == "pause" and res["rule_id"] == "PAY-07"
    assert res["would_pause"] is True and res["agent_paused"] is False
    assert gateway.states.get_state("payments") == "RUNNING"
    # the real call pauses; a later dry run then reports the builtin block, not a rule
    call(gateway, "payments", "ext_transfer_api", amount_minor=5)
    assert gateway.states.get_state("payments") == "PAUSED"
    again = gateway.evaluate_only("payments", "1.0", "transfer", {"amount_minor": 1}, {})
    assert again["rule_id"] == "GATE-PAUSED" and again["builtin"] is True
    assert again["would_pause"] is False


def test_window_rules_are_not_evaluated_and_do_not_count(gateway: Gateway) -> None:
    res = gateway.evaluate_only(
        "payments",
        "1.0",
        "transfer",
        {"from_account_id": A1, "payee_id": "P1", "amount_minor": 90_000_000},
        {},
    )
    assert "PAY-03" in res["not_evaluated"]  # a sum over 24 h needs history
    # dry runs never feed the windows: 3 dry runs of 90M do not trip the 150M daily limit
    for _ in range(3):
        gateway.evaluate_only(
            "payments",
            "1.0",
            "transfer",
            {"from_account_id": A1, "payee_id": "P1", "amount_minor": 90_000_000},
            {},
        )
    real = call(
        gateway,
        "payments",
        "transfer",
        from_account_id=A1,
        payee_id="P1",
        amount_minor=90_000_000,
    )
    assert real["allow"] is True


def test_dry_run_does_not_count_in_metrics(gateway: Gateway) -> None:
    before = json.dumps(gateway.metrics.snapshot(), sort_keys=True, default=str)
    gateway.evaluate_only("payments", "1.0", "get_balance", {"account_id": A1}, {})
    assert json.dumps(gateway.metrics.snapshot(), sort_keys=True, default=str) == before


def test_dry_run_never_raises(gateway: Gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> Any:
        raise RuntimeError("policy store down")

    monkeypatch.setattr(gateway.policy, "current", boom)
    res = gateway.evaluate_only("payments", "1.0", "transfer", {}, {})
    assert res["dry_run"] is True and "RuntimeError" in res["error"]


def test_the_fingerprint_is_sensitive(
    gateway: Gateway, adapters: Adapters, evidence: MemoryEvidence
) -> None:
    """Guard for the test above: a real check does change the store and the evidence."""
    before = snapshot(gateway, adapters, evidence)
    call(gateway, "payments", "get_balance", account_id=A1)
    gateway.drain()
    after = snapshot(gateway, adapters, evidence)
    assert after["store"] != before["store"] and after["evidence"] == before["evidence"] + 1
    assert after["metrics"] != before["metrics"]


def test_slow_dry_run_times_out_and_never_takes_a_gate_worker(
    gateway: Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review WP-UX3: a dry run that hangs (for example a slow FactSource) gives the timeout
    message, and it runs on its own pool, so real checks still get a worker."""
    import threading
    import time

    release = threading.Event()

    def hang(*_a: Any, **_k: Any) -> dict[str, Any]:
        release.wait(10)
        return {"dry_run": True}

    monkeypatch.setattr(gateway, "_dry", hang)
    monkeypatch.setattr(gateway, "timeout_s", 0.2)
    try:
        for _ in range(10):  # more hung dry runs than the gate has workers (8)
            res = gateway.evaluate_only("payments", "1.0", "get_balance", {"account_id": A1}, {})
            assert res["dry_run"] is True and "no decision within" in res["error"]
        monkeypatch.setattr(gateway, "timeout_s", 2.0)
        t0 = time.perf_counter()
        real = call(gateway, "payments", "get_balance", account_id=A1)
        assert real["allow"] is True and real["fail_mode"] is None
        assert time.perf_counter() - t0 < 1.5
    finally:
        release.set()
