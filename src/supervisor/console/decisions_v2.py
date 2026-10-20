"""Gate decisions page under verdict v2 (WP39, flag CONSOLE_DECISIONS_V2).

Same read model as :mod:`supervisor.console.decisions` (``agent_event`` rows of type
``gate_decision``, the tier-0 ``verdict`` rows, ``case_link``, ``chain_entry``) plus the
``finding`` rows of WP37. Only equality filters go to the store; the rest is applied in Python
over the newest ``CONSOLE_SCAN_CAP`` rows (events, and findings), so the page behaves the same
on SQLite and on Delta. Nothing is written here.

Privacy (R2): every piece of text on screen is MASKED. The gate never stores the arguments of a
call (only a keyed hash), so the Request tab rebuilds the masked request from the recorder
events of the same trace (``args_masked`` / ``result_masked``, capture level ``masked``), and the
text goes through the masker once more before it is shown, like the Traces page. With no masker
configured, or at capture level ``digest``, no request text is shown at all. Fragments of a
finding are located on that masked text: by offset when the text at the offset is the fragment,
else by its token, else listed as "not located". A finding row that holds raw text by mistake is
masked again on the way out, so a buggy detector cannot leak through the console.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from supervisor.analytics.decisions import (
    CODE_RE,
    DIRECTIONS,
    STATUSES,
    direction_of,
    loads,
    not_evaluated,
    status_of,
)
from supervisor.console import decisions as v1
from supervisor.console import ux3
from supervisor.console.listing import (
    ListingError,
    paginate,
    parse_int,
    parse_sort,
    query_string,
    sort_rows,
)
from supervisor.console.readmodels import rules_index
from supervisor.core.detectors import MAX_DEPTH, walk_leaves

DRAWER_TABS = ("request", "response", "detections", "metadata")
FILTERS = (
    "agent",
    "action",
    "rule",
    "tool",
    "range",
    "trace",
    "status",
    "code",
    "noteval",
    "consumer",
    "direction",
    "corr",
)
COLUMNS = ("ts", "agent_id", "tool", "status", "rule_id", "latency_us")
_STATUS_RANK = {
    s: i for i, s in enumerate(("block", "pause", "transform", "report", "skip", "allow"))
}
PAGE_SIZE = v1.PAGE_SIZE
TEXT_CAP = 1000  # characters of one masked leaf shown
MAX_LEAVES = 200  # leaves shown per part
MAX_FINDINGS = 200  # finding rows read for one drawer
EXPORT_PREFIX = "decisions-"
# Columns of the CSV export: an explicit allow-list. Every one is an id, a code, an enum or an
# integer. No arguments, no fragments, no entity tokens, no hashes of arguments, no keys.
EXPORT_COLUMNS = (
    "time_utc",
    "decision_id",
    "request_id",
    "correlation_id",
    "trace_id",
    "agent_id",
    "consumer_id",
    "tool",
    "direction",
    "status",
    "action",
    "rule_ids",
    "finding_codes",
    "not_evaluated_reasons",
    "latency_us",
    "latency_rules_us",
    "latency_detectors_us",
    "case_id",
)


# ---------------------------------------------------------------------------- list


def parse_params(query: Mapping[str, str]) -> dict[str, str]:
    p = v1.parse_params(query)
    code = (query.get("code") or "").strip()
    if code and not CODE_RE.match(code):
        raise ListingError("code: letters, digits and . _ : - only (64 max)")
    noteval = query.get("noteval") or ""
    if noteval not in ("", "1"):
        raise ListingError("unknown not-evaluated filter")
    p.update(
        status=ux3.choice(query, "status", STATUSES),
        code=code,
        noteval=noteval,
        consumer=ux3.ident(query, "consumer"),
        direction=ux3.choice(query, "direction", DIRECTIONS),
        corr=ux3.ident(query, "corr"),
    )
    return p


def _findings_by_event(ctx: Any, agent: str) -> dict[str, list[dict[str, Any]]]:
    where: dict[str, Any] = {"agent_id": agent} if agent else {}
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in ctx.tables.query("finding", where, order_by=("-ts",), limit=ux3.scan_cap(ctx)):
        out[str(f["event_id"])].append(f)
    return out


def _row(
    e: Mapping[str, Any],
    vs: list[dict[str, Any]],
    cases: Mapping[str, str],
    fs: list[dict[str, Any]],
) -> dict[str, Any]:
    row = v1._row(e, vs, cases)
    fired = sorted({str(f["code"]) for f in fs if not f.get("not_executed_reason")})
    row.update(
        status=status_of(e),
        direction=direction_of(e),
        consumer_id=e.get("consumer_id"),
        correlation_id=e.get("correlation_id"),
        request_id=e.get("request_id"),
        codes=fired,
        not_eval=not_evaluated(e, fs),
        latency_rules_us=e.get("latency_rules_us"),
        latency_detectors_us=e.get("latency_detectors_us"),
    )
    return row


def rows_for(ctx: Any, p: Mapping[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """All decision rows that match the filters except the status (so the tiles can count
    them), plus the option lists for the filter bar."""
    where: dict[str, Any] = {"event_type": "gate_decision"}
    if p["agent"]:
        where["agent_id"] = p["agent"]
    cap = ux3.scan_cap(ctx)
    events = ctx.tables.query("agent_event", where, order_by=("-ts",), limit=cap)
    start = ux3.range_start(ctx.clock.now(), p["range"])
    if start is not None:
        events = [e for e in events if e["ts"] >= start]
    verdicts = v1._verdicts_by_event(ctx, p["agent"])
    cases = v1._case_links(ctx)
    findings = _findings_by_event(ctx, p["agent"])
    rows = [
        _row(e, verdicts.get(str(e["event_id"]), []), cases, findings.get(str(e["event_id"]), []))
        for e in events
    ]
    opts = {
        "tools": sorted({r["tool"] for r in rows if r["tool"] != "-"}),
        "rules": sorted({rid for r in rows for rid in r["rule_ids"]} | set(rules_index(ctx))),
        "codes": sorted({c for r in rows for c in r["codes"]}),
        "consumers": sorted({r["consumer_id"] for r in rows if r["consumer_id"]}),
        "capped": len(events) >= cap or sum(map(len, findings.values())) >= cap,
    }
    out = []
    for r in rows:
        if p["tool"] and r["tool"] != p["tool"]:
            continue
        if p["rule"] and p["rule"] not in r["rule_ids"]:
            continue
        if p["trace"] and p["trace"] not in str(r["trace_id"] or ""):
            continue
        if p["action"] and r["action"] != p["action"]:
            continue
        if p["code"] and p["code"] not in r["codes"]:
            continue
        if p["noteval"] and not r["not_eval"]:
            continue
        if p["consumer"] and r["consumer_id"] != p["consumer"]:
            continue
        if p["direction"] and r["direction"] != p["direction"]:
            continue
        if p["corr"] and r["correlation_id"] != p["corr"]:
            continue
        out.append(r)
    return out, opts


def _qs(p: Mapping[str, str], **override: str) -> str:
    return query_string({k: p[k] for k in FILTERS}, **override)


def ordered(rows: list[dict[str, Any]], p: Mapping[str, str]) -> tuple[list[Any], str, str]:
    col, direction = parse_sort(p["sort"], p["dir"], COLUMNS, "ts", "desc")
    shown = [r for r in rows if not p["status"] or r["status"] == p["status"]]
    keys = {
        **v1._KEYS,
        "ts": lambda r: r["ts"],
        "agent_id": lambda r: r["agent_id"],
        "status": lambda r: _STATUS_RANK.get(r["status"], 9),
    }
    return sort_rows(shown, col, direction, keys), col, direction


def list_view(ctx: Any, query: Mapping[str, str]) -> dict[str, Any]:
    p = parse_params(query)
    rows, opts = rows_for(ctx, p)
    shown, col, direction = ordered(rows, p)
    page = paginate(shown, parse_int(p["page"], "page", 1), PAGE_SIZE)
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    tiles = [{"label": "all", "n": len(rows), "on": not p["status"], "qs": _qs(p, status="")}]
    tiles += [
        {"label": f"st_{s}", "n": counts[s], "on": p["status"] == s, "qs": _qs(p, status=s)}
        for s in STATUSES
        if s in ("allow", "report", "transform", "pause", "block") or counts[s]
    ]
    agents = sorted(a["agent_id"] for a in ctx.state.query("agent"))
    base = {k: p[k] for k in FILTERS}
    return {
        "v2": True,
        "tiles": tiles,
        "page": page,
        "params": p,
        "sort_col": col,
        "sort_dir": direction,
        "agent_opts": [(a, a) for a in agents],
        "action_opts": [(a, f"act_{a}") for a in v1.ACTIONS],
        "rule_opts": [(r, r) for r in opts["rules"]],
        "tool_opts": [(t, t) for t in opts["tools"]],
        "range_opts": [(k, f"range_{k}") for k in ux3.RANGES],
        "status_opts": [(s, f"st_{s}") for s in STATUSES],
        "code_opts": [(c, c) for c in opts["codes"]],
        "consumer_opts": [(c, c) for c in opts["consumers"]],
        "direction_opts": [(d, f"dir_{d}") for d in DIRECTIONS],
        "noteval_opts": [("1", "ne_only")],
        "capped": opts["capped"],
        "base_qs": query_string(base),
        "list_qs": query_string({**base, "sort": col, "dir": direction}),
        "export_max": int(ctx.settings.console_export_max_rows),
    }


# ---------------------------------------------------------------------------- masked request


class _Masked:
    """Masked text policy (same as the Traces page): no masker, no text."""

    def __init__(self, ctx: Any) -> None:
        from supervisor.adapters.factory import make_masker

        self.masker = make_masker(ctx.settings)

    def text(self, value: Any) -> str | None:
        """Masked, capped text of a value; None when nothing may be shown."""
        if value is None or self.masker is None:
            return None
        try:
            return str(self.masker.mask(str(value)))[:TEXT_CAP]
        except Exception:  # noqa: BLE001 - a masker error shows nothing rather than raw text
            return None

    def tree(self, value: Any, depth: int = 0) -> Any:
        """Copy of a parsed JSON value with every string leaf (and key) masked and capped."""
        if depth > MAX_DEPTH:
            return "..."
        if isinstance(value, str):
            return self.text(value) or ""
        if isinstance(value, Mapping):
            return {
                (self.text(k) or "*"): self.tree(v, depth + 1) for k, v in list(value.items())[:200]
            }
        if isinstance(value, list | tuple):
            return [self.tree(v, depth + 1) for v in list(value)[:200]]
        return value


def _parse(text: Any) -> Any:
    if text is None:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return str(text)


def _linked_events(ctx: Any, e: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Recorder events of the same trace that carry masked text (not the gate rows)."""
    try:
        evs = ctx.tables.query(
            "agent_event", {"trace_id": e["trace_id"]}, order_by=("ts",), limit=200
        )
    except Exception:  # noqa: BLE001 - the tab degrades to "no text", never a 500
        return []
    return [
        x
        for x in evs
        if x["event_type"] != "gate_decision" and str(x.get("capture_level")) != "digest"
    ]


