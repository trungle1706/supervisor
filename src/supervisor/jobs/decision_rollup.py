"""Decision rollup (WP39): daily ``decision_daily`` rows from ``agent_event`` and ``finding``.

Run: python -m supervisor.jobs.decision_rollup [--days N | --from D --to D | --backfill]
Also callable in-process (scheduler): ``run(ctx, settings)``; on with CONSOLE_DECISIONS_V2=1,
every SCHED_DECISION_ROLLUP_S seconds.

Why: the Analytics Gate and Detectors tabs must not scan the raw event table on every page
load. This job reads it once per run with grouped SQL (never row by row, never text), and the
console reads the small daily table.

Dimensions (one row per UTC day, dimension, key, key2; counts are gate decisions):

=================  ============  =========  ==========================================
dimension          dim_key       dim_key2   meaning
=================  ============  =========  ==========================================
total              ``*``         ``*``      all decisions of the day
agent              agent id      ``*``      decisions of one agent
consumer           consumer id   ``*``      decisions of one calling application
rule               rule id       ``*``      decisions where the tier-0 rule matched
detector_code      detector      code       decisions with that finding (or that detector
                                            run that could not look: not_evaluated)
detector_latency   detector      ``*``      requests = timed runs; p50_us, p95_us
=================  ============  =========  ==========================================

Status per decision is ``verdict_status`` (verdict v2), or, on a row written without detectors,
``pause`` / ``block`` / ``allow`` from the old columns. ``not_evaluated`` counts decisions whose
coverage or detector rows say a part of the call was not inspected (not "not applicable").
Idempotent: a rerun over the same data writes nothing new.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
from collections import defaultdict  # noqa: E402
from collections.abc import Mapping, Sequence  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from datetime import UTC, date, datetime, timedelta  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.analytics.decisions import COVERAGE_GAP_REASONS, shown_id  # noqa: E402
from supervisor.analytics.tools import _day_expr, percentile_from_histogram  # noqa: E402
from supervisor.config import Settings  # noqa: E402
from supervisor.core.errors import ConcurrencyError, DuplicateKeyError, SupervisorError  # noqa: E402
from supervisor.monitors.common import MonitorContext, as_dt  # noqa: E402
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402

TABLE = "decision_daily"
CHUNK_DAYS = 7
KNOWN_DETECTORS = ("dlp_vn", "injection_regex", "judge_advisory")
_SLUG = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
VALUE_COLUMNS = (
    "requests",
    "allows",
    "reports",
    "transforms",
    "pauses",
    "blocks",
    "skips",
    "not_evaluated",
    "p50_us",
    "p95_us",
)
_STAR = "*"
_COUNT_OF = {
    "allow": "allows",
    "report": "reports",
    "transform": "transforms",
    "pause": "pauses",
    "block": "blocks",
    "skip": "skips",
}


@dataclass
class Counts:
    requests: int = 0
    allows: int = 0
    reports: int = 0
    transforms: int = 0
    pauses: int = 0
    blocks: int = 0
    skips: int = 0
    not_evaluated: int = 0
    p50_us: int | None = None
    p95_us: int | None = None

    def add(self, status: str, n: int, not_eval: int) -> None:
        self.requests += n
        col = _COUNT_OF.get(status, "allows")
        setattr(self, col, getattr(self, col) + n)
        if not_eval:
            self.not_evaluated += n


def status_sql(alias: str = "") -> str:
    """Decision status as SQL: the v2 column, else the old columns (pause / block / allow)."""
    p = f"{alias}." if alias else ""
    return (
        f"COALESCE({p}verdict_status, CASE WHEN {p}classification = 'pause' THEN 'pause' "
        f"WHEN {p}status = 'denied' THEN 'block' ELSE 'allow' END)"
    )


def not_evaluated_sql(alias: str, finding_table: str) -> str:
    """1 when the decision's coverage or a detector row says something was not inspected."""
    p = f"{alias}." if alias else ""
    likes = " OR ".join(f'{p}coverage_json LIKE \'%"reason":"{r}"%\'' for r in COVERAGE_GAP_REASONS)
    # the table name comes from the executor, the rest is constant
    # the table name comes from the executor, the rest is constant. The subquery has the same
    # date bounds as the outer query (a finding row has the time of its decision), so it never
    # reads the whole finding table.
    sub = (
        f"SELECT event_id FROM {finding_table} WHERE not_executed_reason IS NOT NULL "  # noqa: S608
        "AND not_executed_reason <> 'not_applicable_for_direction' "
        "AND ts >= :r_from AND ts < :r_to"
    )
    return f"CASE WHEN ({likes} OR {p}event_id IN ({sub})) THEN 1 ELSE 0 END"  # noqa: S608


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _scan(
    ctx: MonitorContext, ts_from: datetime, ts_to: datetime
) -> dict[tuple[str, str, str, str], Counts]:
    """Grouped queries over ``ts_from <= ts < ts_to``; result keyed
    (day, dimension, dim_key, dim_key2)."""
    x = ctx.executor
    ev = x.qualify("agent_event")
    fd = x.qualify("finding")
    vd = x.qualify("verdict")
    day = _day_expr(x.dialect, "e.ts")
    params = {"r_from": ts_from, "r_to": ts_to}
    ptypes = {"r_from": "timestamp", "r_to": "timestamp"}
    where = "e.event_type = 'gate_decision' AND e.ts >= :r_from AND e.ts < :r_to"
    st = status_sql("e")
    ne = not_evaluated_sql("e", fd)
    out: dict[tuple[str, str, str, str], Counts] = defaultdict(Counts)

    rows = x.query(
        f"SELECT e.agent_id AS agent_id, COALESCE(e.consumer_id, '*') AS consumer, "  # noqa: S608 - names from model.yaml
        f"{day} AS d, {st} AS st, {ne} AS ne, COUNT(*) AS n "
        f"FROM {ev} e WHERE {where} GROUP BY e.agent_id, COALESCE(e.consumer_id, '*'), {day}, "
        f"{st}, {ne}",
        params,
        column_types={
            "agent_id": "string",
            "consumer": "string",
            "d": "string",
            "st": "string",
            "ne": "int",
            "n": "int",
        },
        param_types=ptypes,
    )
    for r in rows:
        d, status, n, flag = str(r["d"]), str(r["st"]), int(r["n"]), int(r["ne"] or 0)
        out[(d, "total", _STAR, _STAR)].add(status, n, flag)
        out[(d, "agent", str(r["agent_id"]), _STAR)].add(status, n, flag)
        if r["consumer"] != _STAR:  # WP39 review: a consumer id with personal data is hidden
            out[(d, "consumer", str(shown_id(str(r["consumer"]))), _STAR)].add(status, n, flag)

    rows = x.query(
        f"SELECT v.rule_id AS rule_id, {day} AS d, {st} AS st, {ne} AS ne, "  # noqa: S608
        "COUNT(DISTINCT e.event_id) AS n "
        f"FROM {vd} v JOIN {ev} e ON e.event_id = v.event_id "
        f"WHERE {where} AND v.tier = 0 AND NOT v.advisory AND v.rule_id IS NOT NULL "
        f"GROUP BY v.rule_id, {day}, {st}, {ne}",
        params,
        column_types={
            "rule_id": "string",
            "d": "string",
            "st": "string",
            "ne": "int",
            "n": "int",
        },
        param_types=ptypes,
    )
    for r in rows:
        out[(str(r["d"]), "rule", str(r["rule_id"]), _STAR)].add(
            str(r["st"]), int(r["n"]), int(r["ne"] or 0)
        )

    rows = x.query(
        f"SELECT f.detector_slug AS slug, f.code AS code, {day} AS d, {st} AS st, "  # noqa: S608
        "CASE WHEN f.not_executed_reason IS NULL THEN 0 ELSE 1 END AS ne, "
        "COUNT(DISTINCT f.event_id) AS n "
        f"FROM {fd} f JOIN {ev} e ON e.event_id = f.event_id "
        f"WHERE {where} AND (f.not_executed_reason IS NULL "
        "OR f.not_executed_reason <> 'not_applicable_for_direction') "
        f"GROUP BY f.detector_slug, f.code, {day}, {st}, "
        "CASE WHEN f.not_executed_reason IS NULL THEN 0 ELSE 1 END",
        params,
        column_types={
            "slug": "string",
            "code": "string",
            "d": "string",
            "st": "string",
            "ne": "int",
            "n": "int",
        },
        param_types=ptypes,
    )
    slugs = set(KNOWN_DETECTORS)
    for r in rows:
        out[(str(r["d"]), "detector_code", str(r["slug"]), str(r["code"]))].add(
            str(r["st"]), int(r["n"]), int(r["ne"] or 0)
        )
        if _SLUG.match(str(r["slug"])):
            slugs.add(str(r["slug"]))

    for slug in sorted(slugs):  # latency histogram per detector: exact percentiles, no rows loaded
        col = _json_value(x.dialect, "e.detector_latency_json", slug)
        rows = x.query(
            f"SELECT {day} AS d, {col} AS lat, COUNT(*) AS n "  # noqa: S608 - slug is [a-z0-9_]
            f"FROM {ev} e WHERE {where} AND {col} IS NOT NULL GROUP BY {day}, {col}",
            params,
            column_types={"d": "string", "lat": "int", "n": "int"},
            param_types=ptypes,
        )
        hist: dict[str, dict[int, int]] = defaultdict(dict)
        for r in rows:
            hist[str(r["d"])][int(r["lat"])] = int(r["n"])
        for d, h in hist.items():
            c = out[(d, "detector_latency", slug, _STAR)]
            c.requests = sum(h.values())
            c.p50_us = percentile_from_histogram(h.items(), 50)
            c.p95_us = percentile_from_histogram(h.items(), 95)
    return out


