"""WP-L4 test helpers: a system with one supervised agent and synthetic evidence rows."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from supervisor.governance import duties_gap as dg
from supervisor.governance import duty_evidence as de
from supervisor.governance.register_v2 import duties as dut

from .conftest import Console, add_agent, draft

BANNER = "Not legal advice. Bank counsel must confirm."
CREATOR = "reviewer.an"
AGENT = "l4-agent"
NOW = dt.datetime(2026, 10, 28, 9, 0, tzinfo=dt.UTC)

# real RegKB obligations and the Supervisor controls they map to (non-process, coverage not none)
OB_GATE2 = "VN-DEC23-2025-A14-01"  # approved_tools, single_limit (both read gate decisions)
OB_MASK = "VN-CPL-2023-A15-01"  # pii_masking
OB_RULE = "VN-DATA-2024-A25.1-01"  # PII-02 (a gate rule)
OB_JUDGE = "VN-DATA-2024-A43.3-01"  # tier1_monitor (advisory: never works)
OB_MIXED = "VN-CYBER-2025-A18.2-01"  # injection_prefilter, tier1_monitor
OB_CHAIN = "VN-ETX-2023-A31-01"  # anchor, evidence_chain
OB_CONSOLE = "VN-PDPL-2025-A33.2-01"  # case_signoff (a console screen: unmeasured)


def kb(c: Console) -> Any:
    return dg.kb_of(c.ctx)


def env(c: Console) -> de.Env:
    return de.Env.from_console(c.ctx)


def system_with_agent(c: Console, agent: str = AGENT, gate: str = "RUNNING", **over: Any) -> str:
    add_agent(c.runtime.adapters, agent, gate_state=gate)
    s = c.ctx.systems.register(draft(**over), CREATOR)
    sid = str(s["system_id"])
    c.ctx.systems.link(sid, "agent", agent, CREATOR)
    return sid


def when(c: Console, hours: int = 3, days: int = 0) -> dt.datetime:
    return c.ctx.clock.now() - dt.timedelta(hours=hours, days=days)


def put_row(
    c: Console,
    sid: str,
    oid: str,
    *,
    coverage: str = "full",
    status: str = "open",
    applies: str = "yes",
    note: str | None = None,
    control: str | None = None,
) -> dict[str, Any]:
    ob = kb(c).get(oid)
    c.ctx.state.insert(
        "obligation_status",
        {
            "status_id": dut.status_id(sid, oid),
            "system_id": sid,
            "obligation_id": oid,
            "instrument_id": ob.instrument_id,
            "applies": applies,
            "coverage": coverage,
            "status": status,
            "owner_user": CREATOR,
            "due_date": None,
            "closing_control": control,
            "note": note or f"{BANNER} seeded",
            "created_at": NOW,
        },
    )
    return row(c, sid, oid)


def row(c: Console, sid: str, oid: str) -> dict[str, Any]:
    r = c.ctx.state.get("obligation_status", {"status_id": dut.status_id(sid, oid)})
    assert r is not None
    return dict(r)


def gate_events(c: Console, n: int, agent: str = AGENT, hours: int = 3, days: int = 0) -> None:
    c.ctx.tables.append(
        "agent_event",
        [
            {
                "event_id": uuid.uuid4().hex,
                "ts": when(c, hours, days),
                "trace_id": "t-" + uuid.uuid4().hex[:8],
                "span_id": uuid.uuid4().hex[:8],
                "agent_id": agent,
                "event_type": "gate_decision",
                "tool_name": "transfer",
                "status": "allowed",
                "env": "test",
                "source": "gate",
                "capture_level": "full",
            }
            for _ in range(n)
        ],
    )


def verdicts(
    c: Console,
    n: int,
    *,
    agent: str = AGENT,
    rule: str | None = "PII-02",
    tier: int = 0,
    mock: bool = False,
    label: str = "matched",
    action: str = "block",
) -> None:
    c.ctx.tables.append(
        "verdict",
        [
            {
                "verdict_id": uuid.uuid4().hex,
                "ts": when(c),
                "trace_id": "t-" + uuid.uuid4().hex[:8],
                "agent_id": agent,
                "tier": tier,
                "checker_id": "gate.tier0a" if tier == 0 else "judge.x",
                "is_mock": mock,
                "advisory": tier != 0,
                "label": label,
                "action": action,
                "rule_id": rule,
            }
            for _ in range(n)
        ],
    )


def gap_task(c: Console, sid: str, instrument_id: str, cov: str) -> str:
    """The WP-L2 task of a group, written the way the register step writes it."""
    tasks = c.ctx.tasks
    trow = tasks._row_for(
        sid,
        "initiation",
        template_id=de.group_template(instrument_id, cov),
        kind="custom",
        title=f"Close duties of {instrument_id} ({cov})",
        owner_role="owner",
        required=False,
        due_days=14,
        evidence_kind="none",
        evidence_ref=f"{BANNER} ids",
        level="low",
        d33_class="unclassified",
        actor=CREATOR,
    )
    assert tasks._insert(trow, CREATOR)
    return str(trow["task_id"])