def request_parts(ctx: Any, e: Mapping[str, Any], masked: _Masked) -> dict[str, Any]:
    """Masked request material by detector part: ``args``, ``tool_results``, ``output``."""
    if masked.masker is None:
        return {}
    linked = _linked_events(ctx, e)
    same = [x for x in linked if x["span_id"] == e["span_id"]]
    parts: dict[str, Any] = {}
    calls = [x for x in same if x["event_type"] == "tool_call" and x.get("args_masked")]
    if calls:
        parts["args"] = masked.tree(_parse(calls[-1]["args_masked"]))
    results = [
        masked.tree(_parse(x["result_masked"]))
        for x in linked
        if x["event_type"] == "tool_call"
        and x.get("result_masked")
        and x["span_id"] != e["span_id"]
        and x["ts"] <= e["ts"]
    ][-5:]
    if results:
        parts["tool_results"] = results
    outs = [
        x
        for x in (same or linked)
        if x["event_type"] in ("llm_call", "message") and x.get("result_masked")
    ]
    if outs:
        parts["output"] = masked.tree(_parse(outs[-1]["result_masked"]))
    return parts


def _segments(text: str, spans: Sequence[tuple[int, int, int]]) -> list[dict[str, Any]]:
    """Split ``text`` at the span edges. Each segment lists the finding numbers that cover it
    (a list, empty for plain text). Spans are clamped to the text; empty spans are dropped."""
    cuts = {0, len(text)}
    clean = []
    for s, e, i in spans:
        s, e = max(0, s), min(len(text), e)
        if s < e:
            clean.append((s, e, i))
            cuts.update((s, e))
    edges = sorted(cuts)
    out = []
    for a, b in zip(edges, edges[1:], strict=False):
        cover = sorted({i for s, e, i in clean if s <= a and b <= e})
        out.append({"t": text[a:b], "hl": cover})
    return out


