"""7-day trend of the multi-turn pack, read from the stored ``eval_result`` rows.

One line per UTC day: runs, conversations, the worst gate catch of the day, the highest number
of unexpected escapes and of open known gaps, the average mock attack success. Integers only.
A day with no run shows ``-``; the table never invents a value.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

PACK_ID = "multiturn_redteam_vi"


def _ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _metrics(row: Mapping[str, Any]) -> Mapping[str, Any]:
    m = row.get("metrics")
    if isinstance(m, str):
        import json

        try:
            m = json.loads(m)
        except ValueError:
            return {}
    return m if isinstance(m, Mapping) else {}


def pack_trend(
    tables: Any,
    pack_id: str = PACK_ID,
    *,
    now: datetime | None = None,
    days: int = 7,
    target_id: str | None = None,
) -> list[dict[str, Any]]:
    """Daily rows for the last ``days`` UTC days, oldest first (always ``days`` rows)."""
    now = now or datetime.now(UTC)
    today = now.astimezone(UTC).date()
    keys = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    where: dict[str, Any] = {"pack_id": pack_id}
    if target_id:
        where["target_id"] = target_id
    try:
        rows = tables.query("eval_result", where, order_by=["ts"])
    except Exception:  # noqa: BLE001 - no table yet (fresh store): an empty trend
        rows = []
    by_day: dict[Any, list[Mapping[str, Any]]] = {k: [] for k in keys}
    for row in rows:
        ts = _ts(row.get("ts"))
        if ts is not None and ts.date() in by_day and row.get("status") in ("ok", "warn", "fail"):
            by_day[ts.date()].append(row)
    out = []
    for k in keys:
        rs = by_day[k]
        ms = [_metrics(r) for r in rs]

        def pick(name: str, ms: list[Mapping[str, Any]] = ms) -> list[int]:
            return [int(m[name]) for m in ms if m.get(name) is not None]

        catch, esc, gaps, succ, conv = (
            pick("gate_catch_bp"),
            pick("unexpected_escape_count"),
            pick("known_gap_open_count"),
            pick("attack_success_bp"),
            pick("conversations"),
        )
        out.append(
            {
                "date": k.isoformat(),
                "runs": len(rs),
                "conversations": sum(conv),
                "gate_catch_bp_min": min(catch) if catch else None,
                "unexpected_escape_max": max(esc) if esc else None,
                "known_gap_open_max": max(gaps) if gaps else None,
                "attack_success_bp_avg": (sum(succ) // len(succ)) if succ else None,
            }
        )
    return out


def render_trend(
    rows: list[dict[str, Any]], title: str = "Multi-turn red team, 7-day trend"
) -> str:
    def s(v: Any) -> str:
        return "-" if v is None else str(v)

    lines = [
        f"## {title}",
        "",
        "| Day (UTC) | Rows | Conversations | Gate catch min (bp) | Unexpected escapes max "
        "| Known gaps open | Mock success avg (bp) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['date']} | {r['runs']} | {r['conversations']} | {s(r['gate_catch_bp_min'])} | "
            f"{s(r['unexpected_escape_max'])} | {s(r['known_gap_open_max'])} | "
            f"{s(r['attack_success_bp_avg'])} |"
        )
    seen = sum(1 for r in rows if r["runs"])
    lines += [
        "",
        f"{seen} of {len(rows)} days have a run. Mock agent; thresholds illustrative.",
        "",
    ]
    return "\n".join(lines)
