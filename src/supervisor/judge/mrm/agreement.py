"""Judge-vs-human agreement from case sign-offs (WP19, docs/metrics.md).

Definition
    A *pair* is a case that a reviewer closed (``signoff.decision`` is ``close:confirmed``
    or ``close:false_alarm``) and that is linked to at least one judge verdict (a
    ``case_link`` row of ``source_kind`` ``judge``, or a linked verdict of tier 1 or 2).
    The judge's label on such a case is ``suspicious`` (it opened or raised the case).
    The pair *agrees* when the reviewer confirmed the case and *disagrees* on a false alarm.

    ``agree_bp = agree * 10000 / pairs`` (integer basis points, round half up), None when
    there are no pairs. The pair time is the time of the closing sign-off (the latest one).

Limit
    This sees only items the judge flagged (precision-type agreement). What the judge
    misses is measured by the golden set, not here.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from supervisor.core.ports import TableStore
from supervisor.core.rows import rows_by
from supervisor.core.timeutil import parse_utc_strict

CLOSE_RESOLUTIONS = {"close:confirmed": "confirmed", "close:false_alarm": "false_alarm"}
JUDGE_LABEL = "suspicious"
DEFAULT_MIN_PAIRS = 5


_ts = parse_utc_strict


def agree_bp(agree: int, pairs: int) -> int | None:
    """Integer basis points, round half up; None when ``pairs`` is 0."""
    if pairs <= 0:
        return None
    return (agree * 20000 + pairs) // (2 * pairs)


def _judge_verdicts_by_case(
    tables: TableStore, links: list[dict[str, Any]] | None = None
) -> dict[str, list[str]]:
    links = tables.query("case_link") if links is None else links
    # One batch read of the verdicts of every gate link, not one query per link.
    gate = rows_by(
        tables,
        "verdict",
        "event_id",
        [str(lk["source_ref"]) for lk in links if lk["source_kind"] == "gate"],
        columns=("event_id", "verdict_id", "tier"),
    )
    out: dict[str, list[str]] = defaultdict(list)
    for link in links:
        kind, ref, case_id = link["source_kind"], str(link["source_ref"]), str(link["case_id"])
        if kind == "judge":
            out[case_id].append(ref)
        elif kind == "gate":
            for v in gate.get(ref, []):
                if int(v["tier"]) in (1, 2):
                    out[case_id].append(str(v["verdict_id"]))
    return {k: sorted(set(v)) for k, v in out.items()}


def agreement_pairs(
    tables: TableStore, *, since: datetime | None = None, until: datetime | None = None
) -> list[dict[str, Any]]:
    """Pairs whose closing sign-off ts is in ``since <= ts < until`` (either bound optional)."""
    links = tables.query("case_link")
    judged = _judge_verdicts_by_case(tables, links)
    agent_of: dict[str, str] = {}
    for lk in links:  # the agent is the same on every link of a case
        agent_of.setdefault(str(lk["case_id"]), str(lk["agent_id"]))
    closes: dict[str, tuple[datetime, str]] = {}
    for s in tables.query("signoff"):
        resolution = CLOSE_RESOLUTIONS.get(str(s["decision"]))
        case_id = str(s["case_id"])
        if resolution is None or case_id not in judged:
            continue
        ts = _ts(s["ts"])
        if case_id not in closes or ts >= closes[case_id][0]:
            closes[case_id] = (ts, resolution)
    out: list[dict[str, Any]] = []
    for case_id, (ts, resolution) in sorted(closes.items(), key=lambda kv: (kv[1][0], kv[0])):
        if (since is not None and ts < since) or (until is not None and ts >= until):
            continue
        agent_id = agent_of[case_id]
        out.append(
            {
                "case_id": case_id,
                "agent_id": agent_id,
                "closed_ts": ts,
                "resolution": resolution,
                "verdict_ids": judged[case_id],
                "judge_label": JUDGE_LABEL,
                "agrees": resolution == "confirmed",
            }
        )
    return out


def agreement_summary(
    tables: TableStore,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    min_pairs: int = DEFAULT_MIN_PAIRS,
) -> dict[str, Any]:
    pairs = agreement_pairs(tables, since=since, until=until)
    per: dict[str, list[bool]] = defaultdict(list)
    for p in pairs:
        per[p["agent_id"]].append(bool(p["agrees"]))
    agree = sum(1 for p in pairs if p["agrees"])
    status = (
        "no_pairs" if not pairs else ("ok" if len(pairs) >= min_pairs else "insufficient_pairs")
    )
    return {
        "status": status,
        "pairs": len(pairs),
        "agree": agree,
        "agree_bp": agree_bp(agree, len(pairs)),
        "min_pairs": min_pairs,
        "by_agent": {
            a: {"pairs": len(v), "agree": sum(v), "agree_bp": agree_bp(sum(v), len(v))}
            for a, v in sorted(per.items())
        },
    }


__all__ = ["agree_bp", "agreement_pairs", "agreement_summary"]