def locate(
    text: str, frag: Mapping[str, Any], used: set[tuple[int, int]]
) -> tuple[int, int] | None:
    """Where a fragment sits in a masked leaf: the stored offsets when the text there is the
    fragment, else the first unused occurrence of its text, else None."""
    s, e, t = frag.get("start"), frag.get("end"), frag.get("text")
    if not isinstance(t, str) or not t:
        return None
    if (
        isinstance(s, int)
        and isinstance(e, int)
        and not isinstance(s, bool)
        and 0 <= s < e <= len(text)
        and text[s:e] == t
        and (s, e) not in used
    ):
        return s, e
    at = text.find(t)
    while at >= 0:
        if (at, at + len(t)) not in used:
            return at, at + len(t)
        at = text.find(t, at + 1)
    return None


def build_request_view(
    parts: Mapping[str, Any], findings: Sequence[Mapping[str, Any]], masked: _Masked
) -> dict[str, Any]:
    """Leaves of the masked request with the located fragments highlighted in place, plus the
    fragments that could not be located. ``hl`` numbers index ``marks``."""
    leaves: dict[tuple[str, str], list[str]] = {}
    for part, tree in parts.items():
        for leaf in list(walk_leaves(part, tree))[:MAX_LEAVES]:
            leaves.setdefault((part, leaf.path), []).append(leaf.text)
    spans: dict[tuple[str, str], list[tuple[int, int, int]]] = defaultdict(list)
    used: dict[tuple[str, str], set[tuple[int, int]]] = defaultdict(set)
    marks: list[dict[str, Any]] = []
    unlocated: list[dict[str, Any]] = []
    for f in findings:
        if f.get("not_executed_reason"):
            continue
        for fr in loads(f.get("fragments_masked"), []) or []:
            if not isinstance(fr, dict):
                continue
            mark = {"n": len(marks) + 1, "code": str(f["code"])[:64]}
            part, path = str(fr.get("part")), str(fr.get("path"))
            cands = [(part, path)] + [k for k in leaves if k[0] == part and k != (part, path)]
            hit = None
            for key in cands:
                for text in leaves.get(key, []):
                    at = locate(text, fr, used[key])
                    if at is not None:
                        hit = (key, at)
                        break
                if hit:
                    break
            if hit is None:
                shown = masked.text(fr.get("text"))
                unlocated.append({**mark, "part": part, "path": path[:120], "text": shown})
                continue
            key, (s, e) = hit
            used[key].add((s, e))
            spans[key].append((s, e, mark["n"]))
            marks.append(mark)
    out_parts = []
    for part in ("args", "tool_results", "output"):
        rows = []
        for (p, path), texts in leaves.items():
            if p != part:
                continue
            for text in texts:
                rows.append({"path": path, "segments": _segments(text, spans.get((p, path), []))})
        if rows:
            out_parts.append({"part": part, "leaves": rows})
    return {"parts": out_parts, "unlocated": unlocated, "marks": marks}


