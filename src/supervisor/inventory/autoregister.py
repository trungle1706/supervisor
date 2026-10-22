"""Draft registration from the workspace scan (WP-G3, docs/inventory.md).

After the shadow-AI check, an *unmanaged* Databricks App, agent serving endpoint or Genie space
becomes a draft ``ai_system`` (status draft, risk level ``unspecified``, tag
``source=workspace_scan``). The node is linked to it and the initiation task "Confirm context" is
opened for the owner. The owner is the configured default (``config/governance.yaml``): by
group, else by catalog, else ``default_owner``.

* Off by default: ``INVENTORY_AUTOREGISTER=1`` and ``GOVERNANCE_ENABLED=1`` are both needed.
* Deduplicated on the inventory node id: a node that has any ``system_component`` row (active or
  not) is never registered again, so an archived or unlinked draft does not come back.
* Never blocks or pauses anything. A failure on one node is logged and counted; the scan result
  does not change. No name, URL or id of the workspace goes anywhere but the node it came from.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from supervisor.config import REPO_ROOT
from supervisor.inventory.graph import Graph
from supervisor.inventory.model import Node

log = logging.getLogger("supervisor.inventory")

DEFAULT_CONFIG = REPO_ROOT / "config" / "governance.yaml"
ACTOR = "workspace_scan"
SOURCE_TAG = "workspace_scan"
TEMPLATE_ID = "SYS-CONFIRM-CONTEXT"
CANDIDATE_KINDS = ("app", "agent_endpoint", "genie_space")
MAX_PER_RUN = 100  # a runaway scan must not create thousands of drafts at once
_DRAFT_KEYS = ("system_type", "org_role", "user_segment", "personal_data", "human_control")


@dataclass
class Owner:
    owner_user: str
    owner_team: str

    def usable(self) -> bool:
        return not any("FILL-ME" in v or not v for v in (self.owner_user, self.owner_team))


@dataclass
class GovernanceConfig:
    default_owner: Owner | None = None
    by_group: dict[str, Owner] = field(default_factory=dict)
    by_catalog: dict[str, Owner] = field(default_factory=dict)
    draft_defaults: dict[str, str] = field(default_factory=dict)
    task_title: str = "Confirm context"
    task_owner_role: str = "owner"
    task_due_days: int = 14

    @classmethod
    def load(cls, path: Path | None = None) -> GovernanceConfig:
        p = Path(path) if path else DEFAULT_CONFIG
        if not p.exists():
            return cls()
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            log.warning("governance: config is not valid YAML; defaults used")
            return cls()
        if not isinstance(doc, Mapping):
            return cls()
        task = doc.get("initiation_task") if isinstance(doc.get("initiation_task"), Mapping) else {}
        due = task.get("due_days", 14)
        return cls(
            default_owner=_owner(doc.get("default_owner")),
            by_group=_owners(doc.get("default_owner_by_group")),
            by_catalog=_owners(doc.get("default_owner_by_catalog")),
            draft_defaults={
                k: str(v) for k, v in (doc.get("draft_defaults") or {}).items() if k in _DRAFT_KEYS
            },
            task_title=str(task.get("title") or "Confirm context")[:200],
            task_owner_role=str(task.get("owner_role") or "owner"),
            task_due_days=due if isinstance(due, int) and not isinstance(due, bool) else 14,
        )


def _owner(value: Any) -> Owner | None:
    if not isinstance(value, Mapping):
        return None
    user, team = str(value.get("owner_user") or "").strip(), str(value.get("owner_team") or "")
    return Owner(user, team.strip()) if user and team.strip() else None


def _owners(value: Any) -> dict[str, Owner]:
    out: dict[str, Owner] = {}
    if isinstance(value, Mapping):
        for k, v in value.items():
            o = _owner(v)
            if o is not None and "FILL-ME" not in str(k):
                out[str(k).strip().lower()] = o
    return out


@dataclass
class AutoRegisterResult:
    created: list[str] = field(default_factory=list)  # system ids
    already: int = 0  # candidates that already have a system component
    skipped_no_owner: int = 0
    skipped_name: int = 0
    errors: int = 0
    status: str = "ran"
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "status": self.status,
            "created": len(self.created),
            "already_registered": self.already,
            "skipped_no_owner": self.skipped_no_owner,
            "skipped_name": self.skipped_name,
            "errors": self.errors,
        }
        if self.reason:
            out["reason"] = self.reason
        return out


def candidate_kind(node: Node) -> str | None:
    """``app``, ``agent_endpoint`` or ``genie_space`` for a node the scan may register."""
    wk = node.attrs.get("workspace_kind")
    if wk == "app" or wk == "genie_space":
        return str(wk)
    if wk == "serving_endpoint" and node.attrs.get("agent_endpoint"):
        return "agent_endpoint"
    return None


def catalogs_of(graph: Graph, node: Node) -> list[str]:
    """Catalogs of the Unity Catalog objects the node reads, writes, serves or uses, sorted."""
    found: set[str] = set()
    for e in graph.out_edges(node.node_id, ("reads", "writes", "serves", "uses")):
        dst = graph.nodes.get(e.dst_id)
        if dst is not None and dst.name.count(".") >= 2:
            found.add(dst.name.split(".", 1)[0])
    return sorted(found)


def resolve_owner(graph: Graph, node: Node, cfg: GovernanceConfig) -> Owner | None:
    """Group, then catalog, then the default. ``None`` when nothing usable is configured."""
    group = str(node.attrs.get("owner_group") or "").strip().lower()
    if group and group in cfg.by_group and cfg.by_group[group].usable():
        return cfg.by_group[group]
    for cat in catalogs_of(graph, node):
        o = cfg.by_catalog.get(cat.lower())
        if o is not None and o.usable():
            return o
    if cfg.default_owner is not None and cfg.default_owner.usable():
        return cfg.default_owner
    return None


def _purpose(node: Node, kind: str) -> str:
    label = {"app": "Databricks App", "agent_endpoint": "agent serving endpoint"}.get(
        kind, "Genie space"
    )
    return (
        f"Draft created from the workspace scan for the {label} '{node.display_name}'. "
        "Owner: confirm the context (purpose, users, data) and the intake fields."
    )[:2000]


def _first_ref(node: Node) -> str:
    for e in node.evidence:
        if e["source"] == "workspace_scan":
            return e["ref"][:200]
    return ""


def autoregister(
    graph: Graph,
    systems: Any,
    state: Any,
    *,
    tasks: Any = None,
    cfg: GovernanceConfig | None = None,
    max_new: int = MAX_PER_RUN,
) -> AutoRegisterResult:
    """Register a draft system for each unmanaged candidate node of ``graph``.

    ``systems`` is a ``SystemService``; ``tasks`` a ``TaskService`` (optional: without it the
    draft is made but no task is opened); ``state`` the state port, to look up existing links."""
    from supervisor.core.errors import SupervisorError

    cfg = cfg or GovernanceConfig.load()
    res = AutoRegisterResult()
    linked = {str(r["ref_id"]) for r in state.query("system_component", {"ref_kind": "node"})}
    for nid, node in sorted(graph.nodes.items()):
        kind = candidate_kind(node)
        if kind is None or node.status != "unmanaged":
            continue
        if nid in linked:
            res.already += 1
            continue
        if len(res.created) >= max_new:
            break
        owner = resolve_owner(graph, node, cfg)
        if owner is None:
            res.skipped_no_owner += 1
            continue
        try:
            sid = _register(systems, tasks, node, kind, owner, cfg)
        except _NameTaken:
            res.skipped_name += 1
        except (SupervisorError, ValueError, KeyError):
            res.errors += 1
            log.exception("inventory: draft registration failed for a %s node", kind)
        except Exception:  # noqa: BLE001 - the scan never fails because of governance
            res.errors += 1
            log.exception("inventory: draft registration failed for a %s node", kind)
        else:
            res.created.append(sid)
    return res


class _NameTaken(Exception):
    pass


def _register(
    systems: Any, tasks: Any, node: Node, kind: str, owner: Owner, cfg: GovernanceConfig
) -> str:
    from supervisor.governance.model import SystemsError

    draft: dict[str, Any] = {
        "name": node.display_name,
        "owner_user": owner.owner_user,
        "owner_team": owner.owner_team,
        "purpose": _purpose(node, kind),
        "system_type": "assistant",
        "org_role": "deployer",
        "user_segment": "internal",
        "personal_data": "identifiable",
        "human_control": "none",
        "tags": {
            "source": SOURCE_TAG,
            "workspace_kind": str(node.attrs.get("workspace_kind")),
            "node_id": node.node_id,
            "intake_defaults": "true",  # the intake fields are guesses until the owner confirms
        },
    }
    draft.update(cfg.draft_defaults)
    try:
        view = systems.register(draft, ACTOR)
    except SystemsError as exc:
        if "already" not in str(exc):
            raise
        # A person already made a system with this name: try the kind-qualified name once.
        draft["name"] = f"{node.display_name} ({kind.replace('_', ' ')})"
        try:
            view = systems.register(draft, ACTOR)
        except SystemsError:
            raise _NameTaken from None
    sid = str(view["system_id"])
    try:
        systems.link(
            sid,
            "node",
            node.node_id,
            ACTOR,
            role="component_of",
            source="workspace_scan",
            evidence_ref=_first_ref(node),
        )
    except Exception:
        # No unlinked draft may survive: it could not be deduplicated on the next scan.
        try:
            systems.archive(sid, ACTOR)
        except Exception:  # noqa: BLE001 - report the link failure, not this one
            log.exception("inventory: could not archive a draft whose link failed")
        raise
    _copy_autonomy(systems, sid, node)
    if tasks is not None:
        _open_task(tasks, sid, cfg)
    return sid


def _copy_autonomy(systems: Any, system_id: str, node: Node) -> None:
    """Keep the autonomy level proposal (``node.attrs.autonomy_level_proposal``, set from a
    ``supervisor.onboard.define`` run) as a PROPOSAL in ``tags.autonomy_level_proposal`` (plus
    ``tags.autonomy_level_proposal_ref``, the evidence). It never sets
    ``ai_system.autonomy_level``: a person sets the level on the Classification tab, so the
    apply gate of a Decision 33 classification and the level 5 floor are never met by a scan.
    Goes through ``SystemService.update_fields`` (a ``system_change`` record)."""
    level = node.attrs.get("autonomy_level_proposal")
    if isinstance(level, Mapping):
        level = level.get("level")
    if not level:
        return
    try:
        tags = dict(systems.get(system_id).get("tags") or {})
        tags["autonomy_level_proposal"] = str(level)[:100]
        ref = _first_ref(node)
        if ref:
            tags["autonomy_level_proposal_ref"] = str(ref)[:100]
        systems.update_fields(system_id, {"tags": tags}, ACTOR)
    except Exception:  # noqa: BLE001 - the proposal is optional; a draft without it is fine
        log.info("inventory: autonomy level proposal not kept on the draft")


def _open_task(tasks: Any, system_id: str, cfg: GovernanceConfig) -> None:
    """The initiation task "Confirm context" on the draft. One per system (hash of the pair)."""
    try:
        row = tasks._row_for(  # noqa: SLF001 - the one place that writes a task for a system
            system_id,
            "initiation",
            template_id=TEMPLATE_ID,
            kind="custom",
            title=f"{cfg.task_title} (intake defaults, to confirm)"[:200],
            owner_role=cfg.task_owner_role,
            required=True,
            due_days=cfg.task_due_days,
            evidence_kind="none",
            evidence_ref=None,
            level="low",
            d33_class="unclassified",
            actor=ACTOR,
        )
        tasks._insert(row, ACTOR)  # noqa: SLF001 - a repeat is a no-op (duplicate key)
    except Exception:  # noqa: BLE001 - a draft without its task is still a draft
        log.exception("inventory: could not open the initiation task of a draft system")
