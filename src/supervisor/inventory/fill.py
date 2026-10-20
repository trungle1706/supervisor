"""Fillers (WP24): turn manifests, onboarding output and a workspace listing into graph fragments.

Pure functions: they read files or the reader and return a ``Graph``; the store merges it.
Every node and edge carries its source (manifest | onboarding | workspace_scan) and a pointer:
``path:line`` for repo text, ``workspace:<kind>/<name>`` for a workspace object. No PII and no
URLs or tokens are copied (workspace URLs are left out on purpose).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml

from supervisor.inventory.graph import Graph
from supervisor.inventory.model import TOOL_CLASS_RISK, Node, canonical_name

log = logging.getLogger("supervisor.inventory")

WORKSPACE_KINDS = ("app", "serving_endpoint", "registered_model", "uc_table")
DATABRICKS_HOST_NAME = "databricks"


def _line_of(lines: list[str], needle: str, default: int = 1) -> int:
    for i, line in enumerate(lines, start=1):
        if needle in line:
            return i
    return default


def _rel(path: Path, root: Path | None) -> str:
    try:
        return path.relative_to(root).as_posix() if root else path.as_posix()
    except ValueError:
        return path.as_posix()


def _supplier(g: Graph, name: str, party: str, source: str, ref: str) -> Node:
    n = Node("supplier", name, attrs={"party": party})
    n.add_evidence(source, ref)
    g.add_node(n)
    return g.nodes[n.node_id]


# ---------------------------------------------------------------------------- (a) manifests


def fill_from_manifests(
    agents_dir: Path,
    baseline_path: Path | None = None,
    agent_rows: Mapping[str, Mapping[str, Any]] | None = None,
    root: Path | None = None,
) -> Graph:
    """One system node per ``agents_dir/*/manifest.yaml`` with its tools, model endpoint,
    model, supplier and owner team. ``baseline_path`` (policies/baseline.yaml) is the authority
    for a tool's risk class when it lists the tool. ``agent_rows`` are ``agent`` table rows:
    they supply the human-set Decision 33 class and the risk tier."""
    g = Graph()
    baseline: dict[str, Any] = {}
    base_ref = ""
    if baseline_path is not None and baseline_path.exists():
        baseline = yaml.safe_load(baseline_path.read_text(encoding="utf-8")) or {}
        base_ref = _rel(baseline_path, root)
    base_tools: dict[str, str] = dict(baseline.get("tools") or {})
    base_lines = (
        baseline_path.read_text(encoding="utf-8").splitlines()
        if baseline_path is not None and baseline_path.exists()
        else []
    )
    for mf in sorted(agents_dir.glob("*/manifest.yaml")):
        text = mf.read_text(encoding="utf-8")
        lines = text.splitlines()
        try:
            doc = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            log.warning("inventory: manifest %s is not valid YAML; skipped", mf.name)
            continue
        agent_id = str(doc.get("id") or mf.parent.name)
        ref = _rel(mf, root)
        row = (agent_rows or {}).get(agent_id) or {}
        tier = row.get("risk_tier") or doc.get("risk_tier")
        sysn = Node(
            "system",
            agent_id,
            display_name=str(doc.get("name") or agent_id),
            own_risk=tier if tier in ("low", "medium", "high", "critical") else None,
            risk_source="manifest" if tier else "none",
            decision33_class=row.get("decision33_class"),
            attrs={
                "role": "agent",
                "version": str(doc.get("version", "")),
                "host_type": row.get("host_type") or doc.get("host_type"),
                "plug_point": row.get("plug_point") or doc.get("plug_point"),
                "model_family": row.get("model_family") or doc.get("model_family"),
                "gate_state": row.get("gate_state"),
            },
        )
        sysn.attrs = {k: v for k, v in sysn.attrs.items() if v not in (None, "")}
        sysn.add_evidence("manifest", f"{ref}:{_line_of(lines, 'id:')}")
        g.add_node(sysn)
        sysn = g.nodes[sysn.node_id]
        owner = doc.get("owner")
        if owner:
            o = _supplier(
                g, str(owner), "owner_team", "manifest", f"{ref}:{_line_of(lines, 'owner:')}"
            )
            g.link(sysn, "owned_by", o, "manifest", f"{ref}:{_line_of(lines, 'owner:')}")
        model_id = doc.get("model_id")
        if model_id:
            mref = f"{ref}:{_line_of(lines, 'model_id:')}"
            ep = Node("model_endpoint", str(model_id), attrs={"declared_in": "manifest"})
            ep.add_evidence("manifest", mref)
            g.add_node(ep)
            ep = g.nodes[ep.node_id]
            mdl = Node("model", str(model_id), attrs={"family": doc.get("model_family")})
            mdl.attrs = {k: v for k, v in mdl.attrs.items() if v}
            mdl.add_evidence("manifest", mref)
            g.add_node(mdl)
            mdl = g.nodes[mdl.node_id]
            g.link(sysn, "uses", ep, "manifest", mref)
            g.link(ep, "serves", mdl, "manifest", mref)
            fam = doc.get("model_family")
            if fam:
                sup = _supplier(g, str(fam), "vendor", "manifest", mref)
                g.link(mdl, "owned_by", sup, "manifest", mref)
        for t in doc.get("tools") or []:
            name = str(t.get("name", "")).strip()
            if not name:
                continue
            tref = f"{ref}:{_line_of(lines, f'name: {name}')}"
            cls = base_tools.get(name) or t.get("risk_class")
            tool = Node(
                "tool",
                f"{agent_id}/{name}",
                display_name=name,
                own_risk=TOOL_CLASS_RISK.get(str(cls)),
                risk_source="manifest" if cls in TOOL_CLASS_RISK else "none",
                attrs={"risk_class": cls, "agent": agent_id},
            )
            tool.add_evidence("manifest", tref)
            if name in base_tools:
                tool.add_evidence("manifest", f"{base_ref}:{_line_of(base_lines, f'{name}:')}")
                if t.get("risk_class") and t.get("risk_class") != base_tools[name]:
                    tool.attrs["manifest_class_differs"] = str(t["risk_class"])
            g.add_node(tool)
            g.link(sysn, "uses", g.nodes[tool.node_id], "manifest", tref)
        for srv in doc.get("mcp_servers") or []:
            sname = str(srv if not isinstance(srv, Mapping) else srv.get("name", "")).strip()
            if sname:
                m = Node("mcp_server", sname)
                m.add_evidence("manifest", f"{ref}:{_line_of(lines, sname)}")
                g.add_node(m)
                g.link(
                    sysn, "uses", g.nodes[m.node_id], "manifest", f"{ref}:{_line_of(lines, sname)}"
                )
        for key, direction in (("reads", "reads"), ("writes", "writes")):
            for ds in (
                (doc.get("datasets") or {}).get(key, [])
                if isinstance(doc.get("datasets"), Mapping)
                else []
            ):
                d = Node("dataset", str(ds))
                d.add_evidence("manifest", f"{ref}:{_line_of(lines, str(ds))}")
                g.add_node(d)
                g.link(
                    sysn,
                    direction,
                    g.nodes[d.node_id],
                    "manifest",
                    f"{ref}:{_line_of(lines, str(ds))}",
                )
        for app in _declared(doc, "databricks_app"):
            a = Node(
                "system", f"app:{app}", attrs={"role": "databricks_app", "workspace_kind": "app"}
            )
            a.add_evidence("manifest", f"{ref}:{_line_of(lines, 'databricks_app:')}")
            g.add_node(a)
            g.link(
                sysn,
                "hosted_on",
                g.nodes[a.node_id],
                "manifest",
                f"{ref}:{_line_of(lines, 'databricks_app:')}",
            )
        for ep_name in _declared(doc, "serving_endpoint"):
            e = Node("model_endpoint", ep_name)
            e.add_evidence("manifest", f"{ref}:{_line_of(lines, 'serving_endpoint:')}")
            g.add_node(e)
            g.link(
                sysn,
                "uses",
                g.nodes[e.node_id],
                "manifest",
                f"{ref}:{_line_of(lines, 'serving_endpoint:')}",
            )
    # Agents registered in the ``agent`` table without a repo manifest (the usual case for an
    # agent onboarded on Databricks). Without this their App would be reported as shadow AI.
    seen = {n.name for n in g.nodes.values() if n.kind == "system"}
    for agent_id, row in sorted((agent_rows or {}).items()):
        if canonical_name(agent_id) in seen or row.get("status") == "retired":
            continue
        tier = row.get("risk_tier")
        ref = f"agent_table:{agent_id}"
        sysn = Node(
            "system",
            agent_id,
            display_name=str(row.get("name") or agent_id),
            own_risk=tier if tier in ("low", "medium", "high", "critical") else None,
            risk_source="manifest" if tier in ("low", "medium", "high", "critical") else "none",
            decision33_class=row.get("decision33_class"),
            attrs={
                k: v
                for k, v in {
                    "role": "agent",
                    "host_type": row.get("host_type"),
                    "plug_point": row.get("plug_point"),
                    "model_family": row.get("model_family"),
                    "gate_state": row.get("gate_state"),
                }.items()
                if v not in (None, "")
            },
        )
        sysn.add_evidence("manifest", ref)
        g.add_node(sysn)
        owner = str(row.get("owner_team") or "").strip()
        if owner and not owner.startswith("FILL-ME"):
            o = _supplier(g, owner, "owner_team", "manifest", ref)
            g.link(g.nodes[sysn.node_id], "owned_by", o, "manifest", ref)
    return g