# ---------------------------------------------------------------------------- drawer


def _finding_view(f: Mapping[str, Any], masked: _Masked) -> dict[str, Any]:
    ents = loads(f.get("entities_masked"), []) or []
    frags = loads(f.get("fragments_masked"), []) or []
    return {
        "detector_id": f["detector_id"],
        "slug": f["detector_slug"],
        "code": f["code"],
        "score_bp": f.get("score_bp"),
        "threshold_bp": f.get("threshold_bp"),
        "hint": f.get("action_hint"),
        "mock": bool(f.get("is_mock")),
        "preset": f.get("preset"),
        "reason": f.get("not_executed_reason"),
        "masked_count": f.get("masked_count"),
        "entities": [
            {
                "type": str(x.get("type"))[:32],
                "token": masked.text(x.get("token")),
                "count": x.get("count"),
            }
            for x in ents[:20]
            if isinstance(x, dict)
        ],
        "fragments": [
            {
                "part": str(x.get("part"))[:16],
                "path": str(x.get("path"))[:120],
                "start": x.get("start"),
                "end": x.get("end"),
                "text": masked.text(x.get("text")),
                "precision": x.get("precision"),
            }
            for x in frags[:20]
            if isinstance(x, dict)
        ],
    }


OBSERVE_LABELS = {"observe_would_block": "block", "observe_would_pause": "pause"}