def _json_value(dialect: str, col: str, key: str) -> str:
    if not _SLUG.match(key):
        raise SupervisorError("detector slug is not a plain identifier")
    if dialect == "sqlite":
        return f"CASE WHEN json_valid({col}) THEN json_extract({col}, '$.{key}') END"
    return f"CAST(get_json_object({col}, '$.{key}') AS BIGINT)"


def compute_rows(ctx: MonitorContext, start: date, end: date) -> list[dict[str, Any]]:
    """Rollup rows for the UTC days ``start..end`` inclusive, sorted by key. Reads in chunks."""
    if end < start:
        raise SupervisorError("end day is before start day")
    rows: list[dict[str, Any]] = []
    days = _days(start, end)
    for i in range(0, len(days), CHUNK_DAYS):
        chunk = days[i : i + CHUNK_DAYS]
        groups = _scan(ctx, _day_start(chunk[0]), _day_start(chunk[-1] + timedelta(days=1)))
        for (d, dim, key, key2), c in groups.items():
            rows.append(
                {
                    "usage_date": date.fromisoformat(d),
                    "dimension": dim,
                    "dim_key": key,
                    "dim_key2": key2,
                    "requests": c.requests,
                    "allows": c.allows,
                    "reports": c.reports,
                    "transforms": c.transforms,
                    "pauses": c.pauses,
                    "blocks": c.blocks,
                    "skips": c.skips,
                    "not_evaluated": c.not_evaluated,
                    "p50_us": c.p50_us,
                    "p95_us": c.p95_us,
                }
            )
    rows.sort(key=lambda r: (r["usage_date"], r["dimension"], r["dim_key"], r["dim_key2"]))
    return rows


