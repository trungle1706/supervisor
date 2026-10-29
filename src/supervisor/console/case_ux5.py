"""UX5 case page helpers (CONSOLE_UX5, group G6): group repeated story events and rule hits.

Pure functions over the lists ``readmodels.case_detail`` returns; the off path never calls them."""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from typing import Any

from supervisor.console.ux5 import page_slice

# Story keys whose repeats collapse into one line with a count.
GROUPABLE = frozenset(
    {
        "st_rule_pause",
        "st_rule_block",
        "st_t0b",
        "st_judge",
        "st_planned",
        "st_read",
        "st_called",
        "ev_join",
    }
)

TRANSCRIPT_PAGE = 25
CHECK_LOG_CAP = 25


def _story_key(item: Mapping[str, Any]) -> Hashable:
    key = str(item.get("key"))
    p = item.get("params") or {}
    if key in ("st_rule_pause", "st_rule_block"):
        return (key, p.get("rule"))
    if key in ("st_planned", "st_read", "st_called"):
        return (key, p.get("tool"))
    if key == "st_judge":
        return (key, p.get("tier"), p.get("label"), p.get("action"))
    return (key,)


def group_story(story: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Group the story timeline. Each entry: ``{item, items, count, ts_from, ts_to, grouped}``.
    ``item`` is the first member (its text renders a singleton or the expanded rows)."""
    out: list[dict[str, Any]] = []
    index: dict[Hashable, dict[str, Any]] = {}
    for it in story:
        if it.get("key") in GROUPABLE:
            k = _story_key(it)
            g = index.get(k)
            if g is None:
                g = {"item": it, "items": [], "count": 0, "ts_from": it["ts"], "ts_to": it["ts"]}
                index[k] = g
                out.append(g)
            g["items"].append(it)
            g["count"] += 1
            g["ts_to"] = it["ts"]
        else:
            out.append(
                {"item": it, "items": [it], "count": 1, "ts_from": it["ts"], "ts_to": it["ts"]}
            )
    for g in out:
        g["grouped"] = g["count"] > 1
    return out


def group_verdicts(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One row per rule / screen / judge with a hit count and the first and last time."""
    out: list[dict[str, Any]] = []
    index: dict[Hashable, dict[str, Any]] = {}
    for r in rows:
        k = (r.get("source"), r.get("rule_id"), r.get("tier"), r.get("action"), r.get("label"))
        g = index.get(k)
        if g is None:
            g = {"row": r, "count": 0, "ts_from": r["ts"], "ts_to": r["ts"]}
            index[k] = g
            out.append(g)
        g["count"] += 1
        g["ts_to"] = r["ts"]
    return out


def build(data: Mapping[str, Any], page: Any = 1) -> dict[str, Any]:
    """The extra context the UX5 case templates read (key ``g6``)."""
    story = data.get("story") or []
    verdict_rows = data.get("verdict_rows") or []
    transcript = data.get("transcript") or []
    t_rows, t_page, t_pages = page_slice(transcript, page, TRANSCRIPT_PAGE)
    return {
        "groups": group_story(story),
        "stops": ((data.get("head") or {}).get("joined") or 0) + 1,
        "rule_groups": group_verdicts(verdict_rows),
        "check_log": list(verdict_rows[:CHECK_LOG_CAP]),
        "check_log_total": len(verdict_rows),
        "t_rows": t_rows,
        "t_page": t_page,
        "t_pages": t_pages,
        "t_total": len(transcript),
    }