def _observed(verdicts: Sequence[Mapping[str, Any]], payload: Mapping[str, Any]) -> dict[str, Any]:
    """The "Observed decision" line (WP38 policy observe mode): the mode of the decision, what
    the policy would have done, and whether approvals were present. Read from the tier-0 verdict
    rows (labels ``observe_would_block`` / ``observe_would_pause``, also written for a lifted
    GATE-DETECTOR-FAILED); ``approvals`` comes from the chain record when it has the key."""
    would = [OBSERVE_LABELS[v["label"]] for v in verdicts if v.get("label") in OBSERVE_LABELS]
    state = str(payload.get("agent_state") or "")
    mode = "observe" if would else ("shadow" if state == "SHADOW" else "enforce")
    ap = payload.get("approvals")
    approvals = None if ap is None else bool(ap)
    return {
        "mode": mode,
        "decision": ("pause" if "pause" in would else "block") if would else None,
        "approvals": approvals,
    }


def resolve_ref(ctx: Any, *, event: str = "", correlation: str = "") -> str:
    """Decision id for a deep link: ``?event=`` (decision id, else request id) or
    ``?correlation=`` (the newest decision of that correlation id)."""
    if event:
        if not ux3.ID.match(event):
            raise ListingError("event: not a valid id")
        for col in ("event_id", "request_id"):
            rows = ctx.tables.query(
                "agent_event",
                {col: event, "event_type": "gate_decision"},
                order_by=("-ts",),
                limit=1,
            )
            if rows:
                return str(rows[0]["event_id"])
        raise ListingError("no gate decision has that event or request id")
    if not ux3.ID.match(correlation):
        raise ListingError("correlation: not a valid id")
    rows = ctx.tables.query(
        "agent_event",
        {"correlation_id": correlation, "event_type": "gate_decision"},
        order_by=("-ts",),
        limit=1,
    )
    if not rows:
        raise ListingError("no gate decision has that correlation id")
    return str(rows[0]["event_id"])


