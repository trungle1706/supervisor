"""Analytics, verdict v2 parts (WP39, flag CONSOLE_DECISIONS_V2): the Gate tables and the
Detectors tab. Everything is read from ``decision_daily`` (the rollup of ``agent_event`` and
``finding``), so a page load never scans the raw tables. If the rollup has not run, the tables
are empty and the page says which command fills them.

Percentiles per detector are approximations over several days: p50 is the request-weighted
mean of the daily p50, p95 is the highest daily p95 (a daily percentile cannot be merged
exactly). One day is exact.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from supervisor.analytics import tools
from supervisor.console import views

STATUS_COLS = ("reports", "transforms", "pauses", "blocks", "skips")
SERIES = ("reports", "transforms", "pauses", "blocks")
DIMENSIONS = ("agent", "consumer", "rule", "detector_code")
MAX_ROWS = 100


def _share(part: int, whole: int) -> int:
    return part * 10000 // whole if whole else 0


def _window(ctx: Any, days: int | None) -> tuple[dt.date, dt.date, int]:
    from supervisor.console.analytics import GATE_DEFAULT_DAYS, _as_of

    n = days or GATE_DEFAULT_DAYS
    start, end = tools.window_bounds(_as_of(ctx), n)
    return start, end, n


def _rows(ctx: Any, dim: str, start: dt.date, end: dt.date) -> list[dict[str, Any]]:
    return [
        r
        for r in ctx.state.query("decision_daily", {"dimension": dim})
        if start <= r["usage_date"] <= end
    ]


def _fold(rows: list[dict[str, Any]], agent: str = "") -> list[dict[str, Any]]:
    """Sum the daily rows per (key, key2) and add the share of each status in basis points."""
    acc: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        a = acc[(r["dim_key"], r["dim_key2"])]
        for c in ("requests", "allows", *STATUS_COLS, "not_evaluated"):
            a[c] += int(r[c] or 0)
    out = []
    for (k, k2), a in acc.items():
        row = {"key": k, "key2": k2, **a}
        for c in (*STATUS_COLS, "not_evaluated"):
            row[c + "_bp"] = _share(a[c], a["requests"])
        out.append(row)
    out.sort(key=lambda r: (-r["requests"], r["key"], r["key2"]))
    return out[:MAX_ROWS]


def gate_tables(ctx: Any, days: int | None, agent: str) -> dict[str, Any]:
    start, end, n = _window(ctx, days)
    tables = {d: _fold(_rows(ctx, d, start, end)) for d in DIMENSIONS}
    if agent:
        tables["agent"] = [r for r in tables["agent"] if r["key"] == agent]
    total_rows = (
        [r for r in _rows(ctx, "agent", start, end) if r["dim_key"] == agent]
        if agent
        else _rows(ctx, "total", start, end)
    )
    by_day: dict[dt.date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in total_rows:
        for c in SERIES:
            by_day[r["usage_date"]][c] += int(r[c] or 0)
    day_list = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    series = {
        c: {
            "values": [by_day[d][c] for d in day_list],
            "total": sum(by_day[d][c] for d in day_list),
            "spark": views.sparkline([by_day[d][c] for d in day_list], width=240, height=36),
        }
        for c in SERIES
    }
    return {
        "dd_tables": tables,
        "dd_series": series,
        "dd_days": [d.isoformat() for d in day_list],
        "dd_empty": not any(tables.values()) and not total_rows,
        "dd_days_n": n,
    }


REPORT_NAME = "detectors_report.json"


def report_path(ctx: Any) -> Path:
    """Where the recorded detectors harness report is read from (never computed in a request)."""
    return Path(ctx.settings.data_dir) / "eval" / REPORT_NAME


def _validation(ctx: Any) -> dict[str, dict[str, str]]:
    """Harness verdicts of the shipped detectors, read from the report file written by
    ``python -m supervisor.detectors.harness --json <DATA_DIR>/eval/detectors_report.json``.
    Nothing runs here: no file (or a bad one) gives an empty dict and the tab says "not run".
    A GO on the adversarial recall whose Wilson lower bound is below the threshold is marked
    "GO (indicative)" by the harness; the tab shows that marker as it is."""
    from supervisor.detectors import harness

    try:
        report = json.loads(report_path(ctx).read_text(encoding="utf-8"))
        out: dict[str, dict[str, str]] = {}
        for slug, d in report["detectors"].items():
            # Phase 5: the report also holds harness suites (dlp_vn_secrets, document_*) and
            # detectors whose row has no adversarial split. Skip an entry that lacks the
            # detector shape instead of rejecting the whole report.
            try:
                adv = harness._indicative(
                    d, "adversarial_recall_bp", d["go_no_go"]["adversarial_recall_bp"]
                )
                out[slug.split("@")[0]] = {
                    "overall": str(d["verdict"]),
                    "adversarial": adv,
                    "mock": "1" if d["model"]["kind"] == "mock" else "",
                }
            except (KeyError, TypeError, AttributeError):
                continue
        return out
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def detectors_data(ctx: Any, days: int | None, agent: str) -> dict[str, Any]:
    start, end, n = _window(ctx, days)
    lat = _rows(ctx, "detector_latency", start, end)
    per: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in lat:
        per[r["dim_key"]].append(r)
    latency = []
    for slug, rows in sorted(per.items()):
        runs = sum(int(r["requests"] or 0) for r in rows)
        p50s = [(int(r["p50_us"]), int(r["requests"])) for r in rows if r["p50_us"] is not None]
        p95s = [int(r["p95_us"]) for r in rows if r["p95_us"] is not None]
        latency.append(
            {
                "detector": slug,
                "runs": runs,
                "p50_us": (sum(v * w for v, w in p50s) // max(1, sum(w for _, w in p50s)))
                if p50s
                else None,
                "p95_us": max(p95s) if p95s else None,
            }
        )
    codes = _fold(_rows(ctx, "detector_code", start, end))
    validation = _validation(ctx)
    return {
        "det_latency": latency,
        "det_codes": codes,
        "det_validation": validation,
        "det_days": n,
        "det_from": start.isoformat(),
        "det_to": end.isoformat(),
        "det_empty": not lat and not codes,
    }