_KEY = ("usage_date", "dimension", "dim_key", "dim_key2")


def _same(old: Mapping[str, Any], new: Mapping[str, Any]) -> bool:
    return all(old.get(c) == new.get(c) for c in VALUE_COLUMNS)


def _write(
    ctx: MonitorContext, rows: Sequence[dict[str, Any]], days: Sequence[date]
) -> dict[str, int]:
    """Insert new rows, update changed rows, zero rows the data no longer supports (a day is
    overwritten), leave equal rows alone (a rerun writes nothing)."""
    stats = {"inserted": 0, "updated": 0, "unchanged": 0, "removed": 0}
    existing: dict[tuple[Any, ...], dict[str, Any]] = {}
    for d in days:
        for r in ctx.state.query(TABLE, {"usage_date": d}):
            existing[tuple(r[k] for k in _KEY)] = r
    now = ctx.clock.now()
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        k = tuple(row[c] for c in _KEY)
        seen.add(k)
        key = {c: row[c] for c in _KEY}
        old = existing.get(k)
        data = {**row, "computed_at": now}
        for attempt in range(3):
            try:
                if old is None:
                    ctx.state.insert(TABLE, data)
                    stats["inserted"] += 1
                elif _same(old, row):
                    stats["unchanged"] += 1
                else:
                    changes = {c: v for c, v in data.items() if c not in key}
                    ctx.state.update(TABLE, key, changes, old["row_version"])
                    stats["updated"] += 1
                break
            except (ConcurrencyError, DuplicateKeyError):
                if attempt == 2:
                    raise
                old = ctx.state.get(TABLE, key)
    for k, old in existing.items():  # the data behind a row is gone (retention): zero it
        if k not in seen and any(old.get(c) for c in VALUE_COLUMNS):
            zero = {c: (None if c.endswith("_us") else 0) for c in VALUE_COLUMNS}
            ctx.state.update(
                TABLE,
                {c: old[c] for c in _KEY},
                {**zero, "computed_at": now},
                old["row_version"],
            )
            stats["removed"] += 1
    return stats


