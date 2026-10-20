"""Traces list and span viewer (WP-UX3).

Read model over ``agent_event`` (span ids), the ``verdict`` rows of the trace (tier 0 rule hits,
Tier 0b findings, judge verdicts), ``case_link`` and ``chain_entry``. The tree is built from
``span_id`` / ``parent_span_id``; events that share a span id form one node. Nothing is written.

Privacy: only the masked columns are read, never ``agent_event_raw``. The capture level of each
event decides what is shown: ``digest`` shows no text at all; ``masked`` and ``raw`` show the
masked excerpt (a ``raw`` event still shows its masked column only). The excerpt goes through the
masker once more before it is shown, and with no masker configured no text is shown (fail safe,
like the recorder)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from supervisor.analytics.decisions import looks_personal, safe_id, shown_id
from supervisor.console import ux3
from supervisor.console.listing import (
    ListingError,
    paginate,
    parse_int,
    parse_sort,
    query_string,
    sort_rows,
)
from supervisor.console.readmodels import _verdict_row, rules_index

MAX_SPANS = 500  # spans drawn per trace; the rest is counted ("+N more")
TEXT_CAP = 1000  # characters of a masked excerpt shown
PAGE_SIZE = 25
COLUMNS = ("started", "agent_id", "spans", "status")
STATUSES = ("ok", "alert", "blocked", "paused")
_RANK = {"pause": 0, "block": 1, "alert": 2, "log": 3, "allow": 4}
_STATUS_OF = {"pause": "paused", "block": "blocked", "alert": "alert"}
_STATUS_RANK = {"paused": 0, "blocked": 1, "alert": 2, "ok": 3}
_MARK = {"pause": "P", "block": "B", "alert": "A"}


def parse_params(query: Mapping[str, str]) -> dict[str, str]:
    p = {
        "agent": ux3.ident(query, "agent"),
        "status": ux3.choice(query, "status", STATUSES),
        "range": ux3.choice(query, "range", ux3.RANGES),
        "q": ux3.token(query, "q"),
        "corr": _corr_filter(query),  # WP39: correlation id (shown with CONSOLE_DECISIONS_V2)
        "sort": query.get("sort") or "",
        "dir": query.get("dir") or "",
        "page": query.get("page") or "",
    }
    parse_int(p["page"], "page", 1)
    return p


def _corr_filter(query: Mapping[str, str]) -> str:
    """WP39 review: a correlation id filter that refuses personal data (R2)."""
    value = ux3.ident(query, "corr")
    if value and looks_personal(value):
        raise ListingError("corr: looks like personal data, not an id")
    return value


def v2_on(ctx: Any) -> bool:
    """WP39: correlation ids, finding chips and the correlation filter (CONSOLE_DECISIONS_V2)."""
    return bool(getattr(ctx.settings, "console_decisions_v2", False))


def _worst(actions: Sequence[str]) -> str:
    stops = [a for a in actions if a in _STATUS_OF]
    return _STATUS_OF[min(stops, key=lambda a: _RANK[a])] if stops else "ok"


def summaries(ctx: Any, p: Mapping[str, str]) -> tuple[list[dict[str, Any]], bool]:
    where: dict[str, Any] = {}
    if p["agent"]:
        where["agent_id"] = p["agent"]
    cap = ux3.trace_scan(ctx)  # CONSOLE_TRACE_SCAN: newest events/verdicts read for the list
    events = ctx.tables.query("agent_event", where, order_by=("-ts",), limit=cap)
    start = ux3.range_start(ctx.clock.now(), p["range"])
    by_trace: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        if start is None or e["ts"] >= start:
            by_trace[str(e["trace_id"])].append(e)
    verdicts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    advisory: dict[str, int] = defaultdict(int)
    vwhere: dict[str, Any] = {"agent_id": p["agent"]} if p["agent"] else {}
    of_event = {str(e["event_id"]): tid for tid, evs in by_trace.items() for e in evs}
    for v in ctx.tables.query("verdict", vwhere, order_by=("-ts",), limit=cap):
        # a gate verdict may carry no trace id (the call gave none): its event does
        tid = str(v["trace_id"]) if v.get("trace_id") else of_event.get(str(v.get("event_id")), "")
        if tid not in by_trace:
            continue
        if v.get("advisory"):
            advisory[tid] += 1
        else:
            verdicts[tid].append(v)
    out = []
    for tid, evs in by_trace.items():
        if p["q"] and p["q"] not in tid:
            continue
        if p["corr"] and not any(e.get("correlation_id") == p["corr"] for e in evs):
            continue
        stamps = [e["ts"] for e in evs]
        gate = [e.get("classification") or "" for e in evs if e["event_type"] == "gate_decision"]
        acts = [v["action"] for v in verdicts.get(tid, [])] + gate
        status = _worst(acts)
        if p["status"] and status != p["status"]:
            continue
        labels = sorted({v["action"] for v in verdicts.get(tid, []) if v["action"] in _STATUS_OF})
        out.append(
            {
                "trace_id": tid,
                "agent_id": evs[0]["agent_id"],
                "started": min(stamps),
                "duration_ms": int((max(stamps) - min(stamps)).total_seconds() * 1000),
                "spans": len({e["span_id"] for e in evs}),
                "events": len(evs),
                "status": status,
                "labels": labels,
                "judge_n": advisory.get(tid, 0),
            }
        )
    return out, len(events) >= cap


def list_view(ctx: Any, query: Mapping[str, str]) -> dict[str, Any]:
    p = parse_params(query)
    rows, capped = summaries(ctx, p)
    col, direction = parse_sort(p["sort"], p["dir"], COLUMNS, "started", "desc")
    keys = {"status": lambda r: _STATUS_RANK[r["status"]]}
    shown = sort_rows(rows, col, direction, keys)
    page = paginate(shown, parse_int(p["page"], "page", 1), PAGE_SIZE)
    agents = sorted(a["agent_id"] for a in ctx.state.query("agent"))
    base = {k: p[k] for k in ("agent", "status", "range", "q", "corr")}
    return {
        "page": page,
        "params": p,
        "sort_col": col,
        "sort_dir": direction,
        "agent_opts": [(a, a) for a in agents],
        "status_opts": [(s, f"trace_{s}") for s in STATUSES],
        "range_opts": [(k, f"range_{k}") for k in ux3.RANGES],
        "capped": capped,
        "v2": v2_on(ctx),
        "base_qs": query_string(base),
        "list_qs": query_string({**base, "sort": col, "dir": direction}),
    }


# ---------------------------------------------------------------------------- one trace


class _Text:
    """Masked excerpt policy (see the module doc)."""

    def __init__(self, ctx: Any) -> None:
        from supervisor.adapters.factory import make_masker

        self.masker = make_masker(ctx.settings)

    def excerpt(self, value: Any, level: str) -> str | None:
        if level == "digest" or not value or self.masker is None:
            return None
        return str(self.masker.mask(str(value)))[:TEXT_CAP]


def _node_name(evs: list[dict[str, Any]]) -> str:
    primary = next((e for e in evs if e["event_type"] != "gate_decision"), evs[0])
    tool = primary.get("tool_name")
    return f"{primary['event_type']} {tool}" if tool else str(primary["event_type"])


def build_tree(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Flat, depth-annotated span list in tree order (parents before children, siblings by
    time). A span whose parent is not in the trace is a root. A cycle cannot loop: every span
    is visited once. Returns (nodes, spans beyond MAX_SPANS)."""
    spans: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        spans.setdefault(str(e["span_id"]), []).append(e)
    parent: dict[str, str | None] = {}
    for sid, evs in spans.items():
        pid = next((str(e["parent_span_id"]) for e in evs if e.get("parent_span_id")), None)
        parent[sid] = pid if pid in spans and pid != sid else None
    kids: dict[str | None, list[str]] = defaultdict(list)
    for sid in sorted(spans, key=lambda s: min(e["ts"] for e in spans[s])):
        kids[parent[sid]].append(sid)
    order: list[tuple[str, int]] = []
    seen: set[str] = set()

    def walk(root: str) -> None:
        # iterative depth-first walk: a chain of 1000+ nested spans must not hit the recursion
        # limit (that was a 500), and drawing stops at MAX_SPANS
        stack = [(root, 0)]
        while stack and len(order) < MAX_SPANS:
            sid, depth = stack.pop()
            if sid in seen:
                continue
            seen.add(sid)
            order.append((sid, depth))
            stack.extend((c, depth + 1) for c in reversed(kids.get(sid, [])))

    for root in kids.get(None, []):
        walk(root)
    for sid in spans:  # spans in a parent cycle have no root: show them at the top level
        walk(sid)
    extra = max(0, len(spans) - len(order))
    nodes = []
    for sid, depth in order[:MAX_SPANS]:
        evs = sorted(spans[sid], key=lambda e: e["ts"])
        nodes.append(
            {
                "span_id": sid,
                "depth": depth,
                "name": _node_name(evs),
                "ts": evs[0]["ts"],
                "latency_ms": next((e["latency_ms"] for e in evs if e.get("latency_ms")), None),
                "events": evs,
                "marks": [],
            }
        )
    return nodes, extra


