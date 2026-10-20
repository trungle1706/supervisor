"""Tool analytics (WP22): a daily rollup of gate decisions per agent, tool and UTC day.

Source: ``agent_event`` rows with ``event_type = 'gate_decision'`` (one per gate decision) and
``verdict`` rows labelled ``rule_error``. Target: ``tool_usage_daily`` (state table, one row
per ``usage_date, agent_id, tool_name``, overwritten when a day is recomputed).

The computation is deterministic and integer only. Database work is grouped SQL, so no event
row is loaded into memory: counts and first/last seen come from one GROUP BY, the latency
percentiles come from a histogram (``latency_us, count`` per group, exact nearest-rank), and
the work runs in chunks of ``CHUNK_DAYS`` days. Hashed ids are counted, never stored.

Run: python -m supervisor.analytics.tools rollup [--days N | --from D --to D | --backfill]
     python -m supervisor.analytics.tools report [--agent ID] [--days N] [--as-of D]
     python -m supervisor.analytics.tools suggest [--agent ID] [--days N] [--as-of D] [--out DIR]
Also callable in-process (scheduler): ``run(ctx, settings)``.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import logging  # noqa: E402
import sys  # noqa: E402
from collections import defaultdict  # noqa: E402
from collections.abc import Iterable, Mapping, Sequence  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from datetime import UTC, date, datetime, timedelta  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.config import Settings  # noqa: E402
from supervisor.core.errors import ConcurrencyError, DuplicateKeyError, SupervisorError  # noqa: E402
from supervisor.monitors.common import MonitorContext, as_dt  # noqa: E402

log = logging.getLogger("supervisor.analytics.tools")
TABLE = "tool_usage_daily"
CHUNK_DAYS = 7  # days per database round trip (bounds the histogram held in memory)
RISK_ORDER = ("money", "credit", "pii_export", "read_only", "unknown")
UNKNOWN_RISK = "unknown"
# Columns compared to decide whether a stored day changed (computed_at is not one of them).
VALUE_COLUMNS = (
    "risk_class",
    "calls",
    "allows",
    "blocks",
    "pauses",
    "errors",
    "p50_us",
    "p95_us",
    "distinct_callers",
    "distinct_users",
    "first_seen",
    "last_seen",
)


class AnalyticsError(SupervisorError):
    """Bad input to the analytics module (HTTP 400 / CLI [FAIL])."""


# --------------------------------------------------------------------------- statistics


def percentile_from_histogram(hist: Iterable[tuple[int, int]], p: int) -> int | None:
    """Nearest-rank percentile of a histogram of ``(value, count)`` pairs (same definition as
    ``monitors.common.percentile`` on the expanded list). None when the histogram is empty."""
    if not 0 < p <= 100:
        raise ValueError("p must be in 1..100")
    pairs = sorted((int(v), int(n)) for v, n in hist if n > 0)
    total = sum(n for _, n in pairs)
    if total == 0:
        return None
    rank = (p * total + 99) // 100
    seen = 0
    for value, n in pairs:
        seen += n
        if seen >= rank:
            return value
    return pairs[-1][0]  # unreachable: seen reaches total >= rank


# --------------------------------------------------------------------------- SQL


def _day_expr(dialect: str, col: str) -> str:
    if dialect == "sqlite":
        return f"substr({col}, 1, 10)"
    return f"date_format(to_utc_timestamp({col}, current_timezone()), 'yyyy-MM-dd')"


def _user_expr(dialect: str) -> str:
    # The gate stores HMAC hashes of grouping ids as {"keys": {"customer_id": "<hash>"}}.
    if dialect == "sqlite":
        return (
            "CASE WHEN json_valid(args_masked) THEN "
            "json_extract(args_masked, '$.keys.customer_id') END"
        )
    return "get_json_object(args_masked, '$.keys.customer_id')"


@dataclass
class _Group:
    """Accumulator for one (day, agent, tool)."""

    calls: int = 0
    allows: int = 0
    pauses: int = 0
    errors: int = 0
    callers: int = 0
    users: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    hist: dict[int, int] = field(default_factory=lambda: defaultdict(int))


def _scan(
    ctx: MonitorContext, ts_from: datetime, ts_to: datetime
) -> dict[tuple[str, str, str], _Group]:
    """Three grouped queries over ``ts_from <= ts < ts_to``; result keyed (day, agent, tool)."""
    x = ctx.executor
    dialect = x.dialect
    ev = x.qualify("agent_event")
    vd = x.qualify("verdict")
    day = _day_expr(dialect, "ts")
    params = {"r_from": ts_from, "r_to": ts_to}
    ptypes = {"r_from": "timestamp", "r_to": "timestamp"}
    where = (
        "event_type = 'gate_decision' AND tool_name IS NOT NULL AND ts >= :r_from AND ts < :r_to"
    )
    groups: dict[tuple[str, str, str], _Group] = defaultdict(_Group)

    rows = x.query(
        f"SELECT agent_id, tool_name, {day} AS d, COUNT(*) AS calls, "  # noqa: S608 - names from model.yaml
        "SUM(CASE WHEN status = 'allowed' THEN 1 ELSE 0 END) AS allows, "
        "SUM(CASE WHEN status = 'denied' AND classification = 'pause' "
        "THEN 1 ELSE 0 END) AS pauses, "
        "COUNT(DISTINCT caller_agent_id) AS callers, "
        f"COUNT(DISTINCT {_user_expr(dialect)}) AS users, "
        "MIN(ts) AS first_seen, MAX(ts) AS last_seen "
        f"FROM {ev} WHERE {where} GROUP BY agent_id, tool_name, {day}",
        params,
        column_types={
            "agent_id": "string",
            "tool_name": "string",
            "d": "string",
            "calls": "int",
            "allows": "int",
            "pauses": "int",
            "callers": "int",
            "users": "int",
            "first_seen": "timestamp",
            "last_seen": "timestamp",
        },
        param_types=ptypes,
    )
    for r in rows:
        g = groups[(str(r["d"]), r["agent_id"], r["tool_name"])]
        g.calls = int(r["calls"] or 0)
        g.allows = int(r["allows"] or 0)
        g.pauses = int(r["pauses"] or 0)
        g.callers = int(r["callers"] or 0)
        g.users = int(r["users"] or 0)
        g.first_seen, g.last_seen = r["first_seen"], r["last_seen"]

    # Latency histogram: exact percentiles without loading the events.
    lat = "COALESCE(latency_us, latency_ms * 1000)"
    rows = x.query(
        f"SELECT agent_id, tool_name, {day} AS d, {lat} AS lat, COUNT(*) AS n "  # noqa: S608
        f"FROM {ev} WHERE {where} AND {lat} IS NOT NULL "
        f"GROUP BY agent_id, tool_name, {day}, {lat}",
        params,
        column_types={
            "agent_id": "string",
            "tool_name": "string",
            "d": "string",
            "lat": "int",
            "n": "int",
        },
        param_types=ptypes,
    )
    for r in rows:
        key = (str(r["d"]), r["agent_id"], r["tool_name"])
        if key in groups:
            groups[key].hist[int(r["lat"])] += int(r["n"])

    # Decisions where a rule raised (its own fail mode decided the outcome).
    eday = _day_expr(dialect, "e.ts")
    rows = x.query(
        f"SELECT e.agent_id AS agent_id, e.tool_name AS tool_name, {eday} AS d, "  # noqa: S608
        "COUNT(DISTINCT e.event_id) AS errs "
        f"FROM {vd} v JOIN {ev} e ON e.event_id = v.event_id "
        "WHERE v.label = 'rule_error' AND e.event_type = 'gate_decision' "
        "AND e.tool_name IS NOT NULL AND e.ts >= :r_from AND e.ts < :r_to "
        f"GROUP BY e.agent_id, e.tool_name, {eday}",
        params,
        column_types={"agent_id": "string", "tool_name": "string", "d": "string", "errs": "int"},
        param_types=ptypes,
    )
    for r in rows:
        key = (str(r["d"]), r["agent_id"], r["tool_name"])
        if key in groups:
            groups[key].errors = int(r["errs"] or 0)
    return groups


def _row_from_group(
    key: tuple[str, str, str], g: _Group, risk: Mapping[str, str]
) -> dict[str, Any]:
    d, agent_id, tool = key
    return {
        "usage_date": date.fromisoformat(d),
        "agent_id": agent_id,
        "tool_name": tool,
        "risk_class": risk.get(tool, UNKNOWN_RISK),
        "calls": g.calls,
        "allows": g.allows,
        "blocks": g.calls - g.allows - g.pauses,
        "pauses": g.pauses,
        "errors": g.errors,
        "p50_us": percentile_from_histogram(g.hist.items(), 50),
        "p95_us": percentile_from_histogram(g.hist.items(), 95),
        "distinct_callers": g.callers,
        "distinct_users": g.users,
        "first_seen": g.first_seen,
        "last_seen": g.last_seen,
    }


# --------------------------------------------------------------------------- risk classes


def risk_classes(policy_dir: Any = None) -> dict[str, str]:
    """Tool name -> risk class: the policy ``tools`` catalogue first, then every manifest.
    A tool in neither is reported with risk class ``unknown`` (fail-closed in the gate)."""
    from pathlib import Path

    from supervisor.config import REPO_ROOT
    from supervisor.gateway.policy import PolicyError, load_policy_dir

    out: dict[str, str] = {}
    try:
        out.update(load_policy_dir(Path(policy_dir or REPO_ROOT / "policies")).doc.tools)
    except (PolicyError, OSError):
        pass
    try:
        from supervisor_agents.common.manifest import PACKAGE_DIR, load_manifest

        for d in sorted(PACKAGE_DIR.iterdir()):
            if (d / "manifest.yaml").is_file():
                for t in load_manifest(d.name).tools:
                    out.setdefault(t.name, t.risk_class)
    except Exception:  # noqa: BLE001 - a broken demo manifest must not stop the rollup
        log.warning("tool analytics: could not read agent manifests")
    return out


# --------------------------------------------------------------------------- rollup


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def compute_rows(
    ctx: MonitorContext, start: date, end: date, risk: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Rollup rows for the UTC days ``start..end`` inclusive, sorted by key. Reads in chunks."""
    if end < start:
        raise AnalyticsError("end day is before start day")
    out: list[dict[str, Any]] = []
    days = _days(start, end)
    for i in range(0, len(days), CHUNK_DAYS):
        chunk = days[i : i + CHUNK_DAYS]
        groups = _scan(ctx, _day_start(chunk[0]), _day_start(chunk[-1] + timedelta(days=1)))
        out.extend(_row_from_group(k, g, risk) for k, g in groups.items())
    out.sort(key=lambda r: (r["usage_date"], r["agent_id"], r["tool_name"]))
    return out


