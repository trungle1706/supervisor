"""Assignment rules service (WP-G2, docs/assignment-rules.md): facts, runs and the table.

* ``system_facts``: the facts of one AI system (its row, its effective risk level, the parts it
  reaches in the inventory) for the pure evaluator in ``rules.py``.
* ``run``: evaluate, then save into ``assignment``. A row whose rule no longer fires is set
  inactive; nothing is ever deleted. One ``rule_run`` chain record per run: system id, rule ids
  fired, integer counts, the sha256 of the rules file. No name, no purpose, no user id.
* ``explain``: the trace as ASCII lines.
* ``guardian_floor``: the feature slugs a product owner may not switch off, with the rule ids.

Nothing here decides anything a person must decide: it applies the rules file, the same way every
time. It needs GOVERNANCE_ENABLED (``ensure_on``).
"""

from __future__ import annotations

import functools
import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from supervisor.controls.model import actor_ref
from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import NotFoundError
from supervisor.governance import rules as R
from supervisor.governance.conditions import RulesError
from supervisor.governance.model import check_system_id, check_user, ensure_on
from supervisor.inventory.model import node_id_for
from supervisor.inventory.store import InventoryStore

log = logging.getLogger("supervisor.governance")
# Guardian features that are not detectors: the gate rules of the policy file and the session
# monitor (docs/autonomy-levels.md). WP-S1 binds them per system.
GUARDIAN_EXTRA: frozenset[str] = frozenset({"policy_rules", "session_monitor"})
TRIGGERS: tuple[str, ...] = ("register", "update", "link", "unlink", "classification", "manual")


def _on(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)


def assignment_id(system_id: str, kind: str, ref_id: str) -> str:
    return "as_" + sha256_hex({"system": system_id, "kind": kind, "ref": ref_id})[:24]


def _fired_text(items: Any) -> str:
    return json.dumps(items, sort_keys=True, separators=(",", ":"))