def _declared(doc: Mapping[str, Any], key: str) -> list[str]:
    v = doc.get(key)
    if not v:
        return []
    return [str(x) for x in (v if isinstance(v, list) else [v])]


# ---------------------------------------------------------------------------- (b) onboarding


def fill_from_onboarding(
    inv: Mapping[str, Any],
    *,
    resolve_dataset: Callable[[str], str] | None = None,
) -> Graph:
    """Graph fragment from one onboarding ``inventory.json`` (a dict as written by
    ``supervisor.onboard.run``). ``resolve_dataset`` maps a bare table name from code to the
    node name of a known dataset (for example a Unity Catalog full name)."""
    g = Graph()
    agent_id = str(inv.get("agent_id") or "").strip()
    if not agent_id:
        return g
    resolve = resolve_dataset or (lambda n: n)
    tier = inv.get("declared_risk_tier")
    manifest_file = inv.get("manifest_file")
    sysn = Node(
        "system",
        agent_id,
        display_name=str(inv.get("name") or agent_id),
        own_risk=tier if tier in ("low", "medium", "high", "critical") else None,
        risk_source="onboarding" if tier else "none",
        attrs={
            k: v
            for k, v in {
                "role": "agent",
                "version": inv.get("version"),
                "host_type": inv.get("host_type"),
                "plug_point": inv.get("plug_point"),
                "model_family": inv.get("model_family"),
                "framework": inv.get("framework"),
                "revision": inv.get("revision"),
            }.items()
            if v not in (None, "", "unknown")
        },
    )
    sysn.add_evidence(
        "onboarding", f"{manifest_file}:1" if manifest_file else f"inventory.json:{agent_id}"
    )
    g.add_node(sysn)
    sysn = g.nodes[sysn.node_id]
    owner = str(inv.get("owner_team") or "").strip()
    if owner and not owner.startswith("FILL-ME"):
        o = _supplier(g, owner, "owner_team", "onboarding", "inventory.json:owner_team")
        g.link(sysn, "owned_by", o, "onboarding", "inventory.json:owner_team")
    for t in inv.get("tools") or []:
        name = str(t.get("name", "")).strip()
        if not name:
            continue
        d = t.get("definition") or t.get("manifest_entry") or {}
        ref = _ev(d) or f"inventory.json:tools/{name}"
        cls = t.get("risk_class")
        tool = Node(
            "tool",
            f"{agent_id}/{name}",
            display_name=name,
            own_risk=TOOL_CLASS_RISK.get(str(cls)),
            risk_source="onboarding" if cls in TOOL_CLASS_RISK else "none",
            attrs={"risk_class": cls, "agent": agent_id, "risk_basis": t.get("risk_source")},
        )
        tool.add_evidence("onboarding", ref)
        g.add_node(tool)
        g.link(sysn, "uses", g.nodes[tool.node_id], "onboarding", ref)
    endpoints = list(inv.get("model_endpoints") or [])
    for ep in endpoints:
        name = str(ep.get("name", "")).strip()
        if not name:
            continue
        ref = _ev(ep.get("evidence")) or f"inventory.json:model_endpoints/{name}"
        n = Node("model_endpoint", name, attrs={"declared_in": ep.get("source")})
        n.add_evidence("onboarding", ref)
        g.add_node(n)
        n = g.nodes[n.node_id]
        g.link(sysn, "uses", n, "onboarding", ref)
        fam = ep.get("family")
        if fam:
            sup = _supplier(g, str(fam), "vendor", "onboarding", ref)
            m = Node("model", name, attrs={"family": fam})
            m.add_evidence("onboarding", ref)
            g.add_node(m)
            g.link(n, "serves", g.nodes[m.node_id], "onboarding", ref)
            g.link(g.nodes[m.node_id], "owned_by", sup, "onboarding", ref)
    for call in inv.get("llm_calls") or []:
        # a model call site found in code that has no declared endpoint of the same name
        model = str(call.get("model") or "").strip()
        if model and not any(
            str(e.get("name", "")).strip().lower() == model.lower() for e in endpoints
        ):
            ref = _ev(call.get("evidence")) or "inventory.json:llm_calls"
            n = Node("model_endpoint", model, attrs={"declared_in": "code", "via": call.get("via")})
            n.add_evidence("onboarding", ref)
            g.add_node(n)
            g.link(sysn, "uses", g.nodes[n.node_id], "onboarding", ref)
    for srv in inv.get("mcp_servers") or []:
        name = str(srv.get("name", "")).strip()
        if name:
            ref = _ev(srv.get("evidence")) or f"inventory.json:mcp_servers/{name}"
            m = Node("mcp_server", name)
            m.add_evidence("onboarding", ref)
            g.add_node(m)
            g.link(sysn, "uses", g.nodes[m.node_id], "onboarding", ref)
    for p in inv.get("prompts") or []:
        sha = str(p.get("sha256", ""))[:16]
        if not sha:
            continue
        ref = _ev(p.get("evidence")) or "inventory.json:prompts"
        pn = Node(
            "prompt",
            f"{agent_id}/{p.get('kind', 'prompt')}/{sha}",
            attrs={"kind": p.get("kind"), "sha256": p.get("sha256")},
        )
        pn.add_evidence("onboarding", ref)
        g.add_node(pn)
        g.link(sysn, "uses", g.nodes[pn.node_id], "onboarding", ref)
    for tb in inv.get("tables") or []:
        name = str(tb.get("name", "")).strip()
        if not name:
            continue
        direction = "writes" if tb.get("direction") == "write" else "reads"
        ref = _ev(tb.get("evidence")) or f"inventory.json:tables/{name}"
        ds = Node("dataset", resolve(name))
        ds.add_evidence("onboarding", ref)
        g.add_node(ds)
        g.link(sysn, direction, g.nodes[ds.node_id], "onboarding", ref)
    for app in inv.get("apps") or []:
        name = str(app).strip()
        if name:
            a = Node(
                "system", f"app:{name}", attrs={"role": "databricks_app", "workspace_kind": "app"}
            )
            a.add_evidence("onboarding", f"inventory.json:apps/{name}")
            g.add_node(a)
            g.link(
                sysn, "hosted_on", g.nodes[a.node_id], "onboarding", f"inventory.json:apps/{name}"
            )
    return g


