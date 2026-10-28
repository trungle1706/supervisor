"""Suggestions for the register workflow v2 (WP-N3).

Per field of step 1 and 2: ``{value, reason_key, source}`` where ``source`` is ``scan`` (the
inventory graph and ``config/governance.yaml``), ``policy`` (the agent manifest of the deployed
policy) or ``person`` (not produced here: it marks a value the person typed). Deterministic from
the evidence that exists now; an LLM assist may be added later and would only advise.

Nothing from the workspace is copied but what the inventory node already holds (names, kinds,
attribute values). The reason is a label key (``rg2_why_*``), shown translated."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from supervisor.inventory.autoregister import GovernanceConfig, resolve_owner
from supervisor.inventory.graph import Graph
from supervisor.inventory.model import Node

WALK_KINDS = ("uses", "serves", "reads", "writes")
MAX_WALK = 200
KIND_OF_WORKSPACE: dict[str, str] = {
    "app": "app",
    "serving_endpoint": "endpoint",
    "genie_space": "genie",
    "job": "job",
}
MONEY_CLASSES = ("money",)
CREDIT_CLASSES = ("credit",)


def sg(value: Any, reason_key: str, source: str) -> dict[str, Any]:
    return {"value": value, "reason_key": reason_key, "source": source}


def evidence_of_node(graph: Graph, node: Node) -> dict[str, Any]:
    """What the graph says about a node: tools (name, risk class), model families, external
    providers, tables, a hosting agent. Walks at most two edges out, plus the agents hosted
    on the node (an agent ``hosted_on`` an App)."""
    start = [node.node_id]
    hosts: list[str] = []
    for e in graph.in_edges(node.node_id, ("hosted_on",)):
        src = graph.nodes.get(e.src_id)
        if src is not None and src.attrs.get("role") == "agent" and src.status != "gone":
            hosts.append(src.name)
            start.append(src.node_id)
    seen = set(start)
    frontier = list(start)
    for _ in range(2):
        nxt: list[str] = []
        for nid in frontier:
            for e in graph.out_edges(nid, WALK_KINDS):
                if e.dst_id not in seen and len(seen) < MAX_WALK:
                    seen.add(e.dst_id)
                    nxt.append(e.dst_id)
        frontier = nxt
    tools: dict[str, str] = {}
    families: set[str] = set()
    providers: set[str] = set()
    tables: set[str] = set()
    for nid in seen:
        n = graph.nodes.get(nid)
        if n is None or n.status == "gone":
            continue
        if n.kind == "tool":
            tools[n.name] = str(n.attrs.get("risk_class") or "")
        elif n.kind == "model" and n.attrs.get("family"):
            families.add(str(n.attrs["family"]))
        elif n.kind == "dataset" and n.attrs.get("workspace_kind") == "uc_table":
            tables.add(n.name)
        for p in n.attrs.get("external_providers") or []:
            providers.add(str(p))
    return {
        "tools": dict(sorted(tools.items())),
        "families": sorted(families),
        "providers": sorted(providers),
        "tables": sorted(tables),
        "hosts": sorted(hosts),
    }


def inherited_level(graph: Graph, node_id: str) -> str | None:
    """The effective inventory risk level of the node over the graph (computed on read)."""
    return graph.effective_risk().get(node_id)


def from_node(
    graph: Graph,
    node: Node,
    cfg: GovernanceConfig | None = None,
    facts: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Suggestions for a scanned node: ``{field: {value, reason_key, source}}``. ``facts`` are the
    active rows of the facts card of the node (WP-O2, ONBOARD_FACTS); None or empty = as before."""
    out = _from_node(graph, node, cfg)
    if facts:
        apply_facts(out, facts)
    return out


FACT_AUTONOMY: dict[str, str] = {
    "L0": "l1_assistive",
    "L1": "l1_assistive",
    "L2": "l2_workflow_step",
    "L3": "l3_tool_using_supervised",
}


def _fact(rows: Sequence[Mapping[str, Any]], kind: str) -> list[Mapping[str, Any]]:
    return [r for r in rows if r.get("kind") == kind]


def _pointer(row: Mapping[str, Any]) -> str:
    return f"{row.get('file')}:{row.get('line')}"