def _same(old: Mapping[str, Any], new: Mapping[str, Any]) -> bool:
    for c in VALUE_COLUMNS:
        a, b = old.get(c), new.get(c)
        if c in ("first_seen", "last_seen"):
            a = as_dt(a) if a is not None else None
            b = as_dt(b) if b is not None else None
        if a != b:
            return False
    return True


def _write(
    ctx: MonitorContext, rows: Sequence[dict[str, Any]], days: Sequence[date]
) -> dict[str, int]:
    """Insert new rows, update changed rows, leave equal rows alone (rerun = zero writes)."""
    stats = {"inserted": 0, "updated": 0, "unchanged": 0}
    existing: dict[tuple[date, str, str], dict[str, Any]] = {}
    for d in days:
        for r in ctx.state.query(TABLE, {"usage_date": d}):
            existing[(d, r["agent_id"], r["tool_name"])] = r
    now = ctx.clock.now()
    for row in rows:
        key = {k: row[k] for k in ("usage_date", "agent_id", "tool_name")}
        old = existing.get((row["usage_date"], row["agent_id"], row["tool_name"]))
        data = {**row, "computed_at": now}
        for attempt in range(3):
            try:
                if old is None:
                    ctx.state.insert(TABLE, data)
                    stats["inserted"] += 1
                elif _same(old, row):
                    stats["unchanged"] += 1
                else:
                    changes = {k: v for k, v in data.items() if k not in key}
                    ctx.state.update(TABLE, key, changes, old["row_version"])
                    stats["updated"] += 1
                break
            except (ConcurrencyError, DuplicateKeyError):
                if attempt == 2:
                    raise
                old = ctx.state.get(TABLE, key)
    return stats


