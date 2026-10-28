"""Post-deploy assessment (WP-O5, phase 9, flag ``ONBOARD_POSTDEPLOY``).

What the gate, the judges, the monitors and the packs say about an agent after it was attached:
one read of the Supervisor tables over a window (default 7 days). No model call, no write, no
network. Every number is an integer (counts, basis points are not needed here). Text fields hold
ids, codes and fixed words only; no argument, no masked excerpt, no rationale leaves the stores.

``assess(ctx, agent_id, days=7)`` returns::

    {agent_id, days, since, mode,                  mode: shadow | running | other state | none
     gate:     {checks, allowed, blocked, paused, would_block,
                by_rule: [{rule_id, would_block, blocked}] top 5},
     judges:   {tiers: [{tier, count, flagged, mock_count, mock_flagged}],
                count, flagged, mock_count, mock_flagged},
     drift:    {drift: {...} | None, session: {...} | None},   status rows of the monitors
     incidents:{open, opened, closed},
     packs:    [{pack_id, status, ts, n_items, is_mock}],      latest eval_result on traces
     timeline: [{ts, kind, text, ref}] newest first, at most 200,
     truncated}

A mock judge verdict is counted in ``mock_count`` and ``mock_flagged`` only, never in ``count``
or ``flagged``: a mock never looks like a real judge. A verdict is *flagged* when its label is not
``benign`` or its action is ``alert`` or ``open_case``.

The gate figures (checks, allowed, blocked, paused, would_block) are the ones of the Guardians
tab (``agent_guardians._gate_results``); ``by_rule`` reads the tier-0 verdict rows of the window
for the same agent.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from typing import Any

from supervisor.core.canonical import format_ts
from supervisor.core.errors import SupervisorError
from supervisor.evidence.chain import check_no_floats
from supervisor.onboard import agent_log

FLAG_TEXT = "the post-deploy assessment is off (ONBOARD_POSTDEPLOY=1 turns it on)"
DEFAULT_DAYS = 7
MAX_DAYS = 90
SCAN = 5000
TIMELINE_CAP = 200
PER_SOURCE = 200
TOP_RULES = 5
KINDS = ("verdict", "finding", "case", "incident", "eval_result", "state", "agent_log")
MONITORS = ("drift", "session")
OPEN_INCIDENT = ("open", "investigating")


class PostdeployError(SupervisorError):
    """A refused request. ``code`` is the stable machine word; the message starts with it."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code


def require_on(settings: Any) -> None:
    if not settings.onboard_postdeploy:
        raise PostdeployError("postdeploy_off", FLAG_TEXT)


def parse_days(raw: Any) -> int:
    if raw in (None, ""):
        return DEFAULT_DAYS
    try:
        days = int(str(raw))
    except ValueError:
        raise PostdeployError("bad_days", "days must be a whole number") from None
    if not 1 <= days <= MAX_DAYS:
        raise PostdeployError("bad_days", f"days must be between 1 and {MAX_DAYS}")
    return days