def _verdict_view(v: Mapping[str, Any], rules: Mapping[str, Any], text: _Text) -> dict[str, Any]:
    row = _verdict_row(dict(v), rules)
    row["event_id"] = v.get("event_id")
    row["rationale"] = text.excerpt(v.get("rationale_masked"), "masked") or row["reason"][:200]
    return row


def trace_detail(ctx: Any, trace_id: str, span_id: str | None = None) -> dict[str, Any]:
    if not ux3.ID.match(trace_id or ""):
        raise ListingError("invalid trace id")
    events = ctx.tables.query(
        "agent_event", {"trace_id": trace_id}, order_by=("ts",), limit=MAX_SPANS * 4
    )
    if not events:
        raise ListingError(f"trace {trace_id} not found")
    rules = rules_index(ctx)
    text = _Text(ctx)
    vs = ctx.tables.query("verdict", {"trace_id": trace_id}, order_by=("ts",), limit=2000)
    seen = {v["verdict_id"] for v in vs}
    gates = [e["event_id"] for e in events if e["event_type"] == "gate_decision"][:50]
    for eid in gates:  # gate verdicts of a call that gave no trace id are keyed by the event
        vs += [
            v for v in ctx.tables.query("verdict", {"event_id": eid}) if v["verdict_id"] not in seen
        ]
    by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for v in vs:
        by_event[str(v.get("event_id"))].append(_verdict_view(v, rules, text))
    nodes, extra = build_tree(events)
    fired: dict[str, list[str]] = defaultdict(list)
    if v2_on(ctx):  # WP39: finding rows of this trace, by decision
        for f in ctx.tables.query("finding", {"trace_id": trace_id}, limit=2000):
            if not f.get("not_executed_reason"):
                fired[str(f["event_id"])].append(str(f["code"]))
    for n in nodes:
        gates = [e for e in n["events"] if e["event_type"] == "gate_decision"]
        n["decision_id"] = str(gates[0]["event_id"]) if gates else None
        n["correlation_id"] = next(
            (e.get("correlation_id") for e in n["events"] if safe_id(e.get("correlation_id"))),
            None,
        )
        n["finding_codes"] = sorted({c for g in gates for c in fired.get(str(g["event_id"]), [])})
        n["verdicts"] = [vv for e in n["events"] for vv in by_event.get(str(e["event_id"]), [])]
        stops = [v["action"] for v in n["verdicts"] if v["action"] in _MARK and not v["advisory"]]
        gate = [e.get("classification") for e in n["events"] if e["event_type"] == "gate_decision"]
        stops += [a for a in gate if a in _MARK]
        n["stop"] = min(stops, key=lambda a: _RANK[a]) if stops else None
        n["mark"] = _MARK.get(n["stop"] or "")
        n["judge"] = any(v["source"] == "judge" for v in n["verdicts"])
    ids = [n["span_id"] for n in nodes]
    if span_id is not None and span_id not in ids:
        raise ListingError(f"span {span_id} is not in trace {trace_id}")
    worst = min((n for n in nodes if n["stop"]), key=lambda n: _RANK[n["stop"]], default=None)
    chosen = span_id or (worst["span_id"] if worst else (ids[0] if ids else None))
    cases = {
        str(r["source_ref"]): str(r["case_id"])
        for r in ctx.tables.query("case_link", {"source_kind": "gate"})
    }
    stamps = [e["ts"] for e in events]
    stops = [n["stop"] for n in nodes if n["stop"]]
    head = {
        "trace_id": trace_id,
        "agent_id": events[0]["agent_id"],
        "spans": len(ids) + extra,
        "started": min(stamps),
        "duration_ms": int((max(stamps) - min(stamps)).total_seconds() * 1000),
        "status": _worst(stops),
        "correlation_ids": sorted(  # WP39 review: ids that hold personal data are not shown
            {str(e["correlation_id"]) for e in events if safe_id(e.get("correlation_id"))}
        )[:5],
        "case_ids": sorted(
            {cases[str(e["event_id"])] for e in events if str(e["event_id"]) in cases}
        ),
    }
    return {
        "head": head,
        "nodes": nodes,
        "extra": extra,
        "selected": span_detail(ctx, nodes, chosen, text, cases),
        "selected_id": chosen,
        "truncated": len(events) >= MAX_SPANS * 4,
        "v2": v2_on(ctx),
    }