def rollup(
    ctx: MonitorContext, start: date, end: date, *, policy_dir: Any = None
) -> dict[str, Any]:
    """Recompute ``tool_usage_daily`` for the UTC days ``start..end`` inclusive."""
    rows = compute_rows(ctx, start, end, risk_classes(policy_dir))
    stats = _write(ctx, rows, _days(start, end))
    return {"from": start.isoformat(), "to": end.isoformat(), "rows": len(rows), **stats}


def run(
    ctx: MonitorContext, settings: Settings, *, days: int = 2, today: date | None = None
) -> dict[str, Any]:
    """Scheduler entry: recompute the last ``days`` days (default yesterday and today), then
    write the least-privilege suggestion files. Suggestions are files only, never applied."""
    today = today or ctx.clock.now().astimezone(UTC).date()
    out = rollup(ctx, today - timedelta(days=days - 1), today)
    from supervisor.analytics import tools_suggest

    out["suggestions"] = tools_suggest.write_all(ctx, settings, as_of=today)
    return out


def earliest_event_day(ctx: MonitorContext) -> date | None:
    x = ctx.executor
    rows = x.query(
        f"SELECT MIN(ts) AS t FROM {x.qualify('agent_event')} WHERE event_type = 'gate_decision'",  # noqa: S608
        column_types={"t": "timestamp"},
    )
    t = rows[0]["t"] if rows else None
    return as_dt(t).date() if t is not None else None