def drawer_view(ctx: Any, event_id: str, tab: str, query: Mapping[str, str]) -> dict[str, Any]:
    if tab not in DRAWER_TABS:
        raise ListingError("unknown drawer tab")
    events = ctx.tables.query("agent_event", {"event_id": event_id, "event_type": "gate_decision"})
    if not events:
        raise ListingError(f"gate decision {event_id} not found")
    e = events[0]
    masked = _Masked(ctx)
    vs = ctx.tables.query("verdict", {"event_id": event_id}, order_by=("ts",))
    t0 = [v for v in vs if int(v["tier"]) == 0]
    fs = ctx.tables.query(
        "finding", {"event_id": event_id}, order_by=("detector_slug",), limit=MAX_FINDINGS
    )
    cases = v1._case_links(ctx)
    row = _row(e, t0, cases, fs)
    hits = v1._hits(t0)
    rules = rules_index(ctx)
    rule_rows = [
        {
            "rule_id": h["rule_id"],
            "action": h["action"],
            "severity": (rules.get(h["rule_id"]) or {}).get("severity"),
            "text": (rules.get(h["rule_id"]) or {}).get("description") or "",
            "regulation_ref": (rules.get(h["rule_id"]) or {}).get("regulation_ref"),
        }
        for h in hits
    ]
    chain = v1._chain(ctx, event_id)
    payload: dict[str, Any] = {}
    if chain is not None:
        pr = ctx.tables.query("chain_payload", {"lane": chain["lane"], "seq": chain["seq"]})
        loaded = loads(pr[0]["payload"], {}) if pr else {}
        payload = loaded if isinstance(loaded, dict) else {}
    cid = e.get("correlation_id")
    alerts = (
        [
            {"alert_id": a["alert_id"], "rule_id": a["rule_id"], "severity": a["severity"]}
            for a in ctx.state.query("alert", {"correlation_id": cid})
        ][:20]
        if cid
        else []
    )
    shared = (
        len(
            ctx.tables.query(
                "agent_event",
                {"correlation_id": cid, "event_type": "gate_decision"},
                limit=500,
            )
        )
        if cid
        else 0
    )
    fviews = [_finding_view(f, masked) for f in fs]
    parts = request_parts(ctx, e, masked) if tab in ("request", "response", "detections") else {}
    view = (
        build_request_view(parts, fs, masked)
        if parts or fs
        else {"parts": [], "unlocated": [], "marks": []}
    )
    lat = row["latency_us"]
    rules_us, det_us = e.get("latency_rules_us"), e.get("latency_detectors_us")
    split = {
        "total": lat,
        "rules": rules_us,
        "detectors": det_us,
        "overhead": (
            max(0, int(lat) - int(rules_us) - int(det_us))
            if None not in (lat, rules_us, det_us)
            else None
        ),
        "per_detector": loads(e.get("detector_latency_json"), {}) or {},
    }
    cov = loads(e.get("coverage_json"), {})
    cov = cov if isinstance(cov, dict) else {}
    observed = _observed(t0, payload)
    p = parse_params(query)
    rows, _ = rows_for(ctx, p)
    ids = [r["event_id"] for r in ordered(rows, p)[0]]
    i = ids.index(event_id) if event_id in ids else -1
    reason = next((h.get("rationale_masked") for h in hits), None) or (
        vs[0].get("rationale_masked") if vs else None
    )
    doc = {
        "event_id": event_id,
        "request_id": e.get("request_id") or payload.get("request_id"),
        "correlation_id": cid,
        "ts": e["ts"].isoformat() if isinstance(e["ts"], dt.datetime) else str(e["ts"]),
        "agent_id": e["agent_id"],
        "consumer_id": e.get("consumer_id"),
        "tool": e.get("tool_name"),
        "direction": row["direction"],
        "status": row["status"],
        "action": row["action"],
        "rule_ids": row["rule_ids"],
        "finding_codes": row["codes"],
        "not_evaluated": row["not_eval"],
        "latency_us": split,
        "coverage": {
            "inspected": cov.get("inspected", []),
            "not_inspected": [
                {"part": n.get("part"), "reason": n.get("reason")}
                for n in cov.get("not_inspected", [])
                if isinstance(n, dict)
            ],
        },
        "findings": [
            {k: v for k, v in f.items() if k not in ("reason",)}
            | {"not_executed_reason": f["reason"]}
            for f in fviews
        ],
        "request": parts,
    }
    return {
        "v2": True,
        "e": e,
        "row": row,
        "tab": tab,
        "tabs": DRAWER_TABS,
        "rules": rule_rows,
        "chain": chain,
        "payload": payload,
        "reason": masked.text(reason),
        "findings": fviews,
        "fired": [f for f in fviews if not f["reason"]],
        "not_executed": [f for f in fviews if f["reason"]],
        "coverage": cov,
        "view": view,
        "has_text": masked.masker is not None and bool(parts),
        "alerts": alerts,
        "shared": shared,
        "split": split,
        "observed": observed,
        "request_id": doc["request_id"],
        "prev_id": ids[i - 1] if i > 0 else None,
        "next_id": ids[i + 1] if 0 <= i < len(ids) - 1 else None,
        "qs": query_string({k: v for k, v in p.items() if k != "page" and v}),
        "traces_on": bool(ctx.settings.console_traces_enabled),
        "json_text": json.dumps(doc, sort_keys=True, indent=2, default=str),
    }


