"""Inventory service (WP24): fill from the three sources, shadow-AI check, reads and exports.

The one object the job, the CLI, the routes, the console and the compliance advisor use.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from supervisor.config import REPO_ROOT, Settings
from supervisor.core.errors import check_agent_id
from supervisor.inventory import shadow
from supervisor.inventory.fill import (
    WORKSPACE_KINDS,
    fill_from_manifests,
    fill_from_onboarding,
    fill_from_workspace,
)
from supervisor.inventory.graph import Graph, edge_dict
from supervisor.inventory.model import InventoryError, Node, canonical_name
from supervisor.inventory.store import ApplyResult, InventoryStore

log = logging.getLogger("supervisor.inventory")

AGENTS_DIR = REPO_ROOT / "src" / "supervisor_agents"
BASELINE = REPO_ROOT / "policies" / "baseline.yaml"
DEFAULT_ALLOWLIST = REPO_ROOT / "config" / "inventory_allowlist.yaml"
MAX_INVENTORY_JSON = 5_000_000
NODE_CSV = (
    "node_id",
    "kind",
    "name",
    "display_name",
    "status",
    "own_risk",
    "effective_risk",
    "risk_source",
    "decision33_class",
    "sources",
    "first_evidence",
)
EDGE_CSV = (
    "edge_id",
    "src_id",
    "src_kind",
    "src_name",
    "kind",
    "dst_id",
    "dst_kind",
    "dst_name",
    "source",
    "evidence_ref",
    "active",
)


def _cell(value: Any) -> str:
    """A CSV cell safe to open in a spreadsheet (no formula injection)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


