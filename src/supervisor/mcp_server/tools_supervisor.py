"""Supervisor tools (WP-G6): scope ``supervisor.read``, read only.

The gate state, the decisions, the detector findings, the chain check and the assurance pack
results of an agent. The app sees an agent only when a person with its roles would see it in the
console (``SystemService.agents_in_scope``). Text is the masked text the tables hold; the tools
leave out the masked arguments and results of a call and return the rule, the outcome and the
masked rationale. Nothing here pauses, blocks or releases an agent.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from supervisor.core.errors import SupervisorError
from supervisor.mcp_server.common import LIMIT_SPEC, limit_of, pick, plain, visible_agent
from supervisor.mcp_server.registry import Registry, Tool

STOP_ACTIONS = ("block", "pause")
SCAN_CAP = 2000
RATIONALE_CHARS = 300


def _since(a: dict[str, Any]) -> dt.datetime | None:
    raw = a.get("since")
    if not raw:
        return None
    try:
        out = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        raise SupervisorError(
            "since must be an RFC 3339 time, for example 2026-10-22T00:00:00Z"
        ) from None
    return out if out.tzinfo else out.replace(tzinfo=dt.UTC)


def _ts(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    if isinstance(value, str) and value:
        try:
            out = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return out if out.tzinfo else out.replace(tzinfo=dt.UTC)
    return None


def gate_state(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    agent = visible_agent(call, a["agent_id"])
    desc = call.ctx.gateway.states.describe(agent)
    pending = desc.get("pending_resume") or []
    return {
        "agent_id": agent,
        "state": desc["state"],
        "pending_resume": [pick(p, ("role", "principal", "ts")) for p in pending],
    }


def decisions(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    agent = visible_agent(call, a["agent_id"])
    since = _since(a)
    tables = call.ctx.tables
    events = tables.query(
        "agent_event",
        {"agent_id": agent, "event_type": "gate_decision"},
        order_by=("-ts",),
        limit=SCAN_CAP,
    )
    out = []
    for e in events:
        ts = _ts(e["ts"])
        if since is not None and (ts is None or ts < since):
            continue
        verdicts = tables.query("verdict", {"event_id": e["event_id"]})
        stops = [
            v
            for v in verdicts
            if int(v["tier"]) == 0 and v["action"] in STOP_ACTIONS and not v["advisory"]
        ]
        stop = min(stops, key=lambda v: v["action"] != "pause") if stops else None
        outcome = (
            ("paused" if stop["action"] == "pause" else "blocked")
            if stop
            else ("allowed" if e.get("status") == "allowed" else str(e.get("status") or "-"))
        )
        out.append(
            {
                "event_id": e["event_id"],
                "ts": plain(e["ts"]),
                "tool": e.get("tool_name") or "-",
                "outcome": outcome,
                "rule_id": stop.get("rule_id") if stop else None,
                "rationale_masked": (stop.get("rationale_masked") or "")[:RATIONALE_CHARS]
                if stop
                else None,
                "verdict_status": e.get("verdict_status"),
                "advisory": [
                    {"checker": v["checker_id"], "label": v["label"], "mock": bool(v["is_mock"])}
                    for v in verdicts
                    if v["advisory"]
                ][:5],
            }
        )
        if len(out) >= limit_of(a):
            break
    return {"agent_id": agent, "count": len(out), "items": out}


def findings(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    agent = visible_agent(call, a["agent_id"])
    since = _since(a)
    rows = call.ctx.tables.query("finding", {"agent_id": agent}, order_by=("-ts",), limit=SCAN_CAP)
    keys = (
        "finding_id",
        "ts",
        "event_id",
        "tool_name",
        "direction",
        "detector_slug",
        "code",
        "score_bp",
        "threshold_bp",
        "masked_count",
        "action_hint",
        "not_executed_reason",
        "verdict_status",
        "is_mock",
        "entities_masked",
        "fragments_masked",
    )
    out = []
    for r in rows:
        ts = _ts(r["ts"])
        if since is not None and (ts is None or ts < since):
            continue
        out.append(pick(r, keys))
        if len(out) >= limit_of(a):
            break
    return {"agent_id": agent, "count": len(out), "items": out}


def chain_verify(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    from supervisor.console import auditpack

    agent = visible_agent(call, a["agent_id"])
    res = auditpack.verify_chain(call.ctx, f"agent:{agent}")
    return {
        "agent_id": agent,
        "ok": bool(res["ok"]),
        "failures": int(res["failures"]),
        "lane": res["lane"],
        "ts": plain(res["ts"]),
        "last_lines": [str(x)[:200] for x in res["lines"] if str(x).startswith("[")][-10:],
    }


def pack_results(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    agent = visible_agent(call, a["agent_id"])
    rows = call.ctx.tables.query(
        "eval_result",
        {"target_kind": "agent", "target_id": agent},
        order_by=("-ts",),
        limit=SCAN_CAP,
    )
    latest: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = (str(r["pack_id"]), bool(r["is_mock"]))
        latest.setdefault(f"{key[0]}|{int(key[1])}", r)
    items = [
        pick(
            r,
            (
                "pack_id",
                "pack_version",
                "dimension",
                "status",
                "ts",
                "run_id",
                "n_items",
                "is_mock",
                "launch_gate",
                "metrics",
                "metric_status",
            ),
        )
        for r in latest.values()
    ]
    items.sort(key=lambda r: (r["pack_id"], r["is_mock"]))
    return {"agent_id": agent, "count": len(items), "items": items[: limit_of(a)]}


AGENT = {"type": "string", "maxLength": 128}
SINCE = {"type": "string", "maxLength": 40}


def register(reg: Registry) -> None:
    def tool(
        name: str,
        text: str,
        fn: Any,
        props: dict[str, Any],
        required: list[str],
        permission: str | None = None,
    ) -> None:
        schema = {"properties": props, "required": required}
        reg.register(Tool(name, text, "supervisor.read", schema, fn, permission=permission))

    tool(
        "gate_state",
        "The gate state of an agent (RUNNING, SHADOW, PAUSED or QUARANTINED) and who has "
        "already approved a resume.",
        gate_state,
        {"agent_id": AGENT},
        ["agent_id"],
    )
    tool(
        "decisions",
        "Newest gate decisions of an agent: tool, outcome, rule and masked rationale. since is "
        "an RFC 3339 time.",
        decisions,
        {"agent_id": AGENT, "since": SINCE, "limit": LIMIT_SPEC},
        ["agent_id"],
    )
    tool(
        "findings",
        "Newest detector findings of an agent, masked text only.",
        findings,
        {"agent_id": AGENT, "since": SINCE, "limit": LIMIT_SPEC},
        ["agent_id"],
    )
    tool(
        "chain_verify",
        "Verify the evidence lane of an agent offline and return the result (the same check as "
        "the console).",
        chain_verify,
        {"agent_id": AGENT},
        ["agent_id"],
        permission="chain.verify",
    )
    tool(
        "pack_results",
        "The newest assurance pack result per pack for an agent (mock runs are labelled).",
        pack_results,
        {"agent_id": AGENT, "limit": LIMIT_SPEC},
        ["agent_id"],
    )