# ---------------------------------------------------------------------------- export


def _cell(value: Any) -> str:
    """One CSV cell. A cell that a spreadsheet could read as a formula gets a leading quote
    (OWASP CSV injection rule); control characters become spaces."""
    text = "" if value is None else str(value)
    text = "".join(" " if (ord(c) < 32 or ord(c) == 127) else c for c in text)
    if text[:1] in ("=", "+", "-", "@"):
        text = "'" + text
    return text


def export_csv(ctx: Any, query: Mapping[str, str]) -> dict[str, Any]:
    """Build the masked CSV of the filtered list (sorted as the list is). At most
    CONSOLE_EXPORT_MAX_ROWS rows; ``truncated`` says when rows were left out. Returns the text,
    the counts and a file name; the caller audits and stores it."""
    p = parse_params(query)
    rows, _ = rows_for(ctx, p)
    shown, _, _ = ordered(rows, p)
    cap = int(ctx.settings.console_export_max_rows)
    take = shown[:cap]
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(EXPORT_COLUMNS)
    for r in take:
        w.writerow(
            [
                _cell(x)
                for x in (
                    r["ts"].astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                    if isinstance(r["ts"], dt.datetime)
                    else r["ts"],
                    r["event_id"],
                    r["request_id"],
                    r["correlation_id"],
                    r["trace_id"],
                    r["agent_id"],
                    r["consumer_id"],
                    r["tool"],
                    r["direction"],
                    r["status"],
                    r["action"],
                    ";".join(r["rule_ids"]),
                    ";".join(r["codes"]),
                    ";".join(r["not_eval"]),
                    r["latency_us"],
                    r["latency_rules_us"],
                    r["latency_detectors_us"],
                    r["case_id"],
                )
            ]
        )
    now = ctx.clock.now()
    truncated = len(shown) > cap
    name = (
        f"{EXPORT_PREFIX}{now:%Y%m%dT%H%M%S}Z-{uuid.uuid4().hex[:6]}"
        f"{'-truncated' if truncated else ''}.csv"
    )
    return {
        "name": name,
        "text": buf.getvalue(),
        "rows": len(take),
        "total": len(shown),
        "truncated": truncated,
        "cap": cap,
        "columns": len(EXPORT_COLUMNS),
    }


def save_export(ctx: Any, built: Mapping[str, Any]) -> Path:
    root = Path(ctx.settings.console_export_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / str(built["name"])
    path.write_text(str(built["text"]), encoding="utf-8", newline="")
    return path


EXPORT_RE = re.compile(r"^decisions-\d{8}T\d{6}Z-[0-9a-f]{6}(-truncated)?\.csv$")


def export_path(ctx: Any, name: str) -> Path:
    if not EXPORT_RE.match(name):
        raise ListingError("unknown export name")
    path = Path(ctx.settings.console_export_dir) / name
    if not path.is_file():
        raise ListingError(f"export {name} does not exist (the App wipes /tmp on restart)")
    return path
