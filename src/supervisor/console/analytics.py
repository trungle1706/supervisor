"""Analytics page (WP-UX2): Gate, Tools, Oversight metrics and Latency under one toolbar.

One toolbar (range in days, agent) applies to every tab. The range is blank by default, and
blank means each tab's own window: Tools uses ``TOOL_ANALYTICS_WINDOW_DAYS``, Gate the last 7
days, Oversight metrics all stored days (as the old Metrics page did), Latency the live
process counters. Read only; nothing here writes.

The Tools tab is off with ``CONSOLE_TOOLS_ENABLED=0`` (HTTP 400 with a message, as before)."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from typing import Any

from supervisor.analytics import tools
from supervisor.console import analytics_v2, readmodels, tools_views, ux5_g5, views
from supervisor.console.listing import ListingError
from supervisor.core.errors import SupervisorError

TABS = ("gate", "tools", "metrics", "latency", "detectors")
RANGES = (7, 30, 90)
GATE_DEFAULT_DAYS = 7
_ID = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")


class AnalyticsInputError(SupervisorError):
    """Unknown tab, bad range or agent, or the Tools tab is off (HTTP 400)."""


def visible_tabs(ctx: Any) -> list[str]:
    return [
        t
        for t in TABS
        if (t != "tools" or ctx.settings.console_tools_enabled)
        and (t != "detectors" or ctx.settings.console_decisions_v2)
    ]


def check_tab(ctx: Any, tab: str) -> str:
    if tab not in TABS:
        raise AnalyticsInputError("unknown analytics tab")
    if tab == "tools" and not ctx.settings.console_tools_enabled:
        raise AnalyticsInputError(
            "The Tools tab is off (CONSOLE_TOOLS_ENABLED=1 turns it on); use "
            "python -m supervisor.analytics.tools report"
        )
    if tab == "detectors" and not ctx.settings.console_decisions_v2:
        raise AnalyticsInputError("The Detectors tab is off (CONSOLE_DECISIONS_V2=1 turns it on)")
    return tab


def parse_toolbar(ctx: Any, query: Mapping[str, str]) -> dict[str, Any]:
    """The toolbar values: ``days`` (int or None = tab default) and ``agent`` ('' = all).
    The legacy name ``agent_id`` (old /console/tools links) is read as ``agent``."""
    raw_days = query.get("days") or ""
    days: int | None = None
    if raw_days:
        days = tools_views.check_days(raw_days, ctx.settings)
    agent = query.get("agent") or query.get("agent_id") or ""
    if agent:
        if not _ID.match(agent):
            raise AnalyticsInputError("invalid agent id")
        if ctx.state.get("agent", {"agent_id": agent}) is None:
            raise AnalyticsInputError(f"agent {agent} is not registered")
    return {"days": days, "agent": agent}


def toolbar_options(ctx: Any, days: int | None) -> dict[str, Any]:
    ranges = sorted({*RANGES, *([days] if days else [])})
    agents = sorted(a["agent_id"] for a in ctx.state.query("agent"))
    return {"range_opts": ranges, "agent_opts": agents}


def _as_of(ctx: Any) -> dt.date:
    return ctx.clock.now().astimezone(dt.UTC).date()


# ---------------------------------------------------------------------------- gate


def gate_data(ctx: Any, days: int | None, agent: str) -> dict[str, Any]:
    """Gate decisions per agent in the window: checked, blocked, paused, median latency."""
    n = days or GATE_DEFAULT_DAYS
    start_day, end_day = tools.window_bounds(_as_of(ctx), n)
    since = dt.datetime.combine(start_day, dt.time.min, tzinfo=dt.UTC)
    where: dict[str, Any] = {"event_type": "gate_decision"}
    if agent:
        where["agent_id"] = agent
    events = ctx.tables.query("agent_event", where, order_by=("-ts",), limit=readmodels.SCAN_CAP)
    recent = [e for e in events if e["ts"] >= since]
    ids = {e["event_id"] for e in recent}
    stops: dict[str, str] = {}
    for v in readmodels.stop_verdicts(ctx, readmodels.SCAN_CAP):
        key = v.get("event_id")
        if v["advisory"] or key not in ids:
            continue
        if stops.get(key) != "pause":
            stops[key] = v["action"]
    per: dict[str, dict[str, Any]] = {}
    for e in recent:
        row = per.setdefault(
            e["agent_id"],
            {"agent_id": e["agent_id"], "checked": 0, "blocked": 0, "paused": 0, "lat": []},
        )
        row["checked"] += 1
        action = stops.get(e["event_id"])
        row["blocked"] += action == "block"
        row["paused"] += action == "pause"
        if e.get("latency_ms") is not None:
            row["lat"].append(int(e["latency_ms"]))
    rows = []
    for r in sorted(per.values(), key=lambda r: (-r["checked"], r["agent_id"])):
        lat = r.pop("lat")
        r["median_ms"] = readmodels.median(lat)
        r["p95_ms"] = sorted(lat)[max(0, (len(lat) * 95 + 99) // 100 - 1)] if lat else None
        rows.append(r)
    all_lat = [int(e["latency_ms"]) for e in recent if e.get("latency_ms") is not None]
    p95 = sorted(all_lat)[max(0, (len(all_lat) * 95 + 99) // 100 - 1)] if all_lat else None
    return {
        "gate_rows": rows,
        "gate_days": n,
        "gate_from": start_day.isoformat(),
        "gate_to": end_day.isoformat(),
        "gate_total": {
            "checked": len(recent),
            "blocked": sum(1 for a in stops.values() if a == "block"),
            "paused": sum(1 for a in stops.values() if a == "pause"),
            "p95_ms": p95,
        },
        "gate_capped": len(events) >= readmodels.SCAN_CAP,
    }


# ---------------------------------------------------------------------------- tools


def tools_data(
    ctx: Any, me_can_download: bool, days: int | None, agent: str, sort: str, desc: bool
) -> dict[str, Any]:
    data = tools_views.page(ctx, agent_id=agent or None, days=days, sort=sort, desc=desc)
    rows = [r for a in data["agents"] for r in a["rows"]]
    p95s = [r["p95_us"] for r in rows if r["p95_us"] is not None]
    data["tools_total"] = {
        "calls": sum(r["calls"] for r in rows),
        "blocks": sum(r["blocks"] for r in rows),
        "pauses": sum(r["pauses"] for r in rows),
        "p95_us": max(p95s) if p95s else None,
    }
    data["can_download"] = me_can_download
    return data


# ---------------------------------------------------------------------------- metrics


def alerts_summary(ctx: Any) -> dict[str, Any]:
    try:
        return dict(ctx.alerts.counts())
    except Exception:  # noqa: BLE001 - the tile is a convenience, never a page failure
        return {"open": 0, "acknowledged": 0}


def metrics_data(ctx: Any, days: int | None, agent: str) -> dict[str, Any]:
    """Oversight metric rows (filtered by the toolbar), monitor status, chain status."""
    rows = ctx.state.query("oversight_metric")
    if agent:
        rows = [r for r in rows if r["agent_id"] == agent]
    if days:
        start, _ = tools.window_bounds(_as_of(ctx), days)
        rows = [r for r in rows if r["metric_date"] >= start]
    rows.sort(key=lambda r: (r["agent_id"], r["metric_date"]))
    cols = views.metric_columns(rows)
    by_agent: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_agent.setdefault(r["agent_id"], []).append(r)
    summary = []
    for agent_id, series in sorted(by_agent.items()):
        latest = series[-1]
        summary.append(
            {
                "agent_id": agent_id,
                "metric_date": latest["metric_date"],
                "latest": latest,
                "sparks": {
                    c: views.sparkline([views.to_int(r.get(c)) for r in series]) for c in cols
                },
                "points": len(series),
            }
        )
    heads = ctx.runtime.chain.heads()
    monitor_rows = views.monitor_status_rows(rows)
    extra: dict[str, Any] = {}
    if ctx.settings.console_ux5:  # UX5: only agents with data, plus a count of the rest
        extra = ux5_g5.monitor_view(monitor_rows, views.MONITOR_ORDER)
    return {
        **extra,
        "alert_counts": alerts_summary(ctx),
        "metric_cols": cols,
        "monitor_rows": monitor_rows,
        "monitor_order": views.MONITOR_ORDER,
        "summary": summary,
        "rows": rows[-200:],
        "metric_from": str(min(r["metric_date"] for r in rows)) if rows else "",
        "metric_to": str(max(r["metric_date"] for r in rows)) if rows else "",
        "heads": {k: {"seq": v.seq, "entry_hash": v.entry_hash} for k, v in sorted(heads.items())},
        "entries": sum(v.seq + 1 for v in heads.values()),
        "verify": ctx.last_verify.get("all"),
    }


def latency_data(ctx: Any) -> dict[str, Any]:
    return {"gate": ctx.gateway.metrics.snapshot()}


def effective_window(
    ctx: Any, tab: str, days: int | None, data: Mapping[str, Any]
) -> dict[str, Any]:
    """The window the shown tab really uses, for the toolbar (a blank range means each tab's
    own default, so the toolbar always says which days the numbers cover).

    ``kind``: ``days`` (``from`` .. ``to``, ``n`` days, UTC, ``default`` True when the range was
    blank), ``stored`` (Oversight metrics with a blank range: every stored day, ``from`` ..
    ``to`` or empty when there is no row) or ``live`` (Latency: counters since the process
    started)."""
    if tab == "gate":
        return {
            "kind": "days",
            "from": data["gate_from"],
            "to": data["gate_to"],
            "n": data["gate_days"],
            "default": days is None,
        }
    if tab == "detectors":
        return {
            "kind": "days",
            "from": data["det_from"],
            "to": data["det_to"],
            "n": data["det_days"],
            "default": days is None,
        }
    if tab == "tools":
        return {
            "kind": "days",
            "from": data["window_from"],
            "to": data["window_to"],
            "n": data["days"],
            "default": days is None,
        }
    if tab == "metrics":
        if days:
            start, end = tools.window_bounds(_as_of(ctx), days)
            return {
                "kind": "days",
                "from": start.isoformat(),
                "to": end.isoformat(),
                "n": days,
                "default": False,
            }
        return {"kind": "stored", "from": data["metric_from"], "to": data["metric_to"]}
    return {"kind": "live"}


def tab_data(
    ctx: Any,
    me_can_download: bool,
    tab: str,
    toolbar: Mapping[str, Any],
    query: Mapping[str, str],
) -> dict[str, Any]:
    days, agent = toolbar["days"], toolbar["agent"]
    if tab == "gate":
        data = gate_data(ctx, days, agent)
        if ctx.settings.console_decisions_v2:  # WP39: tables and series from decision_daily
            data.update(analytics_v2.gate_tables(ctx, days, agent), dd_on=True)
        return data
    if tab == "detectors":
        return analytics_v2.detectors_data(ctx, days, agent)
    if tab == "tools":
        sort = query.get("sort", "default")
        if sort not in tools_views.SORTS:
            raise ListingError("unknown sort column")
        return tools_data(ctx, me_can_download, days, agent, sort, query.get("dir") == "desc")
    if tab == "metrics":
        return metrics_data(ctx, days, agent)
    return latency_data(ctx)