class InventoryService:
    def __init__(self, state: Any, clock: Any, settings: Settings) -> None:
        self.store = InventoryStore(state, clock)
        self.state = state
        self.clock = clock
        self.settings = settings

    @classmethod
    def from_adapters(cls, adapters: Any) -> InventoryService:
        return cls(adapters.state, adapters.clock, adapters.settings)

    # ------------------------------------------------------------------ fillers
    def agent_rows(self) -> dict[str, dict[str, Any]]:
        return {r["agent_id"]: r for r in self.state.query("agent")}

    def fill_manifests(
        self, agents_dir: Path | None = None, baseline: Path | None = None
    ) -> ApplyResult:
        g = fill_from_manifests(
            agents_dir or AGENTS_DIR,
            baseline or BASELINE,
            self.agent_rows(),
            root=REPO_ROOT,
        )
        # The fragment is every manifest: a node only a removed manifest backed becomes gone
        # (ISO/IEC 42001 A.6: a retired agent must not stay "active" and keep its App managed).
        return self.store.apply(g, source="manifest", stale_any=True, stale_edges=True)

    def fill_onboarding(self, inventory: Mapping[str, Any] | str | Path) -> ApplyResult:
        """From the ``inventory.json`` an onboarding run wrote (a dict or a path)."""
        if isinstance(inventory, (str, Path)):
            p = Path(inventory)
            if p.stat().st_size > MAX_INVENTORY_JSON:
                raise InventoryError(f"{p.name}: inventory file is too large")
            try:
                inventory = json.loads(p.read_text(encoding="utf-8"))
            except ValueError as exc:
                raise InventoryError(f"{p.name}: not valid JSON") from exc
        if not isinstance(inventory, Mapping) or not inventory.get("agent_id"):
            raise InventoryError("inventory.json has no agent_id")
        check_agent_id(str(inventory["agent_id"]))
        g = fill_from_onboarding(inventory, resolve_dataset=self._dataset_resolver())
        return self.store.apply(g, source="onboarding")

    def _dataset_resolver(self) -> Any:
        by_tail: dict[str, set[str]] = {}
        for r in self.state.query("inventory_node", {"kind": "dataset"}):
            attrs = r.get("attrs")
            attrs = json.loads(attrs) if isinstance(attrs, str) else (attrs or {})
            if attrs.get("workspace_kind") == "uc_table" and r["status"] != "gone":
                by_tail.setdefault(r["name"].rsplit(".", 1)[-1], set()).add(r["name"])

        def resolve(name: str) -> str:
            if "." in name:
                return name
            hits = by_tail.get(canonical_name(name), set())
            return next(iter(hits)) if len(hits) == 1 else name

        return resolve

    def declared_apps(self, g: Graph) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for nid, n in g.nodes.items():
            if n.kind == "system" and n.attrs.get("role") == "agent":
                apps = [
                    g.nodes[e.dst_id].name.removeprefix("app:")
                    for e in g.out_edges(nid, ("hosted_on",))
                    if e.source in ("manifest", "onboarding") and e.dst_id in g.nodes
                ]
                out[n.name] = sorted(apps)
        return out

    def schemas(self) -> list[str]:
        return [s.strip() for s in self.settings.inventory_scan_schemas.split(",") if s.strip()]

    def refresh_workspace(
        self, reader: Any, cases: Any = None, systems: Any = None, tasks: Any = None
    ) -> dict[str, Any]:
        """Read the workspace, merge it, run the shadow-AI check (opens cases when ``cases``
        is given). Returns counts. A listing that fails is reported and does not mark the
        objects of that kind as gone. With ``INVENTORY_AUTOREGISTER=1`` and
        ``GOVERNANCE_ENABLED=1`` an unmanaged App, agent endpoint or Genie space also becomes a
        draft AI system (``systems``: a ``SystemService``; ``tasks``: a ``TaskService``); the
        result then has an ``autoregister`` entry. With the flag off the result is unchanged."""
        scan = fill_from_workspace(
            reader,
            schemas=self.schemas(),
            registered=self.declared_apps(self.store.load_graph()),
            v2=self.settings.inventory_scan_v2,
        )
        stale = {k for k in scan.ok if k in WORKSPACE_KINDS}
        res = self.store.apply(
            scan.graph,
            source="workspace_scan",
            stale_kinds=stale,
            stale_edges=len(scan.errors) == 0,
        )
        sh = self.run_shadow(cases)
        out: dict[str, Any] = {
            "apply": res.as_dict(),
            "shadow": sh.as_dict(),
            "errors": dict(sorted(scan.errors.items())),
        }
        if self.settings.inventory_autoregister:
            out["autoregister"] = self._autoregister(systems, tasks)
        return out

    def _autoregister(self, systems: Any, tasks: Any) -> dict[str, Any]:
        """Draft registration (WP-G3). Never raises: the scan result does not depend on it."""
        from supervisor.inventory import autoregister as ar

        if not self.settings.governance_enabled:
            return ar.AutoRegisterResult(
                status="skipped", reason="GOVERNANCE_ENABLED is off"
            ).as_dict()
        if systems is None:
            return ar.AutoRegisterResult(status="skipped", reason="no system service").as_dict()
        try:
            cfg = ar.GovernanceConfig.load(self.settings.governance_config_file)
            return ar.autoregister(
                self.store.load_graph(), systems, self.state, tasks=tasks, cfg=cfg
            ).as_dict()
        except Exception:  # noqa: BLE001 - the scan never fails because of governance
            log.exception("inventory: draft registration failed")
            return ar.AutoRegisterResult(status="failed", errors=1).as_dict()

    # ------------------------------------------------------------------ shadow AI
    def allowlist(self) -> shadow.Allowlist:
        path = self.settings.inventory_allowlist_file or DEFAULT_ALLOWLIST
        return shadow.Allowlist.load(Path(path))

    def run_shadow(self, cases: Any = None) -> shadow.ShadowResult:
        g = self.store.load_graph()
        verdicts = shadow.classify(
            g,
            self.allowlist(),
            self_app=self.settings.inventory_self_app,
            scan_v2=self.settings.inventory_scan_v2,
        )
        res = shadow.ShadowResult()
        eff = g.effective_risk()
        for nid in sorted(verdicts):
            status = verdicts[nid]
            self.store.set_status(nid, status)
            {"active": res.active, "allowlisted": res.allowlisted, "unmanaged": res.unmanaged}[
                status
            ].append(nid)
            if status == "unmanaged" and cases is not None:
                node = g.node_dict(g.nodes[nid], eff)
                case = cases.open_case(
                    agent_id=shadow.CASE_AGENT_ID,
                    severity=shadow.SHADOW_SEVERITY,
                    summary=shadow.case_summary(node),
                    source_kind=shadow.SOURCE_KIND,
                    source_ref=nid,
                )
                res.cases[nid] = case["case_id"]
        return res

    # ------------------------------------------------------------------ reads
    def agent_view(self, agent_id: str) -> dict[str, Any] | None:
        """Subgraph of one agent: nodes and edges with evidence, effective risk, ASCII tree."""
        g = self.store.load_graph()
        node = g.by_name("system", agent_id)
        if node is None or node.attrs.get("role") != "agent" or node.status == "gone":
            return None
        sub = g.subgraph(node.node_id)
        sub["agent_id"] = node.name
        sub["tree"] = g.ascii_tree(node.node_id)
        return sub

    def unmanaged(self) -> list[dict[str, Any]]:
        g = self.store.load_graph()
        eff = g.effective_risk()
        rows = [
            g.node_dict(n, eff)
            for n in sorted(g.nodes.values(), key=lambda n: (n.kind, n.name))
            if n.status == "unmanaged"
        ]
        links = {
            r["source_ref"]: r["case_id"]
            for r in self.state_tables_case_links()
            if r["source_kind"] == shadow.SOURCE_KIND
        }
        for r in rows:
            r["case_id"] = links.get(r["node_id"])
        return rows

    def state_tables_case_links(self) -> list[dict[str, Any]]:
        try:
            return self.state.query("case_link", {"source_kind": shadow.SOURCE_KIND})
        except Exception:  # noqa: BLE001 - a read model never fails the page
            return []

    def counts(self) -> dict[str, Any]:
        return self.store.counts()

    def summary_for_agent(self, agent_id: str) -> dict[str, Any]:
        """Small read API for the compliance advisor and the launch report: what the agent
        resolves to (model endpoints, tools, datasets, MCP servers, hosting) with evidence.
        ``found`` is False when the agent is not in the inventory."""
        view = self.agent_view(agent_id)
        if view is None:
            return {"agent_id": agent_id, "found": False}
        by_id = {n["node_id"]: n for n in view["nodes"]}
        root = by_id[view["root"]]
        groups: dict[str, list[dict[str, Any]]] = {}
        for e in view["edges"]:
            if e["src_id"] != view["root"] or e["dst_id"] not in by_id:
                continue
            dst = by_id[e["dst_id"]]
            groups.setdefault(f"{e['kind']}:{dst['kind']}", []).append(
                {
                    "name": dst["display_name"],
                    "own_risk": dst["own_risk"],
                    "effective_risk": dst["effective_risk"],
                    "source": e["source"],
                    "evidence_ref": e["evidence_ref"],
                }
            )
        return {
            "agent_id": agent_id,
            "found": True,
            "own_risk": root["own_risk"],
            "effective_risk": root["effective_risk"],
            "decision33_class": root["decision33_class"],
            "node_count": len(view["nodes"]),
            "links": {k: sorted(v, key=lambda x: x["name"]) for k, v in sorted(groups.items())},
        }

    # ------------------------------------------------------------------ exports
    def export_json(self) -> dict[str, Any]:
        g = self.store.load_graph()
        eff = g.effective_risk()
        return {
            "version": 1,
            "nodes": [g.node_dict(n, eff) for n in sorted(g.nodes.values(), key=_nkey)],
            "edges": [edge_dict(e) | {"active": e.active} for e in _edges(g)],
        }

    def export_csv(self) -> tuple[str, str]:
        """(nodes.csv, edges.csv) for the Databricks dashboard notebook."""
        g = self.store.load_graph()
        eff = g.effective_risk()
        nb = io.StringIO()
        w = csv.writer(nb, lineterminator="\n")
        w.writerow(NODE_CSV)
        for n in sorted(g.nodes.values(), key=_nkey):
            first = n.evidence[0] if n.evidence else {"ref": ""}
            w.writerow(
                [
                    _cell(v)
                    for v in (
                        n.node_id,
                        n.kind,
                        n.name,
                        n.display_name,
                        n.status,
                        n.own_risk,
                        eff.get(n.node_id),
                        n.risk_source,
                        n.decision33_class,
                        "|".join(n.sources),
                        first["ref"],
                    )
                ]
            )
        eb = io.StringIO()
        w = csv.writer(eb, lineterminator="\n")
        w.writerow(EDGE_CSV)
        for e in _edges(g):
            s, d = g.nodes.get(e.src_id), g.nodes.get(e.dst_id)
            w.writerow(
                [
                    _cell(v)
                    for v in (
                        e.edge_id,
                        e.src_id,
                        s.kind if s else "",
                        s.name if s else "",
                        e.kind,
                        e.dst_id,
                        d.kind if d else "",
                        d.name if d else "",
                        e.source,
                        e.evidence_ref,
                        "true" if e.active else "false",
                    )
                ]
            )
        return nb.getvalue(), eb.getvalue()

    def write_exports(self, out_dir: Path) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        nodes_csv, edges_csv = self.export_csv()
        files = {
            "inventory.json": json.dumps(self.export_json(), indent=2, sort_keys=True) + "\n",
            "inventory_nodes.csv": nodes_csv,
            "inventory_edges.csv": edges_csv,
        }
        paths = []
        for name, text in files.items():
            p = out_dir / name
            p.write_text(text, encoding="utf-8", newline="\n")
            paths.append(p)
        return paths


def _nkey(n: Node) -> tuple[str, str]:
    return (n.kind, n.name)


def _edges(g: Graph) -> list[Any]:
    return sorted(g.edges.values(), key=lambda e: e.edge_id)