def rollup(ctx: MonitorContext, start: date, end: date) -> dict[str, Any]:
    rows = compute_rows(ctx, start, end)
    stats = _write(ctx, rows, _days(start, end))
    return {"from": start.isoformat(), "to": end.isoformat(), "rows": len(rows), **stats}


def run(
    ctx: MonitorContext, settings: Settings, *, days: int = 2, today: date | None = None
) -> dict[str, Any]:
    """Scheduler entry: recompute the last ``days`` UTC days (default yesterday and today)."""
    today = today or ctx.clock.now().astimezone(UTC).date()
    return rollup(ctx, today - timedelta(days=days - 1), today)


def earliest_day(ctx: MonitorContext) -> date | None:
    x = ctx.executor
    rows = x.query(
        f"SELECT MIN(ts) AS t FROM {x.qualify('agent_event')} WHERE event_type = 'gate_decision'",  # noqa: S608
        column_types={"t": "timestamp"},
    )
    t = rows[0]["t"] if rows else None
    return as_dt(t).date() if t is not None else None


def _parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {text}") from exc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m supervisor.jobs.decision_rollup",
        description="Recompute decision_daily from stored gate decisions and findings (WP39).",
    )
    ap.add_argument("--days", type=int, default=2, help="last N UTC days (default 2)")
    ap.add_argument("--from", dest="start", type=_parse_day, default=None)
    ap.add_argument("--to", dest="end", type=_parse_day, default=None)
    ap.add_argument("--backfill", action="store_true", help="from the first gate decision")
    args = ap.parse_args(argv)
    try:
        with standalone() as (_, _, ctx):
            today = ctx.clock.now().astimezone(UTC).date()
            end = args.end or today
            if args.backfill:
                start = earliest_day(ctx) or end
            else:
                start = args.start or end - timedelta(days=max(args.days, 1) - 1)
            out = rollup(ctx, start, end)
    except (SupervisorError, ValueError) as exc:
        print(ascii_line(f"[FAIL] decision rollup: {exc}"))
        return 1
    print(
        ascii_line(
            f"[OK] decision rollup {out['from']}..{out['to']}: {out['rows']} rows "
            f"({out['inserted']} new, {out['updated']} updated, {out['unchanged']} same, "
            f"{out['removed']} removed)"
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
