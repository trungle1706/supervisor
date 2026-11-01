"""Stability view (W8, ``STABILITY_TAB``): how steady is the use case after deployment.

Read only. The tab never pauses, resumes or changes anything. It reads the calls the gate wrote
(``agent_event``), the judge scores (``verdict``), the normal range that the drift check built
(``policy_baseline``) and the cases, incidents and guardian changes of the system.

Same measures as the drift check (``monitors.drift.window_metrics``): tool share per tool, amount
p50 and p90, share of stopped calls, judge suspicion p50 and p90, latency p50 and p90. The range
of normal comes from the stored baseline band (median +- k * MAD); nothing is guessed here.

Verdict (deterministic, one line on the page):

* ``unstable``  an open drift case, or a measure outside its normal range for M windows in a row;
* ``watch``     a measure outside its range in the latest closed window, or a conversation alert
                in the last M windows;
* ``stable``    every measure inside its range;
* ``nodata``    no normal range yet, or too few calls in the latest windows to judge.

Windows are the drift windows (``window_s`` of the stored baseline). The charts may use another
bucket (minute, hour, day); the band is drawn only when the bucket equals the drift window, so the
shaded range is never compared with the wrong unit. Judge scores of a mock judge are kept apart
and never decide the verdict. Values are integers (basis points, minor units, milliseconds);
text formatting happens at the last step. The charts are inline SVG built here: no library."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from supervisor.console import readmodels
from supervisor.core.errors import SupervisorError
from supervisor.monitors.common import as_dt, floor_window, percentile
from supervisor.monitors.drift import window_metrics

log = logging.getLogger("supervisor.console.stability")
VIEWS: dict[str, tuple[int, int]] = {  # view -> (bucket seconds, number of buckets)
    "hour": (60, 60),
    "day": (3600, 24),
    "week": (86400, 7),
}
VIEW_ORDER = ("hour", "day", "week")
LIVE_BELOW_S = 60  # a drift window shorter than this (demo only) gets the "live" view
LIVE_SPAN_S = 600  # the live view shows about the last ten minutes, one point per drift window
REFRESH_S = 10
LIVE_REFRESH_S = 5


def views_for(window_s: int) -> tuple[str, ...]:
    """The time ranges on offer: a short drift window (demo) adds a live range by window."""
    return ("live", *VIEW_ORDER) if window_s < LIVE_BELOW_S else VIEW_ORDER


def view_for_window(window_s: int) -> str:
    """The range whose bucket is the drift window (so the band and the breach marks show)."""
    if window_s < LIVE_BELOW_S:
        return "live"
    return {60: "hour", 3600: "day", 86400: "week"}.get(window_s, "day")


def spec(view: str, window_s: int) -> tuple[int, int]:
    """(bucket seconds, number of buckets) of a range. Live: one bucket per drift window."""
    if view == "live":
        return window_s, max(8, min(60, LIVE_SPAN_S // max(1, window_s)))
    return VIEWS[view]


SCAN = 20000  # newest events read per agent (a busy agent: the view says so)
EVENT_COLS = ("agent_id", "ts", "event_type", "tool_name", "status", "amount_minor", "latency_ms")
EVENT_COLS_V = (*EVENT_COLS, "agent_version")
VERDICT_COLS = ("agent_id", "ts", "tier", "role", "score_bp", "is_mock")
STATES = ("stable", "watch", "unstable", "nodata")
RANK = {"unstable": 3, "watch": 2, "stable": 1, "nodata": 0}
OPEN_CASE = ("open", "investigating", "in_review", "escalated", "new", "triage")
HISTORY_DAYS = 14
PAUSE_RUN_S = 900  # stops less than 15 minutes apart are shown as one line
TIMELINE_ROWS = 12
MAX_TOOLS = 4
FALLBACK_BASELINE_WINDOWS = 7


class StabilityError(SupervisorError):
    """A bad request on the Stability tab (HTTP 400)."""


def require_on(settings: Any) -> None:
    if not getattr(settings, "stability_tab", False):
        raise StabilityError(
            "The Stability view is switched off. Ask the platform team to turn it on."
        )


# ------------------------------------------------------------------------------ formatting


def fmt_bp(bp: int | None) -> str:
    """Basis points as a percentage, integer arithmetic: 316 -> 3.1%, 900 -> 9%."""
    if bp is None:
        return "-"
    sign = "-" if bp < 0 else ""
    a = abs(int(bp))
    whole, tenth = a // 100, (a % 100) // 10
    return f"{sign}{whole}{'.' + str(tenth) if tenth else ''}%"


def fmt_vnd(v: int | None) -> str:
    """VND amount, short: 950000 -> 950k, 12500000 -> 12.5M, 2000000000 -> 2B."""
    if v is None:
        return "-"
    a = abs(int(v))
    sign = "-" if v < 0 else ""
    for size, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "k")):
        if a >= size:
            whole = a // size
            tenth = (a % size) * 10 // size
            if whole >= 100:
                tenth = 0
            return f"{sign}{whole}{'.' + str(tenth) if tenth else ''}{suffix}"
    return f"{sign}{a}"


def fmt_ms(v: int | None) -> str:
    if v is None:
        return "-"
    return f"{int(v)} ms" if v < 10_000 else f"{int(v) // 1000} s"


def fmt_int(v: int | None) -> str:
    return "-" if v is None else f"{int(v):,}"


FORMATS = {"bp": fmt_bp, "vnd": fmt_vnd, "ms": fmt_ms, "n": fmt_int}


def window_words(seconds: int) -> tuple[str, int]:
    """A window length as (unit key, count): 60 -> ('minute', 1), 7200 -> ('hour', 2)."""
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds % size == 0:
            return unit, seconds // size
    return "second", int(seconds)


# ------------------------------------------------------------------------------ reads


def _rows(
    ctx: Any,
    table: str,
    agent_id: str,
    cols: Sequence[str],
    where: Mapping[str, Any] | None,
    limit: int,
) -> list[dict[str, Any]]:
    tables = ctx.tables
    if hasattr(tables, "query_by"):
        got = tables.query_by(
            table,
            "agent_id",
            [agent_id],
            columns=list(cols),
            where=dict(where or {}),
            order_by=("-ts",),
            per_key_limit=limit,
        )
        return [dict(r) for r in got.get(agent_id, [])]
    rows = tables.query(
        table, {"agent_id": agent_id, **(where or {})}, order_by=("-ts",), limit=limit
    )
    return [dict(r) for r in rows]


def _ts(row: Mapping[str, Any]) -> dt.datetime | None:
    try:
        return as_dt(row.get("ts"))
    except (ValueError, TypeError):
        return None


def load_events(ctx: Any, agent_id: str, since: dt.datetime) -> tuple[list[dict[str, Any]], bool]:
    """Events of the agent since ``since`` (newest SCAN read). ``True`` when older rows were cut."""
    rows = _rows(ctx, "agent_event", agent_id, EVENT_COLS_V, None, SCAN)
    cut = len(rows) >= SCAN
    out: list[dict[str, Any]] = []
    oldest: dt.datetime | None = None
    for r in rows:
        t = _ts(r)
        if t is None:
            continue
        r["_ts"] = t
        oldest = t if oldest is None or t < oldest else oldest
        if t >= since:
            out.append(r)
    return out, bool(cut and oldest is not None and oldest > since)


def load_verdicts(ctx: Any, agent_id: str, since: dt.datetime) -> list[dict[str, Any]]:
    rows = _rows(ctx, "verdict", agent_id, VERDICT_COLS, {"tier": 1}, SCAN)
    out = []
    for r in rows:
        t = _ts(r)
        if t is not None and t >= since:
            r["_ts"] = t
            out.append(r)
    return out


# ------------------------------------------------------------------------------ buckets


def group(
    rows: Sequence[dict[str, Any]], start: dt.datetime, step_s: int, n: int
) -> list[list[dict[str, Any]]]:
    out: list[list[dict[str, Any]]] = [[] for _ in range(n)]
    s = start.timestamp()
    for r in rows:
        i = int((r["_ts"].timestamp() - s) // step_s)
        if 0 <= i < n:
            out[i].append(r)
    return out


def _score_stats(verdicts: Sequence[Mapping[str, Any]], mock: bool, min_n: int) -> dict[str, int]:
    scores = [
        int(v["score_bp"])
        for v in verdicts
        if bool(v.get("is_mock")) == mock
        and v.get("role") == "primary"
        and isinstance(v.get("score_bp"), int)
    ]
    if len(scores) < min_n:
        return {}
    return {"p50": percentile(scores, 50), "p90": percentile(scores, 90)}


def bucket_values(
    events: Sequence[Mapping[str, Any]],
    verdicts: Sequence[Mapping[str, Any]],
    *,
    min_n: int,
    tools: Sequence[str],
) -> dict[str, int | None]:
    """All the numbers of one bucket. The drift measures come from ``window_metrics`` (judge
    scores of real judges only); the rest is for the charts."""
    real = [v for v in verdicts if not v.get("is_mock")]
    m: dict[str, int | None] = dict(window_metrics(events, real, min_n=min_n, tools=list(tools)))
    gate = [e for e in events if e.get("event_type") == "gate_decision"]
    m["calls"] = len(gate) if gate else sum(1 for e in events if e.get("event_type") == "tool_call")
    lat = [int(e["latency_ms"]) for e in gate if isinstance(e.get("latency_ms"), int)]
    if len(lat) >= min_n:
        m["gate_p50_ms"], m["gate_p90_ms"] = percentile(lat, 50), percentile(lat, 90)
    mock = _score_stats(verdicts, True, min_n)
    if mock:
        m["mock_p50_bp"], m["mock_p90_bp"] = mock["p50"], mock["p90"]
    return m


def outside(value: int | None, band: Mapping[str, Any] | None) -> bool:
    return value is not None and band is not None and (value < band["low"] or value > band["high"])


def streak(values: Sequence[int | None], band: Mapping[str, Any] | None) -> int:
    """Trailing run of windows outside the band; a window without a value is skipped (as the
    drift check does: a data gap neither breaks nor extends a streak)."""
    n = 0
    for v in reversed(values):
        if v is None:
            continue
        if not outside(v, band):
            break
        n += 1
    return n


# ------------------------------------------------------------------------------ verdict


def decide(
    windows: Sequence[Mapping[str, int | None]],
    bands: Mapping[str, Mapping[str, Any]],
    *,
    m: int,
    drift_case_open: bool,
    session_alert: bool,
    deciding: Sequence[str] | None = None,
) -> dict[str, Any]:
    """The verdict from the closed windows (oldest first) and the stored bands. Pure."""
    names = sorted(k for k in bands if deciding is None or k in deciding)
    if not bands:
        return {"state": "nodata", "why": "nobase", "names": [], "checked": 0}
    seen = [i for i, w in enumerate(windows) if any(w.get(k) is not None for k in names)]
    if not seen and not drift_case_open:
        return {"state": "nodata", "why": "quiet", "names": [], "checked": 0}
    streaks = {k: streak([w.get(k) for w in windows], bands[k]) for k in names}
    long_run = sorted(k for k, s in streaks.items() if s >= m)
    latest = sorted(k for k, s in streaks.items() if s >= 1)
    checked = sum(1 for k in names if any(w.get(k) is not None for w in windows))
    if drift_case_open or long_run:
        return {
            "state": "unstable",
            "why": "streak" if long_run else "case",
            "names": long_run or latest,
            "checked": checked,
            "streaks": streaks,
        }
    if latest:
        return {
            "state": "watch",
            "why": "range",
            "names": latest,
            "checked": checked,
            "streaks": streaks,
        }
    if session_alert:
        return {
            "state": "watch",
            "why": "session",
            "names": [],
            "checked": checked,
            "streaks": streaks,
        }
    return {"state": "stable", "why": "ok", "names": [], "checked": checked, "streaks": streaks}


# ------------------------------------------------------------------------------ chart geometry

PAD_L, PAD_R, PAD_T, PAD_B = 46, 10, 10, 26


def _nice_ticks(lo: int, hi: int) -> list[int]:
    return [lo, (lo + hi) // 2, hi]


def panel_svg(
    series: Sequence[Mapping[str, Any]],
    labels: Sequence[str],
    unit: str,
    *,
    kind: str = "line",
    partial_last: bool = False,
    compact: bool = False,
) -> dict[str, Any]:
    """Geometry of one chart panel. ``series`` items: ``key``, ``values`` (int or None per
    bucket), ``band`` (``low``/``high`` or None), ``breach`` (bool per bucket). Everything is
    rounded to 0.1 px; the template only draws."""
    n = len(labels)
    W, H = (300, 140) if compact else (420, 170)  # noqa: N806 - the box of this chart
    pw, ph = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    nums: list[int] = []
    for s in series:
        nums += [v for v in s["values"] if v is not None]
        if s.get("band"):
            nums += [s["band"]["low"], s["band"]["high"]]
    lo = 0  # a zero baseline: a small wobble never looks like a jump
    hi = max(nums) if nums else 1
    if hi <= lo:
        hi = lo + 1
    hi_pad = hi + max(1, (hi - lo) // 12)
    span = hi_pad - lo
    step = pw / n

    def px(i: int) -> float:
        return round(PAD_L + step * (i + 0.5), 1)

    def py(v: int) -> float:
        return round(PAD_T + ph - (v - lo) * ph / span, 1)

    fmt = FORMATS[unit]
    out_series = []
    for si, s in enumerate(series):
        segs: list[list[tuple[float, float]]] = []
        cur: list[tuple[float, float]] = []
        dots = []
        bars = []
        for i, v in enumerate(s["values"]):
            if v is None:
                if cur:
                    segs.append(cur)
                    cur = []
                continue
            x, y = px(i), py(v)
            partial = partial_last and i == n - 1
            if not partial:  # the open bucket is a hollow dot only: it is not joined to the line
                cur.append((x, y))
            br = bool(s["breach"][i]) if s.get("breach") else False
            dots.append(
                {
                    "x": x,
                    "y": y,
                    "breach": br,
                    "partial": partial,
                    "title": f"{labels[i]}: {fmt(v)}",
                }
            )
            if kind == "bars" and v > 0:
                top = py(v)
                bars.append(
                    {
                        "x": round(x - step * 0.3, 1),
                        "y": top,
                        "w": round(step * 0.6, 1),
                        "h": round(PAD_T + ph - top, 1),
                        "title": f"{labels[i]}: {fmt(v)}",
                    }
                )
        if cur:
            segs.append(cur)
        paths = ["M" + " L".join(f"{x},{y}" for x, y in seg) for seg in segs if len(seg) > 1]
        band = s.get("band")
        out_series.append(
            {
                "idx": si,
                "key": s["key"],
                "dash": bool(s.get("dash")),
                "paths": paths,
                "dots": dots if kind != "bars" else [],
                "bars": bars,
                "band": (
                    {
                        "y": py(band["high"]),
                        "h": round(max(0.0, py(max(band["low"], lo)) - py(band["high"])), 1),
                    }
                    if band
                    else None
                ),
            }
        )
    stripes = []
    breach_any = [any(s.get("breach") and s["breach"][i] for s in series) for i in range(n)]
    for i, b in enumerate(breach_any):
        if b:
            stripes.append({"x": round(PAD_L + step * i, 1), "w": round(step, 1)})
    idxs = sorted({0, n // 2, n - 1})
    return {
        "w": W,
        "h": H,
        "x0": PAD_L,
        "x1": W - PAD_R,
        "y0": PAD_T,
        "y1": PAD_T + ph,
        "series": out_series,
        "empty": not any(v for sr in series for v in sr["values"])
        if kind == "bars"
        else not any(v is not None for sr in series for v in sr["values"]),
        "stripes": stripes,
        "yticks": [{"y": py(t), "label": fmt(t)} for t in _nice_ticks(lo, hi)],
        "xticks": [{"x": px(i), "label": labels[i]} for i in idxs],
    }


# ------------------------------------------------------------------------------ sentences


BUCKET_UNIT = {
    "hour": "minute",
    "day": "hour",
    "week": "day",
    "live": "window",
}  # view -> what one point is


def _unit_word(unit: str, n: int) -> str:
    """The key part of a time unit word: ('minute', 1) -> 'minute_one', else 'minute_many'."""
    return f"{unit}_{'one' if n == 1 else 'many'}"


def metric_name(metric: str) -> dict[str, str]:
    """``{key, tool}`` for the label of a measure (``t(key, tool=tool)``)."""
    if metric.startswith("tool_share_bp:"):
        return {"key": "st_m_tool", "tool": metric.split(":", 1)[1]}
    return {"key": f"st_m_{metric}", "tool": ""}


def sentence(
    name_key: str,
    series: Mapping[str, Any],
    unit: str,
    view: str,
    *,
    tool: str = "",
    banded: bool,
) -> dict[str, Any]:
    """One plain sentence about a series: ``{key, params}`` for ``t(key, **params)``."""
    fmt = FORMATS[unit]
    vals = series["values"]
    br = series.get("breach") or []
    last_closed = max(0, len(vals) - 2)  # the last bucket is still open: never judged
    params: dict[str, Any] = {"name_key": name_key, "tool": tool}
    have = [v for v in vals[: last_closed + 1] if v is not None] or [
        v for v in vals if v is not None
    ]
    if not have:
        return {"key": "st_sent_none", "params": params}
    band = series.get("band")
    if banded and band:
        n = 0
        for i in range(last_closed, -1, -1):
            if vals[i] is None:
                continue
            if br[i] if i < len(br) else False:
                n += 1
            else:
                break
        if n:
            before = None
            seen = 0
            for i in range(last_closed, -1, -1):
                if vals[i] is None:
                    continue
                seen += 1
                if seen > n:
                    before = vals[i]
                    break
            if before is None:
                before = (band["low"] + band["high"]) // 2
            now_v = have[-1]
            unit_key = _unit_word(BUCKET_UNIT[view], n)
            params.update(a=fmt(before), b=fmt(now_v), n=n, unit_key=unit_key)
            return {
                "key": "st_sent_up" if now_v > band["high"] else "st_sent_down",
                "params": params,
            }
        return {"key": "st_sent_stay", "params": params}
    params.update(a=fmt(have[0]), b=fmt(have[-1]))
    return {"key": "st_sent_plain", "params": params}


# ------------------------------------------------------------------------------ agent block


def _threshold(ctx: Any, agent_id: str, metric: str, default: int) -> int:
    for scope in (agent_id, "*"):
        row = ctx.state.get("policy_threshold", {"agent_id": scope, "metric": metric})
        if row is not None and isinstance(row.get("threshold"), int):
            return int(row["threshold"])
    return default


def _baseline(ctx: Any, agent_id: str, version: str | None) -> dict[str, dict[str, Any]]:
    """The stored normal range of the newest version, ``metric -> {low, high, ...}``."""
    rows = [dict(r) for r in ctx.state.query("policy_baseline", {"agent_id": agent_id})]
    if not rows:
        return {}
    if version is not None and any(r["agent_version"] == version for r in rows):
        rows = [r for r in rows if r["agent_version"] == version]
    else:
        newest = max(rows, key=lambda r: str(r["computed_at"]))["agent_version"]
        rows = [r for r in rows if r["agent_version"] == newest]
    return {
        r["metric"]: {
            "low": int(r["band_low"]),
            "high": int(r["band_high"]),
            "center": int(r["center"]),
            "window_s": int(r["window_s"]),
            "windows": int(r["windows"]),
            "computed_at": r["computed_at"],
            "open_case_id": r.get("open_case_id"),
        }
        for r in rows
    }


def _cases(ctx: Any, agent_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in ctx.state.query("cases", {"agent_id": agent_id})]


def _alert_times(cases: Sequence[Mapping[str, Any]], ctx: Any, agent_id: str) -> list[dt.datetime]:
    """When the conversation monitor raised an alert: its cases and its session holds."""
    out: list[dt.datetime] = []
    for c in cases:
        if c.get("case_type") == "session_escalation" and c.get("opened_at") is not None:
            out.append(as_dt(c["opened_at"]))
    try:
        for r in ctx.state.query("session_control", {"agent_id": agent_id}):
            out.append(as_dt(r["created_at"]))
    except Exception:  # noqa: BLE001 - leave this part out rather than break the tab
        log.debug("stability: part skipped", exc_info=True)
    return sorted(out)


def _label(view: str, t: dt.datetime) -> str:
    local = readmodels.ict(t)
    assert local is not None
    if view == "week":
        return local.strftime("%d/%m")
    if view == "day":
        return local.strftime("%d/%m %H:00")
    if view == "live":
        return local.strftime("%H:%M:%S")
    return local.strftime("%H:%M")


def agent_block(ctx: Any, agent_id: str, view: str, now: dt.datetime) -> dict[str, Any]:
    """Everything the page shows for one agent."""
    s = ctx.settings
    agent = ctx.state.get("agent", {"agent_id": agent_id})
    gate_state = str(agent["gate_state"]) if agent else ""
    min_n = int(getattr(s, "drift_min_n", 20))

    cases = _cases(ctx, agent_id)
    first_rows = _rows(ctx, "agent_event", agent_id, EVENT_COLS_V, None, 1)
    base_probe = _baseline(
        ctx, agent_id, first_rows[0].get("agent_version") if first_rows else None
    )
    window_s = next(
        (b["window_s"] for b in base_probe.values()), int(getattr(s, "drift_window_s", 86400))
    )
    bucket_s, n_buckets = spec(view, window_s)
    end = floor_window(now, bucket_s) + dt.timedelta(seconds=bucket_s)
    start = end - dt.timedelta(seconds=bucket_s * n_buckets)
    m = _threshold(ctx, agent_id, "drift.consecutive", int(getattr(s, "drift_consecutive", 3)))
    n_check = m + 2
    chk_start = floor_window(now, window_s) - dt.timedelta(seconds=window_s * n_check)
    since = min(start, chk_start)
    events_all, truncated = load_events(ctx, agent_id, since)
    verdicts_all = load_verdicts(ctx, agent_id, since)

    base: dict[str, Any] = {
        "agent_id": agent_id,
        "gate_state": gate_state,
        "view": view,
        "window_s": window_s,
        "m": m,
        "min_n": min_n,
    }
    unit, count = window_words(window_s)
    base["window"] = {"unit_key": _unit_word(unit, count), "count": count}
    need_s = window_s * int(getattr(s, "drift_baseline_windows", FALLBACK_BASELINE_WINDOWS))
    need_unit, need_count = window_words(need_s)
    base["need"] = {
        "unit_key": _unit_word(need_unit, need_count),
        "count": need_count,
    }

    if not events_all:
        any_event = bool(first_rows)
        base.update(
            state="nodata",
            why="quiet"
            if any_event
            else ("waiting" if gate_state in ("RUNNING", "PAUSED") else "notlive"),
            names=[],
            has_data=False,
            charts=[],
            timeline=[],
        )
        return base

    version = next(
        (
            e.get("agent_version")
            for e in sorted(events_all, key=lambda e: e["_ts"], reverse=True)
            if e.get("agent_version")
        ),
        None,
    )
    events = [e for e in events_all if e.get("agent_version") == version] if version else events_all
    bands = _baseline(ctx, agent_id, version)
    if bands:
        window_s = next(iter(bands.values()))["window_s"]
        base["window_s"] = window_s
    tools_base = sorted(k.split(":", 1)[1] for k in bands if k.startswith("tool_share_bp:"))
    if tools_base:
        tools = tools_base
    else:
        counts: dict[str, int] = {}
        for e in events:
            if e.get("event_type") == "gate_decision" and e.get("tool_name"):
                counts[str(e["tool_name"])] = counts.get(str(e["tool_name"]), 0) + 1
        tools = [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_TOOLS]]
    tools = tools[:MAX_TOOLS]

    # ---- verdict (drift windows, closed only)
    chk_end = floor_window(now, window_s)
    chk_start = chk_end - dt.timedelta(seconds=window_s * n_check)
    ev_g = group(events, chk_start, window_s, n_check)
    vd_g = group(verdicts_all, chk_start, window_s, n_check)
    windows = [
        bucket_values(ev_g[i], vd_g[i], min_n=min_n, tools=tools_base) for i in range(n_check)
    ]
    drift_open = any(c.get("case_type") == "drift" and c.get("status") in OPEN_CASE for c in cases)
    alerts = _alert_times(cases, ctx, agent_id)
    sess_from = chk_end - dt.timedelta(seconds=window_s * m)
    session_alert = any(sess_from <= a for a in alerts)
    drift_names = [k for k in bands if k in DRIFT_NAMES or k.startswith("tool_share_bp:")]
    verdict = decide(
        windows,
        {k: bands[k] for k in drift_names},
        m=m,
        drift_case_open=drift_open,
        session_alert=session_alert,
    )
    if not bands:
        verdict["why"] = "collecting" if events else "nobase"
        first = min(e["_ts"] for e in events_all)
        have_s = max(0, int((now - first).total_seconds()))
        hu, hc = window_words(min(have_s, need_s) if have_s >= 60 else 60)
        verdict["have"] = {
            "unit_key": _unit_word(hu, hc),
            "count": hc,
        }
        verdict["have_pct"] = min(100, have_s * 100 // max(1, need_s))
    verdict["names_h"] = [metric_name(k) for k in verdict.get("names", [])]
    base.update(verdict)
    base["has_data"] = True
    base["bands_n"] = len(bands)
    base["drift_open"] = drift_open
    base["version"] = version or ""
    base["truncated"] = truncated
    base["checked_window"] = {"from": chk_start.isoformat(), "to": chk_end.isoformat()}

    # ---- charts
    ev_b = group(events, start, bucket_s, n_buckets)
    vd_b = group(verdicts_all, start, bucket_s, n_buckets)
    buckets = [bucket_values(ev_b[i], vd_b[i], min_n=min_n, tools=tools) for i in range(n_buckets)]
    labels = [_label(view, start + dt.timedelta(seconds=bucket_s * i)) for i in range(n_buckets)]
    banded = bool(bands) and bucket_s == window_s
    alert_counts = [0] * n_buckets
    for a in alerts:
        i = int((a.timestamp() - start.timestamp()) // bucket_s)
        if 0 <= i < n_buckets:
            alert_counts[i] += 1
    base["charts"] = build_charts(
        buckets,
        labels,
        bands,
        tools,
        view=view,
        banded=banded,
        alert_counts=alert_counts,
        session_on=bool(getattr(s, "session_monitor_enabled", False)),
        partial_last=True,
    )
    base["banded"] = banded
    base["band_note"] = bool(bands) and not banded
    base["labels"] = [labels[0], labels[-1]]
    base["timeline"] = timeline(ctx, agent_id, cases, bands, now)
    return base


DRIFT_NAMES = (
    "amount_p50",
    "amount_p90",
    "block_rate_bp",
    "judge_p50_bp",
    "judge_p90_bp",
    "latency_p50_ms",
    "latency_p90_ms",
)


def _series(
    key: str,
    buckets: Sequence[Mapping[str, int | None]],
    bands: Mapping[str, Mapping[str, Any]],
    banded: bool,
    *,
    dash: bool = False,
) -> dict[str, Any]:
    vals = [b.get(key) for b in buckets]
    if key == "calls":  # before the first call the agent was not live: a gap, not zero
        first = next((i for i, v in enumerate(vals) if v), len(vals))
        vals = [None] * first + vals[first:]
    band = bands.get(key) if banded else None
    breach = [False] * len(vals)
    if band:
        for i, v in enumerate(vals[:-1]):  # the open bucket is never judged
            breach[i] = outside(v, band)
    return {"key": key, "values": vals, "band": band, "breach": breach, "dash": dash}


def build_charts(
    buckets: Sequence[Mapping[str, int | None]],
    labels: Sequence[str],
    bands: Mapping[str, Mapping[str, Any]],
    tools: Sequence[str],
    *,
    view: str,
    banded: bool,
    alert_counts: Sequence[int],
    session_on: bool,
    partial_last: bool = True,
) -> list[dict[str, Any]]:
    """The seven charts, each with panels, a plain sentence and a table of its numbers."""
    charts: list[dict[str, Any]] = []

    def chart(
        cid: str,
        panels: list[dict[str, Any]],
        *,
        sent: dict[str, Any],
        note: str = "",
        mock: bool = False,
    ) -> None:
        charts.append({"id": cid, "panels": panels, "sentence": sent, "note": note, "mock": mock})

    def panel(
        series: list[dict[str, Any]],
        unit: str,
        name_keys: list[str],
        *,
        title: str = "",
        kind: str = "line",
        mock: bool = False,
    ) -> dict[str, Any]:
        return {
            "svg": panel_svg(
                series,
                labels,
                unit,
                kind=kind,
                partial_last=partial_last,
                compact=bool(title) and not mock,
            ),
            "series": [
                {
                    "key": s["key"],
                    "name_key": nk,
                    "dash": s.get("dash", False),
                    "has_band": bool(s.get("band")),
                }
                for s, nk in zip(series, name_keys, strict=True)
            ],
            "title": title,
            "unit": unit,
            "mock": mock,
            "rows": [
                {"label": labels[i], **{s["key"]: FORMATS[unit](s["values"][i]) for s in series}}
                for i in range(len(labels))
            ],
        }

    def pick(
        series: list[dict[str, Any]], name_keys: list[str], unit: str, tool: str = ""
    ) -> dict[str, Any]:
        """The sentence of the worst series (a breach first), else the first with data."""
        order = sorted(
            range(len(series)),
            key=lambda i: (-(sum(series[i]["breach"]) if series[i].get("breach") else 0), i),
        )
        for i in order:
            if any(v is not None for v in series[i]["values"]):
                return sentence(name_keys[i], series[i], unit, view, tool=tool, banded=banded)
        return sentence(name_keys[0], series[0], unit, view, tool=tool, banded=banded)

    # 1 calls
    s = [_series("calls", buckets, bands, False)]
    chart("calls", [panel(s, "n", ["st_m_calls"])], sent=pick(s, ["st_m_calls"], "n"))
    # 2 stopped share
    s = [_series("block_rate_bp", buckets, bands, banded)]
    chart("stopped", [panel(s, "bp", ["st_m_stopped"])], sent=pick(s, ["st_m_stopped"], "bp"))
    # 3 amounts
    s = [
        _series("amount_p50", buckets, bands, banded),
        _series("amount_p90", buckets, bands, banded, dash=True),
    ]
    nk = ["st_m_amount_p50", "st_m_amount_p90"]
    chart("amount", [panel(s, "vnd", nk)], sent=pick(s, nk, "vnd"))
    # 4 tool mix: small multiples
    panels = []
    sents: list[dict[str, Any]] = []
    all_series = []
    for tool in tools:
        sr = _series(f"tool_share_bp:{tool}", buckets, bands, banded)
        all_series.append((tool, sr))
        panels.append(panel([sr], "bp", ["st_m_tool"], title=tool))
    if all_series:
        worst = max(all_series, key=lambda ts: sum(ts[1]["breach"]))
        sents.append(sentence("st_m_tool", worst[1], "bp", view, tool=worst[0], banded=banded))
    chart(
        "mix",
        panels,
        sent=sents[0]
        if sents
        else {"key": "st_sent_none", "params": {"name_key": "st_m_mix", "tool": ""}},
    )
    # 5 latency: the agent's own latency when it is reported, else the gate answer time
    own = any(b.get("latency_p50_ms") is not None for b in buckets)
    if own:
        s = [
            _series("latency_p50_ms", buckets, bands, banded),
            _series("latency_p90_ms", buckets, bands, banded, dash=True),
        ]
        nk = ["st_m_lat_p50", "st_m_lat_p90"]
        chart("latency", [panel(s, "ms", nk)], sent=pick(s, nk, "ms"))
    else:
        s = [
            _series("gate_p50_ms", buckets, bands, False),
            _series("gate_p90_ms", buckets, bands, False, dash=True),
        ]
        nk = ["st_m_gate_p50", "st_m_gate_p90"]
        chart("latency", [panel(s, "ms", nk)], sent=pick(s, nk, "ms"), note="st_note_gate_latency")
    # 6 judge suspicion: real and mock judges kept apart
    real = [
        _series("judge_p50_bp", buckets, bands, banded),
        _series("judge_p90_bp", buckets, bands, banded, dash=True),
    ]
    mock = [
        _series("mock_p50_bp", buckets, bands, False),
        _series("mock_p90_bp", buckets, bands, False, dash=True),
    ]
    has_real = any(v is not None for sr in real for v in sr["values"])
    has_mock = any(v is not None for sr in mock for v in sr["values"])
    jp = []
    if has_real or not has_mock:
        jp.append(panel(real, "bp", ["st_m_judge_p50", "st_m_judge_p90"]))
    if has_mock:
        jp.append(
            panel(mock, "bp", ["st_m_judge_p50", "st_m_judge_p90"], title="st_mock", mock=True)
        )
    chart(
        "judge",
        jp,
        sent=pick(real, ["st_m_judge_p50", "st_m_judge_p90"], "bp")
        if has_real or not has_mock
        else {"key": "st_sent_mock", "params": {"name_key": "st_m_judge_p50", "tool": ""}},
        mock=has_mock,
    )
    # 7 conversation alerts
    sv = [
        {
            "key": "alerts",
            "values": list(alert_counts),
            "band": None,
            "breach": [False] * len(alert_counts),
        }
    ]
    total = sum(alert_counts)
    sent = (
        {
            "key": "st_sent_alerts_n",
            "params": {"name_key": "st_m_alerts", "tool": "", "b": fmt_int(total)},
        }
        if total
        else {
            "key": "st_sent_alerts_0" if session_on else "st_sent_alerts_off",
            "params": {"name_key": "st_m_alerts", "tool": ""},
        }
    )
    chart("session", [panel(sv, "n", ["st_m_alerts"], kind="bars")], sent=sent)
    order = ["calls", "stopped", "amount", "latency", "mix", "judge", "session"]
    return sorted(charts, key=lambda c: order.index(c["id"]))


# ------------------------------------------------------------------------------ timeline


def timeline(
    ctx: Any,
    agent_id: str,
    cases: Sequence[Mapping[str, Any]],
    bands: Mapping[str, Mapping[str, Any]],
    now: dt.datetime,
) -> list[dict[str, Any]]:
    """What changed: cases, pauses, incidents and the new normal range."""
    since = now - dt.timedelta(days=HISTORY_DAYS)
    items: list[dict[str, Any]] = []

    def add(ts: Any, kind: str, link: str = "", **params: Any) -> None:
        try:
            t = as_dt(ts)
        except (ValueError, TypeError):
            return
        if t >= since:
            items.append({"ts": t, "kind": kind, "link": link, "params": params})

    for c in cases:
        kind = (
            "case_drift"
            if c.get("case_type") == "drift"
            else ("case_session" if c.get("case_type") == "session_escalation" else "case")
        )
        add(
            c.get("opened_at"),
            kind,
            f"/console/cases/{c['case_id']}",
            id=str(c["case_id"]),
            sev=str(c.get("severity") or ""),
        )
    try:
        stops = sorted(
            (as_dt(g["created_at"]), str(g.get("action")))
            for g in ctx.state.query("gate_control", {"agent_id": agent_id})
            if str(g.get("action")) in ("pause", "quarantine") and g.get("created_at") is not None
        )
        runs: list[list[tuple[dt.datetime, str]]] = []
        for item in stops:  # stops close together are one line ("paused 8 times")
            if runs and (item[0] - runs[-1][-1][0]).total_seconds() <= PAUSE_RUN_S:
                runs[-1].append(item)
            else:
                runs.append([item])
        for run in runs:
            last_ts, action = run[-1]
            add(
                last_ts,
                ("pause" if action == "pause" else "quarantine") + ("_n" if len(run) > 1 else ""),
                f"/console/agents/{agent_id}",
                n=len(run),
            )
    except Exception:  # noqa: BLE001 - leave this part out rather than break the tab
        log.debug("stability: part skipped", exc_info=True)
    try:
        for i in ctx.state.query("incident", {"agent_id": agent_id}):
            add(
                i.get("opened_at"),
                "incident",
                f"/console/incidents/{i['incident_id']}",
                title=str(i.get("title") or "")[:90],
            )
    except Exception:  # noqa: BLE001 - leave this part out rather than break the tab
        log.debug("stability: part skipped", exc_info=True)
    if bands:
        seen = {str(b["computed_at"]) for b in bands.values()}
        for ts in seen:
            add(ts, "baseline", "", n=len(bands))
    return sorted(items, key=lambda x: x["ts"], reverse=True)


def system_timeline(ctx: Any, system_id: str, now: dt.datetime) -> list[dict[str, Any]]:
    since = now - dt.timedelta(days=HISTORY_DAYS)
    out = []
    try:
        for g in ctx.state.query("guardian_binding", {"system_id": system_id}):
            try:
                t = as_dt(g["set_at"])
            except (ValueError, TypeError):
                continue
            if t >= since and g.get("set_by"):
                out.append(
                    {
                        "ts": t,
                        "kind": "guardian",
                        "link": f"/console/systems/{system_id}?tab=guardians",
                        "params": {"slug": str(g["feature_slug"]), "state": str(g["state"])},
                    }
                )
    except Exception:  # noqa: BLE001 - leave this part out rather than break the tab
        log.debug("stability: part skipped", exc_info=True)
    return out


# ------------------------------------------------------------------------------ page data


def parse_query(
    query: Mapping[str, str], agents: Sequence[str], window_s: int
) -> tuple[str, str | None, bool]:
    view = query.get("view") or view_for_window(window_s)
    if view not in views_for(window_s):
        raise StabilityError("Unknown time range. Choose one of the ranges shown.")
    agent = query.get("agent") or None
    if agent is not None and agent not in agents:
        raise StabilityError("This agent is not part of the AI system.")
    live = (query.get("live") or "1") != "0"
    return view, agent, live


def window_of(ctx: Any, agent_id: str | None) -> int:
    """The drift window in seconds: the stored one of the agent, else the setting."""
    if agent_id:
        first = _baseline(ctx, agent_id, None)
        ws = next((b["window_s"] for b in first.values()), None)
        if ws:
            return int(ws)
    return int(getattr(ctx.settings, "drift_window_s", 86400))


def page_data(ctx: Any, system: Mapping[str, Any], query: Mapping[str, str]) -> dict[str, Any]:
    """Template variables of the Stability tab and of its refresh fragment (key ``stab``)."""
    require_on(ctx.settings)
    agents = sorted({str(c["ref_id"]) for c in system["components"] if c["ref_kind"] == "agent"})
    now = ctx.clock.now()
    # the default range is the one whose bucket is the drift window (band and breach marks show)
    window_s = window_of(ctx, agents[0] if agents else None)
    view, agent, live = parse_query(query, agents, window_s)
    sid = str(system["system_id"])
    if not agents:
        return {
            "stab": {
                "system_id": sid,
                "agents": [],
                "state": "nodata",
                "why": "noagent",
                "view": view,
                "live": live,
                "views": views_for(window_s),
                "refresh_s": LIVE_REFRESH_S if view == "live" else REFRESH_S,
                "live_s": window_s,
            }
        }
    blocks = {a: agent_block(ctx, a, view, now) for a in agents}
    chosen = agent or max(
        agents,
        key=lambda a: (blocks[a].get("has_data", False), RANK[blocks[a]["state"]], a == agents[0]),
    )
    deciding = [b for b in blocks.values() if b["state"] != "nodata"] or list(blocks.values())
    top = max(deciding, key=lambda b: RANK[b["state"]])
    tl = list(blocks[chosen].get("timeline", [])) + system_timeline(ctx, sid, now)
    tl.sort(key=lambda x: x["ts"], reverse=True)
    return {
        "stab": {
            "system_id": sid,
            "agents": agents,
            "blocks": blocks,
            "agent": chosen,
            "b": blocks[chosen],
            "state": top["state"],
            "top": top,
            "view": view,
            "views": views_for(window_s),
            "refresh_s": LIVE_REFRESH_S if view == "live" else REFRESH_S,
            "live_s": window_s,
            "live": live,
            "timeline": tl[:TIMELINE_ROWS],
            "now": now,
        }
    }


def agent_link(ctx: Any, me: Any, agent_id: str) -> str | None:
    """For the Post-deploy tab of an agent: the Stability tab of the first visible system the
    agent belongs to (``None`` while the tab is off or the agent is in no system)."""
    if not getattr(ctx.settings, "stability_tab", False):
        return None
    try:
        rows = ctx.state.query("system_component", {"ref_kind": "agent", "ref_id": agent_id})
        for r in sorted(rows, key=lambda r: str(r["system_id"])):
            if r.get("active") in (True, 1) and ctx.systems.can_view(me, str(r["system_id"])):
                return f"/console/systems/{r['system_id']}?tab=stability"
    except Exception:  # noqa: BLE001 - no link rather than a broken tab
        return None
    return None