def _ev(ev: Any) -> str:
    if isinstance(ev, Mapping) and ev.get("file"):
        return f"{ev['file']}:{ev.get('line', 1)}"
    return ""


# ---------------------------------------------------------------------------- (c) workspace


class WorkspaceScan:
    """Result of ``fill_from_workspace``: the fragment and which sections were read."""

    def __init__(self, graph: Graph, ok: set[str], errors: dict[str, str]) -> None:
        self.graph = graph
        self.ok = ok  # workspace kinds listed without error (see WORKSPACE_KINDS)
        self.errors = errors  # kind -> exception class name (never the message)


def fill_from_workspace(
    reader: Any,
    *,
    schemas: list[str] | None = None,
    registered: Mapping[str, list[str]] | None = None,
) -> WorkspaceScan:
    """Read Apps, serving endpoints, registered models and UC tables (read only).

    ``schemas`` are ``catalog.schema`` names; without them a reader that has ``list_schemas``
    (the fixture reader) is asked, a live reader lists none (set INVENTORY_SCAN_SCHEMAS).
    ``registered`` maps an agent id to the Databricks App names its manifest declares: an app
    named like an agent, or declared by it, gets a ``hosted_on`` edge from that agent."""
    g = Graph()
    ok: set[str] = set()
    errors: dict[str, str] = {}
    registered = registered or {}

    def section(kind: str, fn: Callable[[], None]) -> None:
        try:
            fn()
            ok.add(kind)
        except Exception as exc:  # noqa: BLE001 - one failed listing must not hide the others
            errors[kind] = type(exc).__name__
            log.warning("inventory: workspace listing %s failed: %s", kind, type(exc).__name__)

    host = Node("supplier", DATABRICKS_HOST_NAME, attrs={"party": "platform"})
    host.add_evidence("workspace_scan", "workspace:host")
    g.add_node(host)
    host = g.nodes[host.node_id]

    def apps() -> None:
        for a in getattr(reader, "list_apps", lambda: [])():
            name = str(a.get("name") or "").strip()
            if not name:
                continue
            ref = f"workspace:app/{name}"
            n = Node(
                "system",
                f"app:{name}",
                display_name=name,
                status="unmanaged",
                attrs={
                    "role": "databricks_app",
                    "workspace_kind": "app",
                },
            )
            n.add_evidence("workspace_scan", ref)
            g.add_node(n)
            g.link(g.nodes[n.node_id], "owned_by", host, "workspace_scan", ref)
            for agent_id, declared in sorted(registered.items()):
                keys = {canonical_name(agent_id), *(canonical_name(d) for d in declared)}
                if canonical_name(name).replace("-", "_") in {k.replace("-", "_") for k in keys}:
                    src = Node("system", agent_id)
                    g.link(src, "hosted_on", g.nodes[n.node_id], "workspace_scan", ref)

    def endpoints() -> None:
        for e in reader.list_serving_endpoints():
            name = str(e.get("name") or "").strip()
            if not name:
                continue
            ref = f"workspace:serving-endpoint/{name}"
            n = Node(
                "model_endpoint",
                name,
                status="unmanaged",
                attrs={
                    k: v
                    for k, v in {
                        "workspace_kind": "serving_endpoint",
                        "task": e.get("task"),
                        "state": e.get("state"),
                    }.items()
                    if v
                },
            )
            n.add_evidence("workspace_scan", ref)
            g.add_node(n)
            n = g.nodes[n.node_id]
            g.link(n, "hosted_on", host, "workspace_scan", ref)
            served = [str(s) for s in (e.get("served") or []) if s]
            if e.get("model"):
                served.append(str(e["model"]))
            for s in sorted(set(served)):
                m = Node("model", s, attrs={"family": e.get("family")} if e.get("family") else {})
                m.add_evidence("workspace_scan", ref)
                g.add_node(m)
                g.link(n, "serves", g.nodes[m.node_id], "workspace_scan", ref)

    def models() -> None:
        lister = getattr(reader, "list_registered_models", None)
        if lister is None:
            raise NotImplementedError("reader has no list_registered_models")
        for m in lister():
            name = str(m.get("name") or "").strip()
            if name:
                n = Node("model", name, attrs={"workspace_kind": "registered_model"})
                n.add_evidence("workspace_scan", f"workspace:registered-model/{name}")
                g.add_node(n)

    def tables() -> None:
        wanted = list(schemas or [])
        if not wanted and hasattr(reader, "list_schemas"):
            wanted = list(reader.list_schemas())
        for cs in wanted:
            catalog, _, schema = cs.partition(".")
            if not schema:
                continue
            for t in reader.list_tables(catalog, schema):
                full = t if t.count(".") >= 2 else f"{catalog}.{schema}.{t}"
                n = Node("dataset", full, attrs={"workspace_kind": "uc_table"})
                n.add_evidence("workspace_scan", f"workspace:uc-table/{full}")
                g.add_node(n)

    def lineage() -> None:
        for x in getattr(reader, "lineage", lambda: [])():
            agent, table = str(x.get("agent") or ""), str(x.get("table") or "")
            if not agent or not table:
                continue
            ds = Node("dataset", table)
            ds.add_evidence("workspace_scan", f"workspace:lineage/{table}")
            g.add_node(ds)
            kind = "writes" if str(x.get("direction")) == "write" else "reads"
            g.link(
                Node("system", agent),
                kind,
                g.nodes[ds.node_id],
                "workspace_scan",
                f"workspace:lineage/{agent}",
            )

    section("app", apps)
    section("serving_endpoint", endpoints)
    section("registered_model", models)
    section("uc_table", tables)
    section("lineage", lineage)
    return WorkspaceScan(g, ok, errors)