def _fired_of(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("fired")
    try:
        val = raw if isinstance(raw, list) else json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return val if isinstance(val, list) else []


@functools.lru_cache(maxsize=1)
def _kb_obligation_ids() -> frozenset[str]:
    from supervisor.regkb import load_kb

    return frozenset(load_kb().obligations)


def _yaml_ids(folder: Path, key: str) -> set[str]:
    out: set[str] = set()
    if not folder.is_dir():
        return out
    for p in sorted(folder.glob("*.yaml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        for item in doc.get(key, []) if isinstance(doc, dict) else []:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                out.add(item["id"])
    return out


def build_catalogue(settings: Any, state: Any = None) -> R.Catalogue:
    """The ids the rules may name: regulation KB obligations, starter and stored controls and
    risks, task templates, detector slugs."""
    controls = _yaml_ids(Path(settings.controls_starter_dir), "controls")
    # controls the rules may name that are not in the catalogue yet (config/controls_pending)
    controls |= _yaml_ids(
        Path(settings.controls_starter_dir).parent / "controls_pending", "controls"
    )
    risks = _yaml_ids(Path(settings.risk_starter_dir), "risks")
    # risks the rules may name that are not in the register yet (config/risks_pending: a risk
    # that needs governing-body approval before the risk team imports it)
    risks |= _yaml_ids(Path(settings.risk_starter_dir).parent / "risks_pending", "risks")
    if state is not None:
        controls |= {str(r["control_id"]) for r in state.query("control")}
        risks |= {str(r["risk_id"]) for r in state.query("risk")}
    from supervisor.tasks.model import load_config

    tasks = {t.id for t in load_config(getattr(settings, "tasks_config", None)).templates}
    guardian: set[str] = set()
    try:
        doc = yaml.safe_load(Path(settings.detectors_config).read_text(encoding="utf-8")) or {}
        guardian = {str(k) for k in (doc.get("detectors") or {})}
    except (OSError, yaml.YAMLError, AttributeError):
        guardian = set()
    guardian |= GUARDIAN_EXTRA
    return R.Catalogue(
        obligation=_kb_obligation_ids(),
        control=frozenset(controls),
        risk=frozenset(risks),
        task=frozenset(tasks),
        guardian=frozenset(guardian),
    )


class RulesService:
    def __init__(
        self, state: Any, tables: Any, clock: Any, settings: Any, *, evidence: Any = None
    ) -> None:
        self.state = state
        self.tables = tables
        self.clock = clock
        self.settings = settings
        self.evidence_sink = evidence

    @classmethod
    def from_adapters(cls, adapters: Any, evidence: Any = None) -> RulesService:
        return cls(
            adapters.state, adapters.tables, adapters.clock, adapters.settings, evidence=evidence
        )

    # ------------------------------------------------------------------ plumbing
    def _chain(self, record_type: str, ref: str, payload: Mapping[str, Any]) -> str | None:
        if self.evidence_sink is None:
            return None
        try:
            return str(self.evidence_sink.record(record_type, ref, payload))
        except Exception:  # noqa: BLE001 - the rows are stored; log and go on
            log.exception("rule_run chain record failed")
            return None

    def ruleset(self) -> R.RuleSet:
        return R.load_rules(self.settings.assignment_rules_config)

    def catalogue(self) -> R.Catalogue:
        return build_catalogue(self.settings, self.state)

    def _system(self, system_id: str) -> dict[str, Any]:
        check_system_id(system_id)
        row = self.state.get("ai_system", {"system_id": system_id})
        if row is None:
            raise NotFoundError(f"AI system {system_id} does not exist")
        return dict(row)

    # ------------------------------------------------------------------ facts
    def system_facts(self, system_id: str) -> dict[str, Any]:
        """The facts of the system: its row, the effective risk level, and the parts it reaches
        (its linked agents and nodes, and what they use in the inventory graph)."""
        from supervisor.governance.systems import SystemService

        row = self._system(system_id)
        svc = SystemService(self.state, self.tables, self.clock, self.settings)
        level = svc.effective_risk_level(system_id).level
        comps = [
            dict(c)
            for c in self.state.query("system_component", {"system_id": system_id})
            if _on(c["active"])
        ]
        counts: dict[str, int] = {}
        tool_classes: list[str] = []
        agent_nodes: set[str] = set()
        starts: set[str] = set()
        for c in comps:
            if c["ref_kind"] == "agent":
                counts["agent"] = counts.get("agent", 0) + 1
                nid = node_id_for("system", str(c["ref_id"]))
                agent_nodes.add(nid)
                starts.add(nid)
            else:
                starts.add(str(c["ref_id"]))
        graph = InventoryStore(self.state, self.clock).load_graph()
        reached: set[str] = set()
        todo = sorted(starts)
        while todo:
            cur = todo.pop()
            if cur in reached:
                continue
            reached.add(cur)
            for e in graph.edges.values():
                if e.active and e.kind == "uses" and e.src_id == cur and e.dst_id not in reached:
                    todo.append(e.dst_id)
        for nid in sorted(reached - agent_nodes):
            node = graph.nodes.get(nid)
            if node is None or node.status == "gone":
                continue
            counts[node.kind] = counts.get(node.kind, 0) + 1
            if node.kind == "tool" and node.attrs.get("risk_class"):
                tool_classes.append(str(node.attrs["risk_class"]))
        return R.facts_of(row, level, counts, tool_classes)

    # ------------------------------------------------------------------ run and read
    def evaluate(self, system_id: str) -> tuple[R.RuleSet, R.Evaluation]:
        ensure_on(self.settings)
        rs = self.ruleset()
        return rs, R.evaluate(rs, self.system_facts(system_id), self.catalogue())

    def run(self, system_id: str, actor: str, trigger: str = "manual") -> dict[str, Any]:
        """Evaluate the rules for one system and save the result. Rows whose rule no longer
        fires become inactive (never deleted); a rule that fires again reactivates its row."""
        ensure_on(self.settings)
        check_user(actor, "actor")
        if trigger not in TRIGGERS:
            raise RulesError(f"trigger must be one of {', '.join(TRIGGERS)}")
        rs, ev = self.evaluate(system_id)
        now = self.clock.now()
        existing = {
            str(r["assignment_id"]): dict(r)
            for r in self.state.query("assignment", {"system_id": system_id})
        }
        added = reactivated = changed = 0
        wanted: set[str] = set()
        for a in ev.assignments:
            aid = assignment_id(system_id, a.kind, a.ref_id)
            wanted.add(aid)
            fired = _fired_text([{"rule": rid, "fields": list(f)} for rid, f in a.rules])
            cur = existing.get(aid)
            if cur is None:
                self.state.insert(
                    "assignment",
                    {
                        "assignment_id": aid,
                        "system_id": system_id,
                        "rule_id": a.rule_id,
                        "kind": a.kind,
                        "ref_id": a.ref_id,
                        "active": True,
                        "fired": fired,
                        "first_seen": now,
                        "last_seen": now,
                    },
                )
                added += 1
                continue
            fields: dict[str, Any] = {"last_seen": now}
            if not _on(cur["active"]):
                fields["active"] = True
                reactivated += 1
            if _fired_text(_fired_of(cur)) != fired or cur["rule_id"] != a.rule_id:
                fields["fired"] = fired
                fields["rule_id"] = a.rule_id
                changed += 1
            self.state.update("assignment", {"assignment_id": aid}, fields, cur["row_version"])
        deactivated = 0
        for aid, cur in existing.items():
            if aid not in wanted and _on(cur["active"]):
                self.state.update(
                    "assignment",
                    {"assignment_id": aid},
                    {"active": False, "last_seen": now},
                    cur["row_version"],
                )
                deactivated += 1
        per_kind = {k: len(ev.of(k)) for k in R.KINDS}
        payload: dict[str, Any] = {
            "system_id": system_id,
            "trigger": trigger,
            "actor_ref": actor_ref(self.settings, actor, "system"),
            "rules_sha256": rs.sha256,
            "rules_n": len(rs.rules),
            "rules_fired": list(ev.fired),
            "assigned_n": len(ev.assignments),
            "by_kind": per_kind,
            "added_n": added,
            "reactivated_n": reactivated,
            "changed_n": changed,
            "deactivated_n": deactivated,
            "assignments_hash": sha256_hex(
                [f"{a.kind}:{a.ref_id}:{a.rule_id}" for a in ev.assignments]
            ),
            "ts": format_ts(now),
        }
        self._chain("rule_run", f"system:{system_id}", payload)
        return {
            "system_id": system_id,
            "trigger": trigger,
            "rules_sha256": rs.sha256,
            "rules_fired": list(ev.fired),
            "assigned_n": len(ev.assignments),
            "by_kind": per_kind,
            "added_n": added,
            "reactivated_n": reactivated,
            "changed_n": changed,
            "deactivated_n": deactivated,
        }

    def run_all(self, actor: str, trigger: str = "manual") -> list[dict[str, Any]]:
        ensure_on(self.settings)
        out = []
        for s in self.state.query("ai_system", order_by=("system_id",)):
            if s["status"] != "archived":
                out.append(self.run(str(s["system_id"]), actor, trigger))
        return out

    def explain(self, system_id: str) -> list[str]:
        rs, ev = self.evaluate(system_id)
        return R.explain_lines(rs, ev)

    def assignments(self, system_id: str, *, active_only: bool = True) -> list[dict[str, Any]]:
        self._system(system_id)
        rows = []
        for r in self.state.query("assignment", {"system_id": system_id}):
            if active_only and not _on(r["active"]):
                continue
            rows.append(
                {
                    "assignment_id": r["assignment_id"],
                    "kind": r["kind"],
                    "ref_id": r["ref_id"],
                    "rule_id": r["rule_id"],
                    "rules": _fired_of(r),
                    "active": _on(r["active"]),
                    "first_seen": format_ts(r["first_seen"])
                    if hasattr(r["first_seen"], "isoformat")
                    else str(r["first_seen"]),
                    "last_seen": format_ts(r["last_seen"])
                    if hasattr(r["last_seen"], "isoformat")
                    else str(r["last_seen"]),
                }
            )
        order = {k: i for i, k in enumerate(R.KINDS)}
        rows.sort(key=lambda r: (order.get(r["kind"], 99), r["ref_id"]))
        return rows

    def obligations(self, system_id: str) -> list[dict[str, Any]]:
        """The compliance matrix rows of the system: obligations the rules assigned (source
        ``rule``), with the controls that hold them for its agents when the control catalogue
        is on, and the best status among them (working beats failing beats no_data)."""
        rows = [a for a in self.assignments(system_id) if a["kind"] == "obligation"]
        held: dict[str, set[str]] = {}
        best: dict[str, str] = {}
        if rows and getattr(self.settings, "controls_enabled", False):
            from supervisor.controls.service import ControlService

            svc = ControlService(self.state, self.tables, self.clock, self.settings)
            agents = [
                str(c["ref_id"])
                for c in self.state.query("system_component", {"system_id": system_id})
                if _on(c["active"]) and c["ref_kind"] == "agent"
            ]
            rank = {"no_data": 0, "failing": 1, "working": 2}
            for agent in sorted(agents):
                for r in svc.obligation_coverage(agent):
                    o = str(r["obligation"])
                    held.setdefault(o, set()).update(r["controls"])
                    if rank.get(r["status"], 0) >= rank.get(best.get(o, "no_data"), 0):
                        best[o] = str(r["status"])
        return [
            {
                "obligation": a["ref_id"],
                "source": "rule",
                "rules": sorted(x["rule"] for x in a["rules"]),
                "controls": sorted(held.get(a["ref_id"], ())),
                "status": best.get(a["ref_id"], "no_data"),
            }
            for a in rows
        ]

    def guardian_floor(self, system_id: str) -> list[dict[str, Any]]:
        """Feature slugs the product owner cannot switch off, each with the rule ids."""
        return [
            {"slug": a["ref_id"], "rules": sorted(x["rule"] for x in a["rules"])}
            for a in self.assignments(system_id)
            if a["kind"] == "guardian"
        ]


# ---------------------------------------------------------------------- readers for the engines
# These read the table only. With GOVERNANCE_ENABLED off, or for an agent that is on no system,
# they return nothing, so the engines behave as before.


def systems_of_agent(state: Any, agent_id: str) -> list[str]:
    low = agent_id.lower()
    return sorted(
        {
            str(c["system_id"])
            for c in state.query("system_component", {"ref_kind": "agent"})
            if _on(c["active"]) and str(c["ref_id"]).lower() == low
        }
    )


def assigned_refs(state: Any, settings: Any, agent_id: str, kind: str) -> dict[str, list[str]]:
    """ref id -> sorted system ids, for the active assignments of ``kind`` on the systems this
    agent belongs to. Empty with the flag off or when the agent is on no system."""
    if not getattr(settings, "governance_enabled", False):
        return {}
    out: dict[str, set[str]] = {}
    for sid in systems_of_agent(state, agent_id):
        sysrow = state.get("ai_system", {"system_id": sid})
        if sysrow is None or sysrow["status"] == "archived":
            continue
        for a in state.query("assignment", {"system_id": sid, "kind": kind}):
            if _on(a["active"]):
                out.setdefault(str(a["ref_id"]), set()).add(sid)
    return {k: sorted(v) for k, v in sorted(out.items())}


def agents_assigned_control(state: Any, settings: Any, control_id: str) -> frozenset[str]:
    """Lower-case ids of agents whose system has this control assigned by a rule."""
    if not getattr(settings, "governance_enabled", False):
        return frozenset()
    systems = {
        str(a["system_id"])
        for a in state.query("assignment", {"kind": "control", "ref_id": control_id})
        if _on(a["active"])
    }
    if not systems:
        return frozenset()
    return frozenset(
        str(c["ref_id"]).lower()
        for c in state.query("system_component", {"ref_kind": "agent"})
        if _on(c["active"]) and str(c["system_id"]) in systems
    )
