"""Regulation graph (flag ``KBGRAPH_ENABLED``): instrument -> obligation -> AI system.

The page ``/console/regkb/graph`` and the API ``GET /v1/regkb/graph`` show the network between the
RegKB obligations (grouped by their instrument, a circular or a decision) and the AI systems they
bind. The link is one row of ``obligation_status`` (written by the duties feature); the colour of a
link is the same mark as the tick strip of the Duties tab (``systems_duties._tick_of``):

* ``gap``      open, no coverage by a Supervisor control   (tall red)
* ``partial``  open, partly covered                          (amber)
* ``bank``     open, covered: the bank process does the rest (blue)
* ``closed``   met, the duty is closed                       (green)

A waived row, a row that does not apply and a row that still needs an answer are not links.

``build_graph`` is a pure function: rows, systems and a small catalogue in, one JSON-like dict out
(nodes with fixed positions, edges with their SVG path, counts, the flat list for the table view).
The layout is deterministic: three columns, systems in rank order (most gaps first), obligations
in barycenter order inside their instrument. The graph is bounded on purpose: one instrument and
the top-N systems by gap count by default, at most ``MAX_OBLIGATIONS`` obligations and
``MAX_EDGES`` links; ``counts`` says how much is hidden. ``load`` reads the store with one query
per table.

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from supervisor.core.errors import SupervisorError

STATES: tuple[str, ...] = ("gap", "partial", "bank", "closed")
SEVERITY = {s: i for i, s in enumerate(STATES)}
RISKS: tuple[str, ...] = ("prohibited", "high", "medium", "low", "unspecified")
VIEWS: tuple[str, ...] = ("graph", "list")
N_CHOICES: tuple[int, ...] = (10, 20, 40, 60)
DEFAULT_N = 20  # systems drawn for one instrument
DEFAULT_N_ALL = 10  # systems drawn for all instruments (the obligation column is long)
MAX_OBLIGATIONS = 40
MAX_OBLIGATIONS_ALL = 30
MAX_EDGES = 400
MAX_Q = 80
ALL = "all"
AUTO = ""  # the instrument is chosen by the builder (most gaps), or all while a search is typed
PREFIX = {"instrument": "ins:", "obligation": "obl:", "system": "sys:"}

# --- layout (SVG user units) ------------------------------------------------------------------
ROW_H = 30
NODE_H = 24
PAD_Y = 8
COL_X = {"instrument": 0, "obligation": 205, "system": 475}
COL_W = {"instrument": 150, "obligation": 215, "system": 265}
WIDTH = 740
LABEL_MAX = {"instrument": 15, "obligation": 26, "system": 27}


class KbGraphError(SupervisorError):
    """Graph off or a bad parameter (HTTP 400)."""


OFF_MESSAGE = (
    "kbgraph_off: the regulation graph is off (KBGRAPH_ENABLED=1 turns it on; it needs "
    "GOVERNANCE_ENABLED)"
)


def enabled(settings: Any) -> bool:
    return bool(
        getattr(settings, "kbgraph_enabled", False)
        and getattr(settings, "governance_enabled", False)
    )


def require_on(settings: Any) -> None:
    if not enabled(settings):
        raise KbGraphError(OFF_MESSAGE)


def tick_of(row: Mapping[str, Any]) -> str:
    """The mark of one duty row, the same rule as the Duties tab ('' = not a link)."""
    from supervisor.console.systems_duties import _tick_of

    return _tick_of(row)


@dataclass(frozen=True)
class Params:
    instrument: str = AUTO  # '' = auto, 'all', or an instrument id
    risk: str = ALL
    coverage: str = ALL  # all | gap | partial | bank | closed
    q: str = ""
    n: int = 0  # 0 = automatic: DEFAULT_N, or DEFAULT_N_ALL for all instruments
    view: str = "graph"
    sel: str = ""

    def as_query(self) -> dict[str, str]:
        """The non-default parameters, for links and for the API echo."""
        out = {
            "instrument": self.instrument,
            "risk": self.risk,
            "coverage": self.coverage,
            "q": self.q,
            "n": str(self.n) if self.n else "",
            "view": "" if self.view == "graph" else self.view,
        }
        return {k: v for k, v in out.items() if v and (v != ALL or k == "instrument")}


def parse_params(query: Mapping[str, str]) -> Params:
    """Check the query string against allow-lists; a bad value is a KbGraphError (HTTP 400)."""
    inst = (query.get("instrument") or "").strip()
    if (
        inst
        and inst != ALL
        and (len(inst) > 64 or not all(c.isalnum() or c in "-_." for c in inst))
    ):
        raise KbGraphError("instrument is not a valid instrument id")
    risk = (query.get("risk") or ALL).strip()
    if risk != ALL and risk not in RISKS:
        raise KbGraphError(f"risk must be one of {', '.join((ALL, *RISKS))}")
    cov = (query.get("coverage") or ALL).strip()
    if cov != ALL and cov not in STATES:
        raise KbGraphError(f"coverage must be one of {', '.join((ALL, *STATES))}")
    q = (query.get("q") or "").strip()
    if len(q) > MAX_Q or any(ord(c) < 32 for c in q):
        raise KbGraphError(f"q is at most {MAX_Q} characters, without control characters")
    raw_n = (query.get("n") or "").strip()
    try:
        n = int(raw_n) if raw_n else 0
    except ValueError:
        raise KbGraphError("n must be a whole number") from None
    if n and n not in N_CHOICES:
        raise KbGraphError(f"n must be one of {', '.join(str(x) for x in N_CHOICES)}")
    view = (query.get("view") or "graph").strip()
    if view not in VIEWS:
        raise KbGraphError(f"view must be one of {', '.join(VIEWS)}")
    sel = (query.get("sel") or "").strip()
    if sel and (len(sel) > 200 or sel[:4] not in PREFIX.values()):
        raise KbGraphError("sel must be ins:<id>, obl:<id> or sys:<id>")
    return Params(inst, risk, cov, q, n, view, sel)


# ------------------------------------------------------------------------------ catalogue


def catalogue_of(
    kb: Any, instrument_ids: Iterable[str], obligation_ids: Iterable[str]
) -> dict[str, Any]:
    """Plain dict of what the page needs from RegKB, only for the ids that are linked."""
    instruments: dict[str, dict[str, str]] = {}
    for iid in instrument_ids:
        try:
            i = kb.instrument(iid)
            instruments[iid] = {
                "number": str(i.number or iid),
                "title_en": str(i.title_en or ""),
                "title_vi": str(i.title_vi or ""),
            }
        except Exception:  # noqa: BLE001, S112 - an instrument RegKB no longer knows is still listed
            continue
    obligations: dict[str, dict[str, Any]] = {}
    for oid in obligation_ids:
        try:
            o = kb.get(oid)
        except Exception:  # noqa: BLE001, S112 - same for an obligation id
            continue
        obligations[oid] = {
            "article": str(o.article_ref or ""),
            "summary_en": str(o.summary_en or ""),
            "summary_vi": str(o.summary_vi or ""),
            "controls": [
                {"id": str(c.id), "kind": str(c.kind), "coverage": str(c.coverage)}
                for c in o.control_mapping[:12]
            ],
        }
    return {"instruments": instruments, "obligations": obligations}


# ------------------------------------------------------------------------------ the builder

Link = tuple[str, str, str, str]  # (system_id, obligation_id, instrument_id, state)


def _cut(text: str, n: int, tail: int = 0) -> str:
    """Shorten to n characters with an ellipsis; ``tail`` characters of the end are kept (system
    names differ at the end: ``Card Fraud Auto-Block - Pilot``)."""
    if len(text) <= n:
        return text
    if tail:
        return text[: n - tail - 1].rstrip() + "…" + text[-tail:].lstrip()
    return text[: n - 1] + "…"


def _short_obl(oid: str, instrument_id: str) -> str:
    return oid[len(instrument_id) + 1 :] if oid.startswith(instrument_id + "-") else oid


def _has(needle: str, *parts: str) -> bool:
    return needle in " ".join(parts).lower()


def _choose_instrument(p: Params, pool: Sequence[Link]) -> tuple[str, bool]:
    """(instrument id or 'all', chosen by the builder). A typed search looks in all."""
    if p.instrument:
        return p.instrument, False
    if p.q:
        return ALL, False
    weight: dict[str, tuple[int, int, int]] = {}
    for _, _, iid, st in pool:
        w = weight.get(iid, (0, 0, 0))
        weight[iid] = (w[0] + (st == "gap"), w[1] + (st == "partial"), w[2] + 1)
    if not weight:
        return ALL, True
    return max(sorted(weight), key=lambda i: weight[i]), True


def build_graph(
    rows: Iterable[Mapping[str, Any]],
    systems: Iterable[Mapping[str, Any]],
    catalogue: Mapping[str, Any],
    params: Params | None = None,
    lang: str = "en",
) -> dict[str, Any]:
    """The graph for one filter. ``rows`` are ``obligation_status`` rows, ``systems`` the
    ``ai_system`` rows the caller may see (an archived system is left out here)."""
    p = params or Params()
    cat_i: Mapping[str, Mapping[str, str]] = catalogue.get("instruments", {})
    cat_o: Mapping[str, Mapping[str, Any]] = catalogue.get("obligations", {})
    sysmap = {str(s["system_id"]): s for s in systems if str(s.get("status")) != "archived"}

    def sname(sid: str) -> str:
        return str(sysmap[sid].get("name") or sid)

    # 1. every link of the portfolio, with its mark
    links: list[Link] = []
    for r in rows:
        sid = str(r["system_id"])
        state = tick_of(r) if sid in sysmap else ""
        if state:
            links.append((sid, str(r["obligation_id"]), str(r["instrument_id"]), state))
    ins_label = {iid: str(cat_i.get(iid, {}).get("number") or iid) for _, _, iid, _ in links}
    all_instruments = sorted(ins_label)
    gaps_of = Counter(lk[2] for lk in links if lk[3] == "gap")

    # 2. the filters: risk level, coverage state, instrument
    pool = [
        lk
        for lk in links
        if (p.risk == ALL or str(sysmap[lk[0]].get("risk_level")) == p.risk)
        and (p.coverage == ALL or lk[3] == p.coverage)
    ]
    focus, auto = _choose_instrument(p, pool)
    if focus != ALL:
        pool = [lk for lk in pool if lk[2] == focus]

    # 3. the search: systems by id or name, obligations by id or article, instruments by number
    needle = p.q.lower()
    if needle:
        hit_sys = {sid for sid in {lk[0] for lk in pool} if _has(needle, sid, sname(sid))}
        hit_obl = {
            lk[1]
            for lk in pool
            if _has(
                needle,
                lk[1],
                str(cat_o.get(lk[1], {}).get("article", "")),
                lk[2],
                ins_label.get(lk[2], ""),
            )
        }
        pool = [lk for lk in pool if lk[0] in hit_sys or lk[1] in hit_obl]

    # 4. rank the systems (most gaps first) and cut to the top N
    by_sys: dict[str, list[Link]] = {}
    tot_obl: dict[str, Counter[str]] = {}
    for lk in pool:
        by_sys.setdefault(lk[0], []).append(lk)
        tot_obl.setdefault(lk[1], Counter())[lk[3]] += 1
    tot_sys = {sid: Counter(lk[3] for lk in ls) for sid, ls in by_sys.items()}
    ranked = sorted(
        by_sys,
        key=lambda s: (
            -tot_sys[s]["gap"],
            -tot_sys[s]["partial"],
            -tot_sys[s]["bank"],
            sname(s).lower(),
            s,
        ),
    )
    n_eff = p.n or (DEFAULT_N_ALL if focus == ALL else DEFAULT_N)
    keep = ranked[:n_eff]
    shown = [lk for lk in pool if lk[0] in set(keep)]

    # 5. at most MAX_OBLIGATIONS obligation nodes: most gaps first, then most links
    deg: dict[str, Counter[str]] = {}
    for lk in shown:
        deg.setdefault(lk[1], Counter())[lk[3]] += 1
    hidden_obl = 0
    cap = MAX_OBLIGATIONS_ALL if focus == ALL else MAX_OBLIGATIONS
    if len(deg) > cap:
        best = sorted(deg, key=lambda o: (-deg[o]["gap"], -sum(deg[o].values()), o))
        drop = set(best[cap:])
        hidden_obl = len(drop)
        shown = [lk for lk in shown if lk[1] not in drop]
    # 6. at most MAX_EDGES links: drop the lowest ranked system until it fits
    while len(shown) > MAX_EDGES and len(keep) > 1:
        last = keep.pop()
        shown = [lk for lk in shown if lk[0] != last]
    linked = {lk[0] for lk in shown}
    keep = [sid for sid in keep if sid in linked]

    # 7. the order of the columns: obligations by barycenter, grouped by instrument
    obl_ins = {lk[1]: lk[2] for lk in shown}
    frac = {sid: (i + 0.5) / len(keep) for i, sid in enumerate(keep)}
    adj: dict[str, list[float]] = {}
    for lk in shown:
        adj.setdefault(lk[1], []).append(frac[lk[0]])
    bary = {oid: sum(v) / len(v) for oid, v in adj.items()}
    obl_of: dict[str, list[str]] = {}
    for oid, iid in obl_ins.items():
        obl_of.setdefault(iid, []).append(oid)
    ins_order = sorted(obl_of, key=lambda i: (sum(bary[o] for o in obl_of[i]) / len(obl_of[i]), i))
    obl_order = [o for i in ins_order for o in sorted(obl_of[i], key=lambda o: (bary[o], o))]

    # 8. positions: each column is spread over the full height
    height = max(len(ins_order), len(obl_order), len(keep), 1) * ROW_H + 2 * PAD_Y

    def ys(count: int) -> list[float]:
        step = (height - 2 * PAD_Y) / max(count, 1)
        return [PAD_Y + step * (i + 0.5) for i in range(count)]

    nodes: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}

    def add(kind: str, key: str, y: float, label: str, **extra: Any) -> None:
        node = {
            "id": PREFIX[kind] + key,
            "idx": len(nodes),
            "kind": kind,
            "key": key,
            "label": _cut(label, LABEL_MAX[kind], 12 if kind == "system" else 0),
            "x": COL_X[kind],
            "y": round(y - NODE_H / 2, 1),
            "w": COL_W[kind],
            "h": NODE_H,
            **extra,
        }
        nodes.append(node)
        index[node["id"]] = node

    for y, iid in zip(ys(len(ins_order)), ins_order, strict=True):
        meta = cat_i.get(iid, {})
        title = (
            meta.get("title_vi") if lang == "vi" and meta.get("title_vi") else meta.get("title_en")
        )
        add(
            "instrument",
            iid,
            y,
            ins_label[iid],
            title=str(title or ""),
            number=ins_label[iid],
            badge=len(obl_of[iid]),
        )
    for y, oid in zip(ys(len(obl_order)), obl_order, strict=True):
        meta = cat_o.get(oid, {})
        iid = obl_ins[oid]
        text = (
            meta.get("summary_vi")
            if lang == "vi" and meta.get("summary_vi")
            else meta.get("summary_en")
        )
        article = str(meta.get("article", ""))
        add(
            "obligation",
            oid,
            y,
            f"{_short_obl(oid, iid)}  {article}".strip(),
            title=str(text or ""),
            article=article,
            instrument_id=iid,
            controls=list(meta.get("controls", [])),
            badge=sum(tot_obl[oid].values()),
        )
    for y, sid in zip(ys(len(keep)), keep, strict=True):
        s = sysmap[sid]
        add(
            "system",
            sid,
            y,
            sname(sid),
            title=sname(sid),
            risk=str(s.get("risk_level") or "unspecified"),
            owner_team=str(s.get("owner_team") or ""),
            stage=str(s.get("lifecycle_stage") or ""),
            badge=0,
        )

    # 9. edges (SVG paths), the flat list, the neighbours and the counts of each node
    def path(a: Mapping[str, Any], b: Mapping[str, Any]) -> str:
        x1, y1 = a["x"] + a["w"], a["y"] + a["h"] / 2
        x2, y2 = b["x"], b["y"] + b["h"] / 2
        xm = (x1 + x2) / 2
        return f"M{x1:g} {y1:g}C{xm:g} {y1:g} {xm:g} {y2:g} {x2:g} {y2:g}"

    edges: list[dict[str, Any]] = []
    for oid in obl_order:
        a, b = index[PREFIX["instrument"] + obl_ins[oid]], index[PREFIX["obligation"] + oid]
        edges.append(
            {"a": a["id"], "b": b["id"], "kind": "structure", "state": "", "d": path(a, b)}
        )
    for sid, oid, _iid, st in sorted(shown, key=lambda lk: (-SEVERITY[lk[3]], lk[1], lk[0])):
        a, b = index[PREFIX["obligation"] + oid], index[PREFIX["system"] + sid]
        edges.append({"a": a["id"], "b": b["id"], "kind": "duty", "state": st, "d": path(a, b)})

    flat = [
        {
            "instrument_id": iid,
            "instrument": ins_label[iid],
            "obligation_id": oid,
            "article": str(cat_o.get(oid, {}).get("article", "")),
            "system_id": sid,
            "system": sname(sid),
            "risk": str(sysmap[sid].get("risk_level") or "unspecified"),
            "state": st,
        }
        for sid, oid, iid, st in sorted(
            shown, key=lambda lk: (ins_label[lk[2]], lk[1], SEVERITY[lk[3]], sname(lk[0]), lk[0])
        )
    ]

    nbr: dict[str, list[dict[str, str]]] = {n["id"]: [] for n in nodes}
    seen: dict[str, Counter[str]] = {n["id"]: Counter() for n in nodes}
    for sid, oid, iid, st in sorted(
        shown, key=lambda lk: (SEVERITY[lk[3]], lk[1], sname(lk[0]).lower(), lk[0])
    ):
        s_id, o_id, i_id = (
            PREFIX["system"] + sid,
            PREFIX["obligation"] + oid,
            PREFIX["instrument"] + iid,
        )
        nbr[s_id].append({"id": o_id, "state": st})
        nbr[o_id].append({"id": s_id, "state": st})
        for nid in (s_id, o_id, i_id):
            seen[nid][st] += 1
    for oid in obl_order:
        nbr[PREFIX["instrument"] + obl_ins[oid]].append(
            {"id": PREFIX["obligation"] + oid, "state": ""}
        )
    for n in nodes:
        n["links"] = nbr[n["id"]]
        n["states"] = {s: seen[n["id"]][s] for s in STATES}
        if n["kind"] == "obligation":
            n["totals"] = {s: tot_obl[n["key"]][s] for s in STATES}
        elif n["kind"] == "system":
            n["totals"] = {s: tot_sys[n["key"]][s] for s in STATES}

    in_shown = Counter(lk[3] for lk in shown)
    in_all = Counter(lk[3] for lk in links)
    counts = {
        "systems_in_scope": len(sysmap),
        "systems_linked": len({lk[0] for lk in links}),
        "obligations": len({lk[1] for lk in links}),
        "instruments": len(all_instruments),
        "links": len(links),
        "by_state": {s: in_all[s] for s in STATES},
        "matching_systems": len(by_sys),
        "matching_links": len(pool),
        "shown": {
            "systems": len(keep),
            "obligations": len(obl_order),
            "instruments": len(ins_order),
            "links": len(shown),
            "by_state": {s: in_shown[s] for s in STATES},
        },
        "hidden_systems": len(by_sys) - len(keep),
        "hidden_obligations": hidden_obl,
        "hidden_links": len(pool) - len(shown),
    }
    return {
        "params": p.as_query(),
        "focus": {
            "instrument": focus,
            "label": ins_label.get(focus, focus),
            "auto": auto,
            "n": n_eff,
            "all": focus == ALL,
        },
        "counts": counts,
        "layout": {"width": WIDTH, "height": height, "columns": COL_X, "widths": COL_W},
        "nodes": nodes,
        "edges": edges,
        "rows": flat,
        "options": [
            {
                "id": iid,
                "label": ins_label[iid],
                "title": str(cat_i.get(iid, {}).get("title_en", "")),
                "gaps": gaps_of[iid],
            }
            for iid in all_instruments
        ],
        "empty": not shown,
        "selected": p.sel if p.sel in index else "",
    }


# ------------------------------------------------------------------------------ the loader


def load(ctx: Any, me: Any, query: Mapping[str, str], lang: str = "en") -> dict[str, Any]:
    """Read the store (``obligation_status`` and ``ai_system``: one query each, plus the scope of a
    person who sees only some systems), take RegKB from its cache and build the graph."""
    from supervisor.console import compliance_view
    from supervisor.governance.systems import ALL as ALL_SYSTEMS

    require_on(ctx.settings)
    p = parse_params(query)
    rows = ctx.state.query("obligation_status", {"applies": "yes"})
    systems = ctx.state.query("ai_system")
    scope = ctx.systems.scope_for(me)
    if scope is not ALL_SYSTEMS:
        systems = [s for s in systems if str(s["system_id"]) in scope]
    kb = compliance_view.kb_for(ctx.settings)
    cat = catalogue_of(
        kb, {str(r["instrument_id"]) for r in rows}, {str(r["obligation_id"]) for r in rows}
    )
    return build_graph(rows, systems, cat, p, lang)
