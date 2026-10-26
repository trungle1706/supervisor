"""Suggestions for the register workflow v2 (WP-N3).

Per field of step 1 and 2: ``{value, reason_key, source}`` where ``source`` is ``scan`` (the
inventory graph and ``config/governance.yaml``), ``policy`` (the agent manifest of the deployed
policy) or ``person`` (not produced here: it marks a value the person typed). Deterministic from
the evidence that exists now; an LLM assist may be added later and would only advise.

Nothing from the workspace is copied but what the inventory node already holds (names, kinds,
attribute values). The reason is a label key (``rg2_why_*``), shown translated."""

from __future__ import annotations

from collections.abc import Mapping
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


def from_node(graph: Graph, node: Node, cfg: GovernanceConfig | None = None) -> dict[str, Any]:
    """Suggestions for a scanned node: ``{field: {value, reason_key, source}}``."""
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


def from_agent(agent_id: str, manifest: Any) -> dict[str, Any]:
    """Suggestions for a policy-only agent, from its manifest in the deployed policy."""
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