def span_detail(
    ctx: Any,
    nodes: list[dict[str, Any]],
    span_id: str | None,
    text: _Text,
    cases: Mapping[str, str],
) -> dict[str, Any] | None:
    node = next((n for n in nodes if n["span_id"] == span_id), None)
    if node is None:
        return None
    items = []
    for e in node["events"]:
        level = str(e.get("capture_level") or "digest")
        chain = None
        if e["event_type"] == "gate_decision":
            rows = ctx.tables.query(
                "chain_entry", {"record_ref": e["event_id"], "record_type": "gate_decision"}
            )
            chain = {"lane": rows[0]["lane"], "seq": int(rows[0]["seq"])} if rows else None
        if e.get("correlation_id"):  # WP39 review: a caller-given id is shown only when safe
            e = {**e, "correlation_id": shown_id(e.get("correlation_id"))}
        items.append(
            {
                "e": e,
                "level": level,
                "args": text.excerpt(e.get("args_masked"), level),
                "result": text.excerpt(e.get("result_masked"), level),
                "digest_only": level == "digest" or text.masker is None,
                "case_id": cases.get(str(e["event_id"])),
                "chain": chain,
            }
        )
    return {"node": node, "evs": items}


def span_view(ctx: Any, trace_id: str, span_id: str) -> dict[str, Any]:
    """Data for the right-hand panel only (htmx partial)."""
    if not ux3.ID.match(span_id or ""):
        raise ListingError("invalid span id")
    data = trace_detail(ctx, trace_id, span_id)
    return {"selected": data["selected"], "head": data["head"], "v2": data["v2"]}
