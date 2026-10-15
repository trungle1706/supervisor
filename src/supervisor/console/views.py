"""Pure helpers for the templates: SBV countdowns, sparklines, metric cells."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

REPORT_WINDOW_S = 24 * 3600
METRIC_KEYS = ("metric_date", "agent_id", "row_version", "updated_at", "computed_at")


def countdown(
    due: dt.datetime | None,
    now: dt.datetime,
    window_s: int = REPORT_WINDOW_S,
    severity: str | None = None,
) -> dict:
    """Remaining time and a colour class at 50 / 80 / 100 % of the window used.

    ``used_bp`` (0..10000) draws the bar; ``kind`` colours it: red when overdue, at 80 %
    used, or for a critical case; amber otherwise. ``secs`` is the absolute remaining (or
    overdue) time for ``duration_text``."""
    if due is None:
        return {"text": "-", "cls": "", "overdue": False, "used_bp": 0, "kind": "", "secs": 0}
    remaining = int((due - now).total_seconds())
    used_bp = 10000 - (remaining * 10000 // window_s) if window_s else 10000
    used_bp = max(0, min(10000, used_bp))
    cls = (
        "c100" if remaining <= 0 else "c80" if used_bp >= 8000 else "c50" if used_bp >= 5000 else ""
    )
    secs = abs(remaining)
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    text = (f"{days}d " if days else "") + f"{hours:02d}:{rem // 60:02d}"
    kind = "red" if remaining <= 0 or used_bp >= 8000 or severity == "critical" else "amber"
    return {
        "text": text,
        "cls": cls,
        "overdue": remaining <= 0,
        "used_bp": used_bp,
        "kind": kind,
        "secs": secs,
    }


DURATION_UNITS = {"en": ("d", "h", "m"), "vi": ("ngày", "giờ", "phút")}


def duration_text(secs: int, lang: str = "en") -> str:
    """'4 d 23 h' when a day or more, else '23 h 59 m' (Vietnamese units for vi)."""
    d_u, h_u, m_u = DURATION_UNITS.get(lang, DURATION_UNITS["en"])
    secs = max(0, int(secs))
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days} {d_u} {hours} {h_u}"
    return f"{hours} {h_u} {minutes} {m_u}"


def to_int(value: Any) -> int | None:
    """A metric value as an int for drawing: rates (0..1 floats) in basis points."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value * 10000) if -1.0 <= value <= 1.0 else round(value)
    return None


def sparkline(values: Sequence[int | None], width: int = 120, height: int = 24) -> Markup:
    """Inline SVG polyline, integer coordinates, scaled to the min..max of the values."""
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if not pts:
        return Markup("")
    lo = min(v for _, v in pts)
    hi = max(v for _, v in pts)
    span = hi - lo
    last = max(len(values) - 1, 1)
    coords = []
    for i, v in pts:
        x = i * (width - 2) // last + 1
        y = height // 2 if span == 0 else (height - 2) - (v - lo) * (height - 4) // span
        coords.append(f"{x},{y}")
    poly = " ".join(coords)
    # Only integers and fixed text go into the markup (no user input).
    return Markup(  # noqa: S704
        f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="trend {lo} to {hi}">'
        f'<line class="base" x1="0" y1="{height - 1}" x2="{width}" y2="{height - 1}"/>'
        f'<polyline points="{poly}"/></svg>'
    )


def metric_cell(name: str, value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "OK" if value else "FAIL"
    if isinstance(value, float):
        if -1.0 <= value <= 1.0:
            return f"{value * 100:.1f}%"
        return f"{value:.2f}"
    if name.endswith("_ms"):
        return f"{value} ms"
    if name.endswith("_s"):
        return f"{value} s"
    return str(value)


def metric_columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Every value column present (tolerates columns added later by WP7)."""
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in METRIC_KEYS and k not in cols:
                cols.append(k)
    return cols


def coverage_bp(rows: Sequence[Mapping[str, Any]]) -> int | None:
    """Share of capabilities with status on/enabled, in basis points."""
    if not rows:
        return None
    on = sum(1 for r in rows if str(r.get("status", "")).lower() in ("on", "enabled", "active"))
    return on * 10000 // len(rows)