def _ts(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
    return None


def _in(rows: list[dict[str, Any]], column: str, since: dt.datetime) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        t = _ts(r.get(column))
        if t is not None and t >= since:
            out.append(r)
    return out


def _safe(text: Any, limit: int = 120) -> str:
    """One line cut to ``limit``. The texts here are built from ids, codes and fixed words (the
    agent log rows were scrubbed when they were written), so no masker runs per event."""
    return " ".join(str(text or "").split())[:limit]


def flagged(v: Mapping[str, Any]) -> bool:
    return str(v.get("label") or "") != "benign" or str(v.get("action") or "") in (
        "alert",
        "open_case",
    )


# ------------------------------------------------------------------------------ the parts


def _gate(ctx: Any, agent_id: str, since: dt.datetime, hits: list[bool]) -> dict[str, Any]:
    from supervisor.console import agent_guardians

    out = dict(agent_guardians._gate_results(ctx, agent_id, since))  # noqa: SLF001
    rows = ctx.tables.query(
        "verdict", {"agent_id": agent_id, "tier": 0}, order_by=("-ts",), limit=SCAN
    )
    hits.append(len(rows) >= SCAN)
    per: dict[str, dict[str, int]] = {}
    for v in _in(rows, "ts", since):
        rule = str(v.get("rule_id") or "-")
        if str(v.get("label") or "").startswith("shadow_would_"):
            per.setdefault(rule, {"would_block": 0, "blocked": 0})["would_block"] += 1
        elif not v.get("advisory") and v.get("action") in ("block", "pause"):
            per.setdefault(rule, {"would_block": 0, "blocked": 0})["blocked"] += 1
    top = sorted(per.items(), key=lambda kv: (-(kv[1]["would_block"] + kv[1]["blocked"]), kv[0]))
    out["by_rule"] = [{"rule_id": r, **c} for r, c in top[:TOP_RULES]]
    return out


def _judge_rows(
    ctx: Any, agent_id: str, since: dt.datetime, hits: list[bool]
) -> list[dict[str, Any]]:
    rows = ctx.tables.query("verdict", {"agent_id": agent_id}, order_by=("-ts",), limit=SCAN)
    hits.append(len(rows) >= SCAN)
    return [
        v
        for v in _in(rows, "ts", since)
        if int(v.get("tier") or 0) >= 1 and v.get("role") != "protocol"
    ]


def _judges(verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    tiers: dict[int, dict[str, int]] = {}
    for v in verdicts:
        t = tiers.setdefault(
            int(v["tier"]), {"count": 0, "flagged": 0, "mock_count": 0, "mock_flagged": 0}
        )
        hit = flagged(v)
        if v.get("is_mock"):
            t["mock_count"] += 1
            t["mock_flagged"] += 1 if hit else 0
        else:
            t["count"] += 1
            t["flagged"] += 1 if hit else 0
    rows = [{"tier": k, **tiers[k]} for k in sorted(tiers)]
    return {
        "tiers": rows,
        "count": sum(r["count"] for r in rows),
        "flagged": sum(r["flagged"] for r in rows),
        "mock_count": sum(r["mock_count"] for r in rows),
        "mock_flagged": sum(r["mock_flagged"] for r in rows),
    }


def _monitors(ctx: Any, agent_id: str) -> dict[str, Any]:
    """The newest status of the drift and the session monitor (``oversight_metric``)."""
    rows = ctx.tables.query(
        "oversight_metric", {"agent_id": agent_id}, order_by=("-metric_date",), limit=30
    )
    out: dict[str, Any] = {m: None for m in MONITORS}
    for r in rows:  # newest day first
        raw = r.get("monitor_status")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                raw = None
        if not isinstance(raw, Mapping):
            continue
        for m in MONITORS:
            entry = raw.get(m)
            if out[m] is None and isinstance(entry, Mapping) and entry.get("status"):
                out[m] = {
                    "status": _safe(entry.get("status"), 40),
                    "code": _safe(entry.get("code") or "", 60),
                    "n": int(entry.get("n") or 0),
                    "day": str(r["metric_date"]),
                }
    return out


def _incidents(ctx: Any, agent_id: str, since: dt.datetime) -> tuple[dict[str, int], list[dict]]:
    try:
        rows = [dict(r) for r in ctx.state.query("incident", {"agent_id": agent_id})]
    except Exception:  # noqa: BLE001 - a store without the table: no incidents
        rows = []
    opened = _in(rows, "opened_at", since)
    closed = [
        r
        for r in rows
        if r.get("status") in ("resolved", "closed") and _in([r], "closed_at", since)
    ]
    counts = {
        "open": sum(1 for r in rows if r.get("status") in OPEN_INCIDENT),
        "opened": len(opened),
        "closed": len(closed),
    }
    return counts, rows


def _packs(ctx: Any, agent_id: str) -> list[dict[str, Any]]:
    from supervisor.assurance.results import latest_results

    out = []
    for r in latest_results(ctx.tables, "traces", agent_id):
        t = _ts(r.get("ts"))
        out.append(
            {
                "pack_id": str(r["pack_id"]),
                "status": str(r["status"]),
                "ts": format_ts(t) if t else None,
                "n_items": int(r.get("n_items") or 0),
                "is_mock": bool(r.get("is_mock")),
            }
        )
    return out


# ------------------------------------------------------------------------------ the timeline


def _event(ts: Any, kind: str, text: str, ref: str) -> dict[str, Any] | None:
    t = _ts(ts)
    if t is None:
        return None
    return {"ts": format_ts(t), "kind": kind, "text": _safe(text, 200), "ref": _safe(ref, 120)}


def _timeline(
    ctx: Any,
    agent_id: str,
    since: dt.datetime,
    verdicts: list[dict[str, Any]],
    incident_rows: list[dict[str, Any]],
    hits: list[bool],
) -> list[dict[str, Any]]:
    found: list[dict[str, Any] | None] = []
    # verdicts: flagged judge verdicts, gate would-blocks and stops
    tier0 = ctx.tables.query(
        "verdict", {"agent_id": agent_id, "tier": 0}, order_by=("-ts",), limit=PER_SOURCE
    )
    for v in _in(tier0, "ts", since):
        label = str(v.get("label") or "")
        if label.startswith("shadow_would_") or (
            not v.get("advisory") and v.get("action") in ("block", "pause")
        ):
            found.append(
                _event(
                    v["ts"],
                    "verdict",
                    f"gate {v.get('action')}: rule {v.get('rule_id') or '-'} ({label})",
                    str(v["verdict_id"]),
                )
            )
    for v in [v for v in verdicts if flagged(v)][:PER_SOURCE]:
        mock = " (mock)" if v.get("is_mock") else ""
        found.append(
            _event(
                v["ts"],
                "verdict",
                f"judge tier {int(v['tier'])}{mock}: {v.get('label')} / {v.get('action')}",
                str(v["verdict_id"]),
            )
        )
    for f in _in(
        ctx.tables.query("finding", {"agent_id": agent_id}, order_by=("-ts",), limit=PER_SOURCE),
        "ts",
        since,
    ):
        mock = " (mock)" if f.get("is_mock") else ""
        found.append(
            _event(
                f["ts"],
                "finding",
                f"detector {f.get('detector_slug')}{mock}: {f.get('code')} "
                f"-> {f.get('action_hint')}",
                str(f["finding_id"]),
            )
        )
    try:
        cases = [dict(r) for r in ctx.state.query("cases", {"agent_id": agent_id})]
    except Exception:  # noqa: BLE001
        cases = []
    for c in _in(cases, "opened_at", since)[:PER_SOURCE]:
        found.append(
            _event(
                c["opened_at"],
                "case",
                f"case opened: {c.get('case_type') or 'case'}, severity {c.get('severity')}",
                str(c["case_id"]),
            )
        )
    for i in incident_rows:
        if _ts(i.get("opened_at")) and _in([i], "opened_at", since):
            found.append(
                _event(
                    i["opened_at"],
                    "incident",
                    f"incident opened: {i.get('kind')}, severity {i.get('severity')}",
                    str(i["incident_id"]),
                )
            )
        if i.get("closed_at") and _in([i], "closed_at", since):
            found.append(
                _event(
                    i["closed_at"], "incident", f"incident {i.get('status')}", str(i["incident_id"])
                )
            )
    for r in _in(
        ctx.tables.query(
            "eval_result", {"target_id": agent_id}, order_by=("-ts",), limit=PER_SOURCE
        ),
        "ts",
        since,
    ):
        mock = " (mock)" if r.get("is_mock") else ""
        found.append(
            _event(
                r["ts"],
                "eval_result",
                f"pack {r['pack_id']}{mock} on {r.get('target_kind')}: {r['status']}",
                str(r["run_id"]),
            )
        )
    try:
        controls = [dict(r) for r in ctx.state.query("gate_control", {"agent_id": agent_id})]
    except Exception:  # noqa: BLE001
        controls = []
    for g in _in(controls, "created_at", since)[:PER_SOURCE]:
        found.append(
            _event(
                g["created_at"],
                "state",
                f"gate {g.get('action')} ({g.get('status')})",
                str(g["control_id"]),
            )
        )
    for row in agent_log.rows(ctx, agent_id, PER_SOURCE):
        t = _ts(row["at"])
        if t is not None and t >= since:
            found.append(
                _event(
                    row["at"],
                    "agent_log",
                    f"{row['step']} ({row['by_kind']}): {row['what']}",
                    row["log_id"],
                )
            )
    events = [e for e in found if e is not None]
    events.sort(key=lambda e: (e["ts"], e["kind"], e["ref"]), reverse=True)
    return events[:TIMELINE_CAP]


# ------------------------------------------------------------------------------ the assessment


def assess(ctx: Any, agent_id: str, days: int = DEFAULT_DAYS) -> dict[str, Any]:
    """Read the Supervisor tables for ``agent_id`` over the last ``days`` days. Read only."""
    days = parse_days(days)
    now = ctx.clock.now()
    since = now - dt.timedelta(days=days)
    hits: list[bool] = []
    agent = ctx.state.get("agent", {"agent_id": agent_id})
    state = str((agent or {}).get("gate_state") or (agent or {}).get("status") or "")
    mode = state.lower() if state else "none"
    verdicts = _judge_rows(ctx, agent_id, since, hits)
    incidents, incident_rows = _incidents(ctx, agent_id, since)
    out = {
        "agent_id": agent_id,
        "days": days,
        "since": format_ts(since),
        "mode": mode,
        "gate": _gate(ctx, agent_id, since, hits),
        "judges": _judges(verdicts),
        "drift": _monitors(ctx, agent_id),
        "incidents": incidents,
        "packs": _packs(ctx, agent_id),
        "timeline": _timeline(ctx, agent_id, since, verdicts, incident_rows, hits),
        "truncated": any(hits),
    }
    check_no_floats(out)
    return out


__all__ = [
    "PostdeployError",
    "assess",
    "flagged",
    "parse_days",
    "require_on",
]
