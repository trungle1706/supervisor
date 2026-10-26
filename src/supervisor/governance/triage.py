"""Candidate triage (WP-N1): which unmanaged workspace objects should be registered first.

Pure functions over the inventory graph (``supervisor.inventory.graph.Graph``). One ``TriageRow``
(a plain dict) per unmanaged candidate node. Candidate kinds:

* ``app``: a ``system`` node with role ``databricks_app``;
* ``endpoint``: a ``model_endpoint`` with ``attrs.agent_endpoint`` or ``attrs.task == "agent"``;
* ``genie_space``;
* ``job``.

Nothing is read from or written to a store here, and nothing leaves the graph that is not already
a name or an evidence reference. A workspace URL or a numeric workspace id never reaches a row:
every output string goes through ``scrub``.

The points live in one table (``SIGNALS``), so a background analyst agent can replace the rules
later. It can also supply whole rows: ``node.attrs["triage"]`` (or the ``overrides`` argument)
overrides the computed fields. The row shape is in ``docs/triage.md``.

No floats: the score is an integer (``impact * 0.6 + complexity * 0.2 + rank * 10``, computed as
``(6 * impact + 2 * complexity) // 10 + 10 * rank``)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from supervisor.inventory.graph import Graph
from supervisor.inventory.model import Node

# ----------------------------------------------------------------------------- the rule table

# slug -> (points, short rule text). Points add to ``impact`` (cap 100). A slug with 0 points is
# shown but does not move the score.
SIGNALS: dict[str, tuple[int, str]] = {
    "external_model": (20, "serves or calls a model from an external provider"),
    "customer_table": (25, "reads or writes a customer, card, account, loan or payment table"),
    "money_tool": (30, "calls a tool of class money, credit or pii_export"),
    "writes": (10, "a job that writes data"),
    "agent_endpoint": (10, "a serving endpoint that runs an agent"),
    "genie_space": (10, "a Genie space"),
    "app_agent": (10, "an app with an agent endpoint behind it"),
    "unknown": (5, "nothing is known about it"),
    "scheduled": (0, "runs on a schedule"),
    "no_owner": (0, "no owner group is known"),
}
IMPACT_CAP = 100
TOOL_CLASSES = ("money", "credit", "pii_export")
# A table name that points at customer, card, account, loan or payment data. Tokens split on any
# character that is not a letter or digit, so ``the`` does not match ``other``.
CUSTOMER_TABLE = re.compile(
    r"(?<![a-z0-9])(customer|khach|cif|card|the|account|tai_khoan|loan|khoan_vay|payment"
    r"|thanh_toan|txn|transaction)s?(?![a-z0-9])"
)

AUTONOMY_ORDER: tuple[str, ...] = (
    "unspecified",
    "l0_rule_based",
    "l1_assistive",
    "l2_workflow_step",
    "l3_tool_using_supervised",
    "l4_autonomous_bounded",
    "l5_self_directed",
)
AUTONOMY_RANK: dict[str, int] = {
    "unspecified": 1,
    "l0_rule_based": 0,
    "l1_assistive": 1,
    "l2_workflow_step": 2,
    "l3_tool_using_supervised": 3,
    "l4_autonomous_bounded": 4,
    "l5_self_directed": 5,
}
KINDS: tuple[str, ...] = ("app", "endpoint", "genie_space", "job")
ACTIONS: tuple[str, ...] = (
    "register_now",
    "register_and_classify",
    "register_review_vendor",
    "register_when_convenient",
)
BANDS: tuple[str, ...] = ("high", "medium", "low")  # score >= 70, 40..69, below 40
HIGH_SCORE = 70
MEDIUM_SCORE = 40

# Edges followed to find what a candidate reaches (the graph is small; depth is bounded).
_WALK_EDGES = ("uses", "serves", "reads", "writes")
_MAX_DEPTH = 3
_COMPLEXITY_KINDS = ("model", "tool", "uc_function", "dataset", "mcp_server")
_TOOL_KINDS = ("tool", "uc_function", "mcp_server")

# What may be replaced from ``attrs["triage"]``, with the check for each field.
OVERRIDE_FIELDS: tuple[str, ...] = (
    "impact",
    "autonomy",
    "complexity",
    "score",
    "signals",
    "description",
    "recommended_action",
)

_URL = re.compile(
    r"(?i)\b(?:https?|wss?|ftp)://\S+|\b[\w-]+\.(?:cloud\.databricks|azuredatabricks)\.\S+"
)
_WS_HOST = re.compile(r"(?i)\bdbc-[0-9a-f-]{4,}\S*|\badb-\d+\S*")
_LONG_NUMBER = re.compile(r"\d{10,}")
_MAX_TEXT = 300


def scrub(text: Any) -> str:
    """A string that is safe to show: no URL, no workspace host or numeric workspace id."""
    out = str(text)
    out = _URL.sub("[url removed]", out)
    out = _WS_HOST.sub("[id removed]", out)
    out = _LONG_NUMBER.sub("[id removed]", out)
    return out[:_MAX_TEXT]


# ----------------------------------------------------------------------------- graph helpers


def candidate_kind(n: Node) -> str | None:
    """``app``, ``endpoint``, ``genie_space``, ``job`` or None when the node is not a candidate."""
    if n.status != "unmanaged":
        return None
    if n.kind == "system" and n.attrs.get("role") == "databricks_app":
        return "app"
    if n.kind == "model_endpoint" and (
        n.attrs.get("agent_endpoint") or str(n.attrs.get("task") or "") == "agent"
    ):
        return "endpoint"
    if n.kind == "genie_space":
        return "genie_space"
    if n.kind == "job":
        return "job"
    return None


def reach(g: Graph, node_id: str) -> list[tuple[Node, str]]:
    """Nodes reached from ``node_id`` along active uses, serves, reads and writes edges, with the
    kind of the edge that led to each (breadth first, depth 3, each node once, name order)."""
    seen = {node_id}
    frontier = [node_id]
    out: list[tuple[Node, str]] = []
    for _ in range(_MAX_DEPTH):
        nxt: list[str] = []
        for nid in frontier:
            for e in g.out_edges(nid, _WALK_EDGES):
                dst = g.nodes.get(e.dst_id)
                if dst is None or e.dst_id in seen or dst.status == "gone":
                    continue
                seen.add(e.dst_id)
                nxt.append(e.dst_id)
                out.append((dst, e.kind))
        frontier = nxt
    return out


def _providers(node: Node, linked: Iterable[Node]) -> list[str]:
    found: set[str] = set()
    for n in (node, *linked):
        for p in n.attrs.get("external_providers") or []:
            if str(p).strip():
                found.add(str(p).strip().lower())
    return sorted(found)


def _is_customer_table(n: Node) -> bool:
    return n.kind == "dataset" and bool(CUSTOMER_TABLE.search(n.name.lower()))


def _tool_class(n: Node) -> str:
    return str(n.attrs.get("risk_class") or "")


# ----------------------------------------------------------------------------- the rules


def facts_of(g: Graph, n: Node, kind: str) -> dict[str, Any]:
    """What the graph says about one candidate. Names only; the description is built from it."""
    linked = reach(g, n.node_id)
    nodes = [x for x, _ in linked]
    endpoints = [x for x in nodes if x.kind == "model_endpoint"]
    risky = [
        x for x in nodes if x.kind in ("tool", "uc_function") and _tool_class(x) in TOOL_CLASSES
    ]
    tables = [x for x in nodes if x.kind == "dataset"]
    return {
        "kind": kind,
        "name": scrub(n.display_name or n.name),
        "group": scrub(n.attrs["owner_group"]) if n.attrs.get("owner_group") else "",
        "providers": [scrub(p) for p in _providers(n, endpoints)],
        "endpoints": sorted(scrub(x.display_name or x.name) for x in endpoints),
        "agent_endpoint": kind == "endpoint"
        or any(x.attrs.get("agent_endpoint") or x.attrs.get("task") == "agent" for x in endpoints),
        "customer_tables": sorted(scrub(x.name) for x in tables if _is_customer_table(x)),
        "tables_n": len(tables),
        "money_tools": sorted(scrub(x.display_name or x.name) for x in risky),
        "tools_n": sum(1 for x in nodes if x.kind in _TOOL_KINDS),
        "writes": kind == "job" and any(k == "writes" for _, k in linked),
        "scheduled": bool(n.attrs.get("schedule")),
        "linked_n": sum(1 for x in nodes if x.kind in _COMPLEXITY_KINDS),
    }


def signals_of(f: Mapping[str, Any]) -> list[str]:
    """The slugs that fired, in the order of ``SIGNALS``."""
    fired = {
        "external_model": bool(f["providers"]),
        "customer_table": bool(f["customer_tables"]),
        "money_tool": bool(f["money_tools"]),
        "writes": bool(f["writes"]),
        "agent_endpoint": f["kind"] == "endpoint",
        "genie_space": f["kind"] == "genie_space",
        "app_agent": f["kind"] == "app" and bool(f["agent_endpoint"]),
        "scheduled": bool(f["scheduled"]),
        "no_owner": not f["group"],
    }
    scoring = [s for s, on in fired.items() if on and SIGNALS[s][0] > 0]
    out = [s for s in SIGNALS if fired.get(s)]
    if not scoring:
        out.insert(0, "unknown")
    return out


def impact_of(signals: Iterable[str]) -> int:
    return min(IMPACT_CAP, sum(SIGNALS[s][0] for s in signals if s in SIGNALS))


def autonomy_of(n: Node, f: Mapping[str, Any]) -> str:
    """The proposal of the auto-define step (``attrs.autonomy_proposal``) when it is a known
    level, else the rule of the plan (unspecified when nothing fits)."""
    proposal = str(n.attrs.get("autonomy_proposal") or "")
    if proposal in AUTONOMY_ORDER:
        return proposal
    kind = f["kind"]
    if kind == "genie_space" or (kind == "endpoint" and not f["tools_n"]):
        return "l1_assistive"
    if kind in ("app", "endpoint") and f["tools_n"]:
        return "l3_tool_using_supervised"
    if kind == "job" and f["scheduled"] and f["writes"]:
        return "l4_autonomous_bounded"
    return "unspecified"


def complexity_of(f: Mapping[str, Any]) -> int:
    n = int(f["linked_n"])
    base = 0 if n == 0 else 30 if n <= 2 else 60 if n <= 5 else 90
    return min(100, base + (10 if f["providers"] else 0))


def score_of(impact: int, autonomy: str, complexity: int) -> int:
    rank = AUTONOMY_RANK.get(autonomy, 1)
    return min(100, (6 * impact + 2 * complexity) // 10 + 10 * rank)


def action_of(score: int, signals: Iterable[str]) -> str:
    sig = set(signals)
    if score >= HIGH_SCORE:
        return "register_now"
    if sig & {"money_tool", "customer_table"}:
        return "register_and_classify"
    if "external_model" in sig:
        return "register_review_vendor"
    return "register_when_convenient"


def band_of(score: int) -> str:
    return "high" if score >= HIGH_SCORE else "medium" if score >= MEDIUM_SCORE else "low"


def describe(f: Mapping[str, Any]) -> str:
    """One plain sentence from the facts. English; the console builds the Vietnamese one from the
    same facts. No URL and no workspace id (names only)."""
    head = {
        "app": "Databricks App",
        "endpoint": "Serving endpoint",
        "genie_space": "Genie space",
        "job": "Job",
    }[f["kind"]]
    text = f"{head} `{f['name']}`"
    if f["group"]:
        text += f" in group `{f['group']}`"
    parts = []
    if f["endpoints"] and f["kind"] != "endpoint":
        text_e = "calls endpoint " + ", ".join(f"`{e}`" for e in f["endpoints"][:2])
        if f["providers"]:
            text_e += " (external provider " + ", ".join(f"`{p}`" for p in f["providers"]) + ")"
        parts.append(text_e)
    elif f["providers"]:
        parts.append("uses external provider " + ", ".join(f"`{p}`" for p in f["providers"]))
    if f["customer_tables"]:
        n = len(f["customer_tables"])
        parts.append(f"reads {n} customer {'table' if n == 1 else 'tables'}")
    if f["money_tools"]:
        n = len(f["money_tools"])
        parts.append(f"calls {n} money or credit {'tool' if n == 1 else 'tools'}")
    if f["writes"]:
        parts.append("writes data")
    return text + ("; " + "; ".join(parts) if parts else "") + "."


# ----------------------------------------------------------------------------- the rows


def _clean_override(raw: Any) -> dict[str, Any]:
    """Keep only the fields of ``OVERRIDE_FIELDS`` that hold a valid value."""
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key in OVERRIDE_FIELDS:
        if key not in raw:
            continue
        val = raw[key]
        if key in ("impact", "complexity", "score"):
            if isinstance(val, int) and not isinstance(val, bool):
                out[key] = max(0, min(100, val))
        elif key == "autonomy":
            if val in AUTONOMY_ORDER:
                out[key] = val
        elif key == "recommended_action":
            if val in ACTIONS:
                out[key] = val
        elif key == "signals":
            if isinstance(val, (list, tuple)) and all(isinstance(s, str) for s in val):
                out[key] = [s for s in val if s in SIGNALS]
        elif key == "description" and isinstance(val, str) and val.strip():
            out[key] = scrub(val.strip())
    return out


def overrides_from_graph(g: Graph) -> dict[str, dict[str, Any]]:
    """``node_id -> attrs["triage"]`` for every node that carries one."""
    return {nid: dict(n.attrs["triage"]) for nid, n in g.nodes.items() if n.attrs.get("triage")}


def row_for(
    g: Graph, n: Node, kind: str, override: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    f = facts_of(g, n, kind)
    signals = signals_of(f)
    impact = impact_of(signals)
    autonomy = autonomy_of(n, f)
    complexity = complexity_of(f)
    row: dict[str, Any] = {
        "node_id": n.node_id,
        "kind": kind,
        "node_kind": n.kind,
        "name": f["name"],
        "owner_group": f["group"],
        "impact": impact,
        "autonomy": autonomy,
        "complexity": complexity,
        "score": score_of(impact, autonomy, complexity),
        "signals": signals,
        "description": describe(f),
        "facts": f,
        "evidence": [{"source": scrub(e["source"]), "ref": scrub(e["ref"])} for e in n.evidence],
        "from_override": False,
    }
    ov = _clean_override(override)
    if ov:
        row.update(ov)
        row["from_override"] = True
        if "score" not in ov and ({"impact", "autonomy", "complexity"} & set(ov)):
            row["score"] = score_of(row["impact"], row["autonomy"], row["complexity"])
    action = ov.get("recommended_action") or action_of(row["score"], row["signals"])
    row["recommended_action"] = action
    row["reason_key"] = f"tri_reason_{action}"
    row["band"] = band_of(row["score"])
    row["autonomy_rank"] = AUTONOMY_RANK.get(row["autonomy"], 1)
    return row


def triage(
    g: Graph,
    overrides: Mapping[str, Mapping[str, Any]] | None = None,
    exclude: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """One row per unmanaged candidate node, best score first (ties: name, node id).

    ``overrides`` maps a node id to the fields to replace (``OVERRIDE_FIELDS``); it wins over
    ``attrs["triage"]`` of the node. ``exclude`` holds node ids to leave out (for example nodes
    that already belong to a draft system)."""
    skip = set(exclude)
    merged = {**overrides_from_graph(g), **{k: dict(v) for k, v in (overrides or {}).items()}}
    rows = []
    for nid, n in g.nodes.items():
        kind = candidate_kind(n)
        if kind is None or nid in skip:
            continue
        rows.append(row_for(g, n, kind, merged.get(nid)))
    rows.sort(key=lambda r: (-r["score"], r["name"], r["node_id"]))
    return rows


# ----------------------------------------------------------------------------- filters


def filter_rows(
    rows: list[dict[str, Any]], kind: str = "", signal: str = "", band: str = ""
) -> list[dict[str, Any]]:
    out = rows
    if kind:
        out = [r for r in out if r["kind"] == kind]
    if signal:
        out = [r for r in out if signal in r["signals"]]
    if band:
        out = [r for r in out if r["band"] == band]
    return out
