"""Seeded monitor scenarios from the synthetic data (tests and demos only).

* ``drift_weeks``: gateway events for one agent version: normal days, then drifted days.
  The drift changes the tool mix and the transfer amounts; every call is allowed, so no
  rule fires.
* ``loan_decisions``: credit pre-qualification decisions over synthetic loan applications,
  with an optional injected bias against one attribute value.
* ``split_payment_events``: transfers from one account to one payee, handed over by two
  different caller agents inside one hour.

Everything is invented (``supervisor.data.synthetic``); money is integer VND.
"""

from __future__ import annotations

import json
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from supervisor.core.models import AgentEvent
from supervisor.data.synthetic import LoanApplication, SyntheticGenerator
from supervisor.gateway.engine import key_hash

NORMAL_MIX = (("get_balance", 45), ("list_payees", 20), ("transfer", 35))
DRIFT_MIX = (("get_balance", 15), ("list_payees", 10), ("transfer", 75))


def _event(
    ts: datetime,
    agent_id: str,
    version: str,
    event_type: str,
    *,
    tool: str | None = None,
    amount: int | None = None,
    status: str = "allowed",
    latency_ms: int | None = None,
    caller: str | None = None,
    keys: dict[str, str] | None = None,
) -> AgentEvent:
    eid = uuid.uuid4().hex
    return AgentEvent(
        event_id=eid,
        ts=ts,
        trace_id=f"tr-{eid[:16]}",
        span_id=eid[:16],
        agent_id=agent_id,
        agent_version=version,
        caller_agent_id=caller,
        event_type=event_type,  # type: ignore[arg-type]
        tool_name=tool,
        args_masked=json.dumps({"keys": keys or {}}, sort_keys=True) if keys else None,
        amount_minor=amount,
        currency="VND" if amount is not None else None,
        status=status,
        latency_ms=latency_ms,
        env="test",
        source="proxy",
        capture_level="digest",
    )


def drift_weeks(
    start: datetime,
    *,
    agent_id: str = "payments",
    version: str = "1.0.0",
    normal_days: int = 7,
    drift_days: int = 7,
    per_day: int = 120,
    seed: int = 7,
) -> list[AgentEvent]:
    """``normal_days`` of normal traffic, then ``drift_days`` of drifted traffic."""
    gen = SyntheticGenerator(seed)
    rng = random.Random(seed)  # noqa: S311 - synthetic test data
    accounts = gen.accounts(gen.customers(50))
    out: list[AgentEvent] = []
    for day in range(normal_days + drift_days):
        drifted = day >= normal_days
        mix = DRIFT_MIX if drifted else NORMAL_MIX
        tools = [t for t, _ in mix]
        weights = [w for _, w in mix]
        for i in range(per_day):
            ts = start + timedelta(days=day, seconds=(i * 86400) // per_day + rng.randrange(60))
            tool = rng.choices(tools, weights=weights, k=1)[0]
            amount = None
            if tool == "transfer":
                acct = rng.choice(accounts)
                cap = max(1_000_000, acct.balance_minor // 20)
                amount = (rng.randrange(1_000_000, min(cap, 40_000_000) + 1) // 1000) * 1000
                if drifted:
                    amount *= 4  # larger transfers, still under every single-call limit
            out.append(_event(ts, agent_id, version, "gate_decision", tool=tool, amount=amount,
                              latency_ms=rng.randrange(0, 3)))  # fmt: skip
            out.append(
                _event(ts, agent_id, version, "llm_call", latency_ms=rng.randrange(300, 900))
            )
    return out


@dataclass(frozen=True)
class LoanDecision:
    """One pre-qualification outcome. ``subject_id`` is the raw application id (synthetic)."""

    application: LoanApplication
    decision: str  # approve | refer | decline
    blocked: bool


def loan_decisions(
    n: int = 1200,
    *,
    seed: int = 11,
    bias: Callable[[LoanApplication], bool] | None = None,
    bias_drop_bp: int = 0,
) -> list[LoanDecision]:
    """Decisions by a simple score rule; ``bias`` marks applicants whose approvals are
    turned to declines with probability ``bias_drop_bp`` / 10000 (the injected bias)."""
    gen = SyntheticGenerator(seed)
    rng = random.Random(seed + 1)  # noqa: S311 - synthetic test data
    customers = gen.customers(n)
    out: list[LoanDecision] = []
    for app in gen.loan_applications(customers, n):
        approve = app.credit_score >= 560
        decision = "approve" if approve else ("refer" if app.credit_score >= 450 else "decline")
        if bias is not None and bias(app) and decision == "approve":
            if rng.randrange(10000) < bias_drop_bp:
                decision = "decline"
        blocked = rng.randrange(10000) < 200  # 2 % gate blocks, no bias
        out.append(LoanDecision(app, decision, blocked))
    return out


def loan_decision_events(
    decisions: list[LoanDecision],
    start: datetime,
    *,
    agent_id: str = "credit_prequal",
    version: str = "1.0.0",
) -> list[AgentEvent]:
    """Recorder-style ``tool_call`` events for ``decide_prequal`` (masked args JSON)."""
    out = []
    for i, d in enumerate(decisions):
        ev = _event(
            start + timedelta(seconds=30 * i),
            agent_id,
            version,
            "tool_call",
            tool="decide_prequal",
            amount=d.application.amount_minor,
            status="blocked" if d.blocked else "ok",
        )
        args = {"application_id": d.application.application_id, "decision": d.decision}
        out.append(ev.model_copy(update={"args_masked": json.dumps(args, sort_keys=True)}))
    return out


def split_payment_events(
    start: datetime,
    *,
    amounts: tuple[int, ...] = (60_000_000, 55_000_000),
    callers: tuple[str | None, ...] = ("customer_service", "credit_prequal"),
    agent_id: str = "payments",
    from_account: str = "ACC-0000000001",
    payee: str = "PAYEE-0001",
    gap_s: int = 600,
) -> list[AgentEvent]:
    """Gateway ``transfer`` decisions for one (account, payee), one per caller."""
    keys = {
        "from_account_id": key_hash("from_account_id", from_account),
        "payee_id": key_hash("payee_id", payee),
    }
    return [
        _event(
            start + timedelta(seconds=gap_s * i),
            agent_id,
            "1.0.0",
            "gate_decision",
            tool="transfer",
            amount=amt,
            caller=caller,
            keys=keys,
        )  # fmt: skip
        for i, (amt, caller) in enumerate(zip(amounts, callers, strict=True))
    ]


def as_rows(events: list[AgentEvent]) -> list[dict[str, Any]]:
    return [e.row() for e in events]


__all__ = [
    "LoanDecision",
    "as_rows",
    "drift_weeks",
    "loan_decision_events",
    "loan_decisions",
    "split_payment_events",
]