# --------------------------------------------------------------------------- read side


def load_daily(
    ctx_state: Any,
    *,
    agent_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[dict[str, Any]]:
    """Stored rollup rows, newest day first then agent and tool. Dates are inclusive."""
    where = {"agent_id": agent_id} if agent_id else None
    rows = ctx_state.query(TABLE, where, order_by=("-usage_date", "agent_id", "tool_name"))
    out = []
    for r in rows:
        d = r["usage_date"]
        d = d if isinstance(d, date) and not isinstance(d, datetime) else as_dt(d).date()
        if (start and d < start) or (end and d > end):
            continue
        out.append({**r, "usage_date": d})
    return out


def window_bounds(as_of: date, days: int) -> tuple[date, date]:
    """The window of ``days`` UTC days ending at ``as_of`` (inclusive on both ends)."""
    if days < 1:
        raise AnalyticsError("window days must be 1 or more")
    return as_of - timedelta(days=days - 1), as_of


def summarise(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Fold daily rows into one row per (agent, tool) over the rows given.

    p50 is the call-weighted median of the daily p50 values; p95 is the worst daily p95
    (a percentile of percentiles is not exact, so the table says "worst day"). Distinct
    counts are the largest single-day value (distinct counts do not add across days).
    """
    acc: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        a = acc.setdefault(
            (r["agent_id"], r["tool_name"]),
            {
                "agent_id": r["agent_id"],
                "tool_name": r["tool_name"],
                "risk_class": r.get("risk_class") or UNKNOWN_RISK,
                "calls": 0,
                "allows": 0,
                "blocks": 0,
                "pauses": 0,
                "errors": 0,
                "p95_us": None,
                "callers_max": 0,
                "users_max": 0,
                "first_seen": None,
                "last_seen": None,
                "days_active": 0,
                "_p50": [],
            },
        )
        for c in ("calls", "allows", "blocks", "pauses", "errors"):
            a[c] += int(r[c] or 0)
        if r.get("p95_us") is not None:
            a["p95_us"] = max(a["p95_us"] or 0, int(r["p95_us"]))
        if r.get("p50_us") is not None:
            a["_p50"].append((int(r["p50_us"]), int(r["calls"] or 0)))
        a["callers_max"] = max(a["callers_max"], int(r["distinct_callers"] or 0))
        a["users_max"] = max(a["users_max"], int(r["distinct_users"] or 0))
        a["days_active"] += 1
        fs = as_dt(r["first_seen"]) if r.get("first_seen") is not None else None
        ls = as_dt(r["last_seen"]) if r.get("last_seen") is not None else None
        if fs and (a["first_seen"] is None or fs < a["first_seen"]):
            a["first_seen"] = fs
        if ls and (a["last_seen"] is None or ls > a["last_seen"]):
            a["last_seen"] = ls
        if r.get("risk_class") and a["risk_class"] == UNKNOWN_RISK:
            a["risk_class"] = r["risk_class"]
    out = []
    for a in acc.values():
        pairs = sorted(a.pop("_p50"))
        a["p50_us"] = percentile_from_histogram(pairs, 50) if pairs else None
        out.append(a)
    out.sort(
        key=lambda a: (a["agent_id"], _risk_rank(a["risk_class"]), -a["calls"], a["tool_name"])
    )
    return out


def _risk_rank(risk: str | None) -> int:
    return RISK_ORDER.index(risk) if risk in RISK_ORDER else len(RISK_ORDER)


# --------------------------------------------------------------------------- report text


def _fmt(v: Any) -> str:
    return "-" if v is None else str(v)


def _day(v: Any) -> str:
    return "-" if v is None else as_dt(v).strftime("%Y-%m-%d")


def format_report(summary: Sequence[Mapping[str, Any]], *, start: date, end: date) -> str:
    """ASCII table per agent (one screen each)."""
    lines = [
        f"Tool usage {start.isoformat()} .. {end.isoformat()} (UTC, {(end - start).days + 1} days)"
    ]
    by_agent: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in summary:
        by_agent[r["agent_id"]].append(r)
    if not by_agent:
        lines.append(
            "(no rollup rows in this window; run: python -m supervisor.analytics.tools rollup)"
        )
    head = (
        f"{'tool':<20} {'risk':<10} {'calls':>7} {'allow':>7} {'block':>6} {'pause':>6} "
        f"{'err':>5} {'p50us':>7} {'p95us':>7} {'usr':>4} {'last seen':>10}"
    )
    for agent, rows in sorted(by_agent.items()):
        lines += ["", f"agent {agent}", head]
        for r in rows:
            lines.append(
                f"{r['tool_name'][:20]:<20} {r['risk_class'][:10]:<10} {r['calls']:>7} "
                f"{r['allows']:>7} {r['blocks']:>6} {r['pauses']:>6} {r['errors']:>5} "
                f"{_fmt(r['p50_us']):>7} {_fmt(r['p95_us']):>7} {r['users_max']:>4} "
                f"{_day(r['last_seen']):>10}"
            )
    return "\n".join(lines)


# --------------------------------------------------------------------------- CLI


def _parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {text}") from exc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m supervisor.analytics.tools",
        description="Tool analytics and least-privilege suggestion (WP22).",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rollup", help="recompute tool_usage_daily from stored gate decisions")
    r.add_argument("--days", type=int, default=2, help="last N UTC days (default 2)")
    r.add_argument("--from", dest="start", type=_parse_day, default=None)
    r.add_argument("--to", dest="end", type=_parse_day, default=None)
    r.add_argument("--backfill", action="store_true", help="from the first gate decision")
    for name, text in (
        ("report", "print usage per agent and tool"),
        ("suggest", "write the least-privilege suggestion (never applied)"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("--agent", default=None)
        p.add_argument(
            "--days", type=int, default=None, help="window (default TOOL_ANALYTICS_WINDOW_DAYS)"
        )
        p.add_argument("--as-of", type=_parse_day, default=None, help="last day of the window")
    s = sub.choices["suggest"]
    s.add_argument("--out", default=None, help="folder for the suggestion files")
    args = ap.parse_args(argv)

    from supervisor.analytics import tools_suggest
    from supervisor.monitors.jobctx import ascii_line, standalone

    try:
        with standalone() as (settings, _, ctx):
            today = ctx.clock.now().astimezone(UTC).date()
            if args.cmd == "rollup":
                end = args.end or today
                if args.backfill:
                    start = earliest_event_day(ctx) or end
                else:
                    start = args.start or end - timedelta(days=max(args.days, 1) - 1)
                out = rollup(ctx, start, end)
                print(
                    ascii_line(
                        f"[OK] tool rollup {out['from']}..{out['to']}: {out['rows']} rows "
                        f"({out['inserted']} new, {out['updated']} updated, "
                        f"{out['unchanged']} same)"
                    )
                )
                return 0
            as_of = args.as_of or today
            days = args.days or settings.tool_analytics_window_days
            start, end = window_bounds(as_of, days)
            if args.cmd == "report":
                rows = load_daily(ctx.state, agent_id=args.agent, start=start, end=end)
                print(ascii_line(format_report(summarise(rows), start=start, end=end)))
                return 0
            out_dir = args.out or settings.tool_analytics_dir
            result = tools_suggest.write_all(
                ctx, settings, as_of=as_of, days=days, agent_id=args.agent, out_dir=out_dir
            )
            for line in result["text"]:
                print(ascii_line(line))
            for path in result["files"]:
                print(ascii_line(f"[OK] wrote {path}"))
            print(
                ascii_line("[OK] suggestion only: nothing was changed. See docs/tool-analytics.md")
            )
            return 0
    except (SupervisorError, ValueError) as exc:
        print(ascii_line(f"[FAIL] tool analytics: {exc}"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