def fsg(value: Any, reason_key: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """A suggestion built from a fact: ``fact`` names the fact row (kind, name, file:line)."""
    out = sg(value, reason_key, "scan")
    out["fact"] = f"{row.get('kind')}:{str(row.get('name'))[:60]} @ {_pointer(row)}"[:200]
    return out


def apply_facts(out: dict[str, dict[str, Any]], rows: Sequence[Mapping[str, Any]]) -> None:
    """Replace or add suggestions from the facts card of the node (WP-O2). Each one carries a
    reason key ``rg2_why_fact_*`` and the pointer of the fact it comes from."""
    tools = _fact(rows, "tool")
    models = [*_fact(rows, "model"), *_fact(rows, "endpoint")]
    data = [*_fact(rows, "dataset"), *_fact(rows, "file")]
    purpose = next((r for r in _fact(rows, "claim") if r.get("name") == "purpose"), None)
    parts: list[str] = []
    if purpose is not None:
        parts.append(str(purpose.get("detail") or "").rstrip("."))
    if tools:
        parts.append("Tools: " + ", ".join(sorted({str(r["name"]) for r in tools})[:8]))
    if models:
        parts.append("Models: " + ", ".join(sorted({str(r["name"]) for r in models})[:5]))
    if data:
        parts.append("Data: " + ", ".join(sorted({str(r["name"]) for r in data})[:8]))
    anchor = purpose or (tools or models or data or [None])[0]
    if parts and anchor is not None:
        out["purpose"] = fsg(". ".join(p for p in parts if p)[:500], "rg2_why_fact_purpose", anchor)
    if data:
        out["data_sources"] = fsg(
            ", ".join(sorted({str(r["name"]) for r in data}))[:600], "rg2_why_fact_data", data[0]
        )
    pii = [r for r in _fact(rows, "claim") if str(r.get("detail")) == "category=personal_data"]
    if pii:
        out["personal_data"] = fsg("identifiable", "rg2_why_fact_pii", pii[0])
    elif data and "personal_data" not in out:
        out["personal_data"] = fsg("identifiable", "rg2_why_fact_data_pd", data[0])
    fam = next(
        (
            (m.group(1), r)
            for r in models
            if (m := re.search(r"family=([A-Za-z0-9_.-]+)", str(r.get("detail"))))
            and m.group(1) not in ("unknown", "None")
        ),
        None,
    )
    if fam is not None:
        out["model_family"] = fsg(fam[0], "rg2_why_fact_model", fam[1])
    if tools:
        classes = {
            m.group(1): r
            for r in tools
            if (m := re.search(r"risk_class=([a-z_]+)", str(r.get("detail"))))
        }
        for field_, cls, key in (
            ("money_movement", "money", "rg2_why_fact_tool_money"),
            ("credit_decision", "credit", "rg2_why_fact_tool_credit"),
        ):
            hit = classes.get(cls)
            out[field_] = fsg(
                hit is not None, key if hit else "rg2_why_fact_tool_none", hit or tools[0]
            )
    approvals = _fact(rows, "approval_point")
    if approvals:
        out["human_control"] = fsg("pre_approval", "rg2_why_fact_approval", approvals[0])
    auto = next(iter(_fact(rows, "autonomy")), None)
    if auto is not None and str(auto.get("name")) in FACT_AUTONOMY:
        out["autonomy_level"] = fsg(FACT_AUTONOMY[str(auto["name"])], "rg2_why_fact_autonomy", auto)


def _from_node(graph: Graph, node: Node, cfg: GovernanceConfig | None = None) -> dict[str, Any]:
    ev = evidence_of_node(graph, node)
    wk = str(node.attrs.get("workspace_kind") or "")
    kind = KIND_OF_WORKSPACE.get(wk, "other")
    out: dict[str, dict[str, Any]] = {
        "name": sg(node.display_name, "rg2_why_name_node", "scan"),
        "kind": sg(kind, "rg2_why_kind_node", "scan"),
        "system_type": sg(
            "automation" if kind == "job" else "assistant",
            "rg2_why_type_job" if kind == "job" else "rg2_why_type_node",
            "scan",
        ),
        "org_role": sg("deployer", "rg2_why_org_role", "scan"),
        "user_segment": sg("internal", "rg2_why_segment", "scan"),
        # the scan cannot see approvals: the safe-side guess, a person confirms
        "human_control": sg("none", "rg2_why_human_none", "scan"),
    }
    if ev["hosts"]:
        out["agent_id"] = sg(ev["hosts"][0], "rg2_why_agent_hosted", "scan")
    if cfg is not None:
        owner = resolve_owner(graph, node, cfg)
        if owner is not None:
            out["owner_user"] = sg(owner.owner_user, "rg2_why_owner_map", "scan")
            out["owner_team"] = sg(owner.owner_team, "rg2_why_owner_map", "scan")
    out["description"] = sg(describe(node, kind, ev), "rg2_why_desc_scan", "scan")
    out["purpose"] = sg(describe(node, kind, ev), "rg2_why_purpose_scan", "scan")
    if ev["tables"]:
        out["personal_data"] = sg("identifiable", "rg2_why_pd_tables", "scan")
        out["data_sources"] = sg(", ".join(ev["tables"])[:600], "rg2_why_sources_tables", "scan")
    level = autonomy_proposal(node)
    if level:
        out["autonomy_level"] = sg(level, "rg2_why_auto_proposal", "scan")
    elif ev["tools"]:
        out["autonomy_level"] = sg("l3_tool_using_supervised", "rg2_why_auto_tools", "scan")
    else:
        out["autonomy_level"] = sg("l1_assistive", "rg2_why_auto_notools", "scan")
    classes = set(ev["tools"].values())
    out["money_movement"] = sg(
        bool(classes & set(MONEY_CLASSES)),
        "rg2_why_money_tool" if classes & set(MONEY_CLASSES) else "rg2_why_money_none",
        "scan",
    )
    out["credit_decision"] = sg(
        bool(classes & set(CREDIT_CLASSES)),
        "rg2_why_credit_tool" if classes & set(CREDIT_CLASSES) else "rg2_why_credit_none",
        "scan",
    )
    if ev["families"]:
        out["model_family"] = sg(ev["families"][0], "rg2_why_family_model", "scan")
    elif ev["providers"]:
        out["model_family"] = sg(ev["providers"][0], "rg2_why_family_provider", "scan")
    return out


def autonomy_proposal(node: Node) -> str:
    level = node.attrs.get("autonomy_level_proposal")
    if isinstance(level, Mapping):
        level = level.get("level")
    return str(level) if level else ""


def describe(node: Node, kind: str, ev: Mapping[str, Any]) -> str:
    """One sentence about the object, from the evidence only (WP-N1 triage may replace it)."""
    label = {
        "app": "Databricks App",
        "endpoint": "serving endpoint",
        "genie": "Genie space",
        "job": "job",
    }.get(kind, "workspace object")
    parts = [f"{label} '{node.display_name}' found by the workspace scan"]
    if ev["tables"]:
        parts.append(f"reads {len(ev['tables'])} table(s)")
    if ev["tools"]:
        parts.append(f"uses {len(ev['tools'])} tool(s)")
    return (", ".join(parts) + ".")[:500]


def from_agent(
    agent_id: str, manifest: Any, facts: Sequence[Mapping[str, Any]] | None = None
) -> dict[str, Any]:
    """Suggestions for a policy-only agent, from its manifest in the deployed policy (and the
    facts card of the agent when ``facts`` are given, WP-O2)."""
    out = _from_agent(agent_id, manifest)
    if facts:
        apply_facts(out, facts)
    return out


def _from_agent(agent_id: str, manifest: Any) -> dict[str, Any]:
    out: dict[str, dict[str, Any]] = {
        "name": sg(str(manifest.name), "rg2_why_name_policy", "policy"),
        "kind": sg("other", "rg2_why_kind_policy", "policy"),
        "agent_id": sg(agent_id, "rg2_why_agent_policy", "policy"),
        "owner_user": sg(str(manifest.owner_user), "rg2_why_owner_policy", "policy"),
        "owner_team": sg(str(manifest.owner_team), "rg2_why_owner_policy", "policy"),
        "system_type": sg("assistant", "rg2_why_type_node", "policy"),
        "org_role": sg("deployer", "rg2_why_org_role", "policy"),
        "model_family": sg(str(manifest.model_family), "rg2_why_family_policy", "policy"),
    }
    desc = (
        f"Agent '{agent_id}' defined in the policy ({manifest.host_type}, "
        f"{manifest.plug_point}, risk tier {manifest.risk_tier})."
    )
    out["description"] = sg(desc, "rg2_why_desc_policy", "policy")
    out["purpose"] = sg(desc, "rg2_why_purpose_policy", "policy")
    return out
