"""AI system service (WP-G0, docs/governance.md): the unit of governance.

The one object the routes, the console and later work packages use. It reads and writes
``ai_system``, ``system_team`` and ``system_component`` through the state port (SQLite and Delta
alike). Every change writes a ``system_change`` chain record (canonical JSON, integers and
hashes only; no name, no purpose, no user id).

* Risk: ``effective_risk_level`` is the maximum of the manual level and the level inherited
  over the linked agents and inventory nodes (the WP24 graph, ADR D16). Computed on read,
  never stored.
* Scope: ``scope_for`` says which systems a person sees. ``SCOPED_ROLES`` is the one place that
  lists the roles that see only their own systems.
* Segregation of duties: the owner of a system cannot be its reviewer or oversight manager.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from supervisor.controls.model import actor_ref
from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import ConcurrencyError, DuplicateKeyError, NotFoundError
from supervisor.governance.model import (
    EDITABLE,
    INVENTORY_TO_SYSTEM,
    LIFECYCLE_STAGES,
    LINK_ROLES,
    LINK_SOURCES,
    MAX_LINKS,
    MAX_MEMBERS,
    REF_KINDS,
    RISK_LEVELS,
    SOD_ROLES,
    STATUSES,
    SYSTEM_TYPES,
    TEAM_ROLES,
    SegregationOfDuties,
    SystemsError,
    check_ref_id,
    check_system_id,
    check_user,
    choice,
    max_level,
    normalise_draft,
    normalise_field,
    rank,
)
from supervisor.inventory.model import canonical_name, node_id_for
from supervisor.inventory.store import InventoryStore

log = logging.getLogger("supervisor.governance")

# Roles that see every system. The others (SCOPED_ROLES) see the systems they are on in
# system_team, the systems they own, and the systems owned by their team. Together the two
# sets are every role of core/rbac.py (a test checks it).
ALL_ROLES: frozenset[str] = frozenset({"admin", "auditor", "reviewer", "approver"})
SCOPED_ROLES: frozenset[str] = frozenset({"owner", "viewer", "operator"})


class _All:
    """Marker for "every system" (``scope_for`` result for ALL_ROLES)."""

    _instance: _All | None = None

    def __new__(cls) -> _All:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "ALL"

    def __contains__(self, item: object) -> bool:
        return True


ALL = _All()
Scope = frozenset[str] | _All

FILTERS = ("status", "owner_team", "lifecycle_stage", "risk", "system_type", "q")


def _on(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)


def _plain(value: Any) -> Any:
    """JSON-friendly copy: datetimes as text, containers walked."""
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dt.datetime):
        return format_ts(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def _tags(row: Mapping[str, Any]) -> dict[str, str]:
    raw = row.get("tags")
    if isinstance(raw, Mapping):
        return dict(raw)
    try:
        val = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return dict(val) if isinstance(val, dict) else {}


def component_id(system_id: str, ref_kind: str, ref_id: str, role: str) -> str:
    return (
        "sc_"
        + sha256_hex({"system": system_id, "ref_kind": ref_kind, "ref_id": ref_id, "role": role})[
            :24
        ]
    )


def system_id_for(name: str) -> str:
    """Deterministic id from the canonical name, so a repeat registration is a duplicate."""
    return "sys_" + sha256_hex({"name": canonical_name(name)})[:16]


@dataclass(frozen=True)
class EffectiveRisk:
    """Result of ``effective_risk_level``. ``source`` says which level won."""

    system_id: str
    level: str
    source: str  # manual | inherited | classifier
    manual_level: str
    inherited_level: str
    via: tuple[dict[str, str], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "system_id": self.system_id,
            "level": self.level,
            "source": self.source,
            "manual_level": self.manual_level,
            "inherited_level": self.inherited_level,
            "via": [dict(v) for v in self.via],
        }


class SystemService:
    def __init__(
        self, state: Any, tables: Any, clock: Any, settings: Any, *, evidence: Any = None
    ) -> None:
        self.state = state
        self.tables = tables
        self.clock = clock
        self.settings = settings
        self.evidence_sink = evidence

    @classmethod
    def from_adapters(cls, adapters: Any, evidence: Any = None) -> SystemService:
        return cls(
            adapters.state, adapters.tables, adapters.clock, adapters.settings, evidence=evidence
        )

    # ------------------------------------------------------------------ plumbing
    def _chain(self, record_type: str, ref: str, payload: Mapping[str, Any]) -> str | None:
        if self.evidence_sink is None:
            return None
        try:
            return str(self.evidence_sink.record(record_type, ref, payload))
        except Exception:  # noqa: BLE001 - the row is stored; log and go on
            log.exception("system chain record failed")
            return None

    def _run_rules(self, system_id: str, actor: str, trigger: str) -> None:
        """WP-G2: re-evaluate the assignment rules of the system after a change. Only with
        GOVERNANCE_ENABLED on; a rules problem is logged and never stops the change."""
        if not getattr(self.settings, "governance_enabled", False):
            return
        try:
            from supervisor.governance.rules_service import RulesService

            RulesService(
                self.state, self.tables, self.clock, self.settings, evidence=self.evidence_sink
            ).run(system_id, actor, trigger)
        except Exception:  # noqa: BLE001 - the change is stored; the CLI shows the rules problem
            log.exception("assignment rules run failed for %s", system_id)

    def _changed(
        self,
        action: str,
        row: Mapping[str, Any],
        actor: str,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        sid = str(row["system_id"])
        team = self._team_rows(sid)
        links = self._component_rows(sid)
        payload: dict[str, Any] = {
            "system_id": sid,
            "action": action,
            "actor_ref": actor_ref(self.settings, actor, "system"),
            "status": row["status"],
            "system_type": row["system_type"],
            "lifecycle_stage": row["lifecycle_stage"],
            "risk_level": row["risk_level"],
            "risk_level_source": row["risk_level_source"],
            "decision33_class": row["decision33_class"],
            "team_n": len(team),
            "components_n": len(links),
            "row_hash": sha256_hex(_plain(dict(row))),
            "team_hash": sha256_hex(sorted(f"{t['user_id']}:{t['team_role']}" for t in team)),
            "links_hash": sha256_hex(sorted(str(x["component_id"]) for x in links)),
            "ts": format_ts(self.clock.now()),
        }
        if extra:
            payload.update(extra)
        self._chain("system_change", f"system:{sid}", payload)

    def _need(self, system_id: str) -> dict[str, Any]:
        check_system_id(system_id)
        row = self.state.get("ai_system", {"system_id": system_id})
        if row is None:
            raise NotFoundError(f"AI system {system_id} does not exist")
        return dict(row)

    def _need_open(self, system_id: str) -> dict[str, Any]:
        row = self._need(system_id)
        if row["status"] == "archived":
            raise SystemsError(f"AI system {system_id} is archived; it cannot be changed")
        return row

    def _team_rows(self, system_id: str) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.state.query(
                "system_team", {"system_id": system_id}, order_by=("user_id",)
            )
            if _on(r["active"])
        ]

    def _component_rows(self, system_id: str) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.state.query(
                "system_component", {"system_id": system_id}, order_by=("component_id",)
            )
            if _on(r["active"])
        ]

    def _view(self, row: Mapping[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in dict(row).items()}
        out["tags"] = _tags(row)
        out["money_movement"] = _on(row.get("money_movement"))
        out["credit_decision"] = _on(row.get("credit_decision"))
        return out

    # ------------------------------------------------------------------ writes
    def register(
        self, draft: Mapping[str, Any], actor: str, *, for_user: Any = None
    ) -> dict[str, Any]:
        """Create a system (status draft). The owner joins the team as system_owner; a business
        owner who is another person joins as business_owner. ``for_user`` is the calling
        principal: a scoped caller may use only a team already in their scope."""
        check_user(actor, "actor")
        fields = normalise_draft(draft)
        self._check_team_in_scope(for_user, fields["owner_team"])
        self._unique_name(fields["name"])
        sid = system_id_for(fields["name"])
        row = {
            **fields,
            "system_id": sid,
            "created_at": self.clock.now(),
            "created_by": actor,
        }
        try:
            stored = self.state.insert("ai_system", row)
        except DuplicateKeyError:
            raise SystemsError(f"AI system {fields['name']!r} already exists") from None
        self._put_member(sid, fields["owner_user"], "system_owner", actor)
        bo = fields.get("business_owner")
        if bo and bo != fields["owner_user"]:
            self._put_member(sid, bo, "business_owner", actor)
        self._changed("create", stored, actor)
        self._run_rules(sid, actor, "register")
        self._emit("system_registered", sid, {"system_type": fields["system_type"]})
        return self.get(sid)

    def _emit(self, kind: str, system_id: str, payload: Mapping[str, Any]) -> None:
        """WP-G1: one outbound_event row (ids and enums only); never stops the change."""
        from supervisor.governance import events

        events.emit(self.state, self.clock, self.settings, kind, system_id, payload)

    def _unique_name(self, name: str, except_id: str | None = None) -> None:
        low = canonical_name(name)
        for r in self.state.query("ai_system"):
            if r["system_id"] != except_id and canonical_name(str(r["name"])) == low:
                raise SystemsError(f"AI system name {name!r} is already used")

    def update_fields(
        self,
        system_id: str,
        changes: Mapping[str, Any],
        actor: str,
        expected_version: int | None = None,
        *,
        for_user: Any = None,
    ) -> dict[str, Any]:
        check_user(actor, "actor")
        cur = self._need_open(system_id)
        unknown = sorted(set(changes) - set(EDITABLE))
        if unknown:
            raise SystemsError(f"cannot change: {', '.join(unknown)}")
        if not changes:
            raise SystemsError("nothing to change")
        fields = {k: normalise_field(k, v) for k, v in changes.items()}
        if "lifecycle_stage" in fields:  # WP-G1: a stage move is its own call (approval, chain)
            if fields["lifecycle_stage"] != cur["lifecycle_stage"]:
                raise SystemsError(
                    "lifecycle_stage changes with POST /v1/systems/{id}/stage "
                    "(a stage that needs approval needs an approved stage approval)"
                )
            del fields["lifecycle_stage"]
            if not fields:
                raise SystemsError("nothing to change")
        if "tags" in fields:
            fields["tags"] = dict(fields["tags"])
        if "name" in fields:
            self._unique_name(fields["name"], system_id)
        if "owner_team" in fields and fields["owner_team"] != cur["owner_team"]:
            self._check_team_in_scope(for_user, fields["owner_team"])
        new_owner = fields.get("owner_user")
        if new_owner and new_owner != cur["owner_user"]:
            self._check_owner(system_id, new_owner)
        version = expected_version if expected_version is not None else cur["row_version"]
        try:
            stored = self.state.update("ai_system", {"system_id": system_id}, fields, int(version))
        except ConcurrencyError:
            raise SystemsError(
                "the AI system was changed by someone else; reload and retry"
            ) from None
        if new_owner and new_owner != cur["owner_user"]:
            self._put_member(system_id, new_owner, "system_owner", actor)
            self._demote_old_owner(stored, cur["owner_user"], actor)
        self._changed("update", stored, actor, {"fields_n": len(fields)})
        self._run_rules(system_id, actor, "update")
        return self.get(system_id)

    def _demote_old_owner(self, sys_row: Mapping[str, Any], old: str, actor: str) -> None:
        """After an owner change the old owner becomes a technical specialist (so the
        person can later hold another role); recorded on the chain as a team change."""
        key = {"system_id": sys_row["system_id"], "user_id": old}
        cur = self.state.get("system_team", key)
        if cur is None or not _on(cur["active"]) or cur["team_role"] != "system_owner":
            return
        self._put_member(str(sys_row["system_id"]), old, "technical_specialist", actor)
        self._changed(
            "team_add",
            sys_row,
            actor,
            {
                "member_ref": actor_ref(self.settings, old, "system"),
                "team_role": "technical_specialist",
            },
        )

    def _check_team_in_scope(self, user: Any, team: str) -> None:
        """A scoped caller may use (register with, change to) only a team in their scope."""
        if user is None or self.scope_for(user) is ALL:
            return
        if team not in self.teams_of(str(user.user_id)):
            raise SystemsError(
                "owner_team must be a team you already work in "
                "(the team of an agent you own or of a system you are owner of)"
            )

    def archive(self, system_id: str, actor: str) -> dict[str, Any]:
        check_user(actor, "actor")
        cur = self._need(system_id)
        if cur["status"] == "archived":
            raise SystemsError(f"AI system {system_id} is already archived")
        stored = self.state.update(
            "ai_system", {"system_id": system_id}, {"status": "archived"}, cur["row_version"]
        )
        self._changed("archive", stored, actor)
        self._emit("system_archived", system_id, {})
        return self.get(system_id)

    # ------------------------------------------------------------------ team
    def _check_owner(self, system_id: str, user_id: str) -> None:
        """The new owner must not be the reviewer or oversight manager of the system."""
        for m in self._team_rows(system_id):
            if m["user_id"] == user_id and m["team_role"] in SOD_ROLES:
                raise SegregationOfDuties(
                    f"segregation of duties: {user_id} is {m['team_role']} of this system "
                    "and cannot also be its owner"
                )

    def _put_member(self, system_id: str, user_id: str, role: str, actor: str) -> dict[str, Any]:
        key = {"system_id": system_id, "user_id": user_id}
        cur = self.state.get("system_team", key)
        if cur is None:
            return dict(
                self.state.insert(
                    "system_team",
                    {
                        **key,
                        "team_role": role,
                        "active": True,
                        "added_at": self.clock.now(),
                        "added_by": actor,
                    },
                )
            )
        return dict(
            self.state.update(
                "system_team",
                key,
                {
                    "team_role": role,
                    "active": True,
                    "added_at": self.clock.now(),
                    "added_by": actor,
                },
                cur["row_version"],
            )
        )

    def add_member(
        self, system_id: str, user_id: str, team_role: str, actor: str
    ) -> dict[str, Any]:
        """Add a person, or change their role. Refused when it breaks segregation of duties:
        the owner of the system cannot be reviewer or oversight manager, and a reviewer or
        oversight manager cannot become system_owner."""
        check_user(actor, "actor")
        sys_row = self._need_open(system_id)
        check_user(user_id)
        choice(team_role, TEAM_ROLES, "team_role")
        team = self._team_rows(system_id)
        cur = next((m for m in team if m["user_id"] == user_id), None)
        if cur is None and len(team) >= MAX_MEMBERS:
            raise SystemsError(f"a system can have at most {MAX_MEMBERS} team members")
        is_owner = user_id == sys_row["owner_user"] or (cur and cur["team_role"] == "system_owner")
        if team_role in SOD_ROLES and is_owner:
            raise SegregationOfDuties(
                f"segregation of duties: {user_id} owns this system and cannot be its {team_role}"
            )
        if team_role == "system_owner":
            self._check_owner(system_id, user_id)
        if user_id == sys_row["owner_user"] and team_role != "system_owner":
            raise SystemsError(
                "the owner of the system keeps the system_owner role; change the owner first"
            )
        self._put_member(system_id, user_id, team_role, actor)
        self._changed(
            "team_add",
            sys_row,
            actor,
            {"member_ref": actor_ref(self.settings, user_id, "system"), "team_role": team_role},
        )
        return self.get(system_id)

    def remove_member(self, system_id: str, user_id: str, actor: str) -> dict[str, Any]:
        check_user(actor, "actor")
        sys_row = self._need_open(system_id)
        check_user(user_id)
        if user_id == sys_row["owner_user"]:
            raise SystemsError("the owner of the system cannot be removed; change the owner first")
        cur = self.state.get("system_team", {"system_id": system_id, "user_id": user_id})
        if cur is None or not _on(cur["active"]):
            raise NotFoundError(f"{user_id} is not on the team of {system_id}")
        self.state.update(
            "system_team",
            {"system_id": system_id, "user_id": user_id},
            {"active": False},
            cur["row_version"],
        )
        self._changed(
            "team_remove",
            sys_row,
            actor,
            {
                "member_ref": actor_ref(self.settings, user_id, "system"),
                "team_role": cur["team_role"],
            },
        )
        return self.get(system_id)

    # ------------------------------------------------------------------ components
    def _resolve_ref(self, ref_kind: str, ref_id: str) -> str:
        """The stored id of a component; NotFoundError when it does not exist."""
        if ref_kind == "agent":
            for a in self.state.query("agent"):
                if str(a["agent_id"]).lower() == ref_id.lower():
                    return str(a["agent_id"])
            raise NotFoundError(f"agent {ref_id} does not exist")
        if self.state.get("inventory_node", {"node_id": ref_id}) is None:
            raise NotFoundError(f"inventory node {ref_id} does not exist")
        return ref_id

    def _check_link_scope(self, user: Any, ref_kind: str, ref: str) -> None:
        """A scoped caller links only an agent in their scope, or an inventory node that those
        agents reach. Anything else answers like a missing item, so ids cannot be probed."""
        if user is None or self.scope_for(user) is ALL:
            return
        mine = self.agents_in_scope(user)
        if ref_kind == "agent":
            if ref.lower() not in {str(a["agent_id"]).lower() for a in mine}:
                raise NotFoundError(f"agent {ref} does not exist")
            return
        g = InventoryStore(self.state, self.clock).load_graph()
        seen = {node_id_for("system", str(a["agent_id"])) for a in mine}
        todo = list(seen)
        while todo:
            cur = todo.pop()
            for e in g.edges.values():
                if e.active and e.src_id == cur and e.dst_id not in seen:
                    seen.add(e.dst_id)
                    todo.append(e.dst_id)
        if ref not in seen:
            raise NotFoundError(f"inventory node {ref} does not exist")

    def link(
        self,
        system_id: str,
        ref_kind: str,
        ref_id: str,
        actor: str,
        *,
        role: str = "component_of",
        source: str = "manual",
        evidence_ref: str = "",
        for_user: Any = None,
    ) -> dict[str, Any]:
        """Link an agent or an inventory node to the system. A repeat is a no-op; a removed
        link comes back."""
        check_user(actor, "actor")
        sys_row = self._need_open(system_id)
        choice(ref_kind, REF_KINDS, "ref_kind")
        choice(role, LINK_ROLES, "role")
        choice(source, LINK_SOURCES, "source")
        check_ref_id(ref_id)
        if not isinstance(evidence_ref, str) or len(evidence_ref) > 200:
            raise SystemsError("evidence_ref must be text of 200 characters at most")
        ref = self._resolve_ref(ref_kind, ref_id)
        self._check_link_scope(for_user, ref_kind, ref)
        cid = component_id(system_id, ref_kind, ref, role)
        cur = self.state.get("system_component", {"component_id": cid})
        now = self.clock.now()
        if cur is not None and _on(cur["active"]):
            return self.get(system_id)
        if cur is None:
            if len(self._component_rows(system_id)) >= MAX_LINKS:
                raise SystemsError(f"a system can have at most {MAX_LINKS} links")
            self.state.insert(
                "system_component",
                {
                    "component_id": cid,
                    "system_id": system_id,
                    "ref_kind": ref_kind,
                    "ref_id": ref,
                    "role": role,
                    "source": source,
                    "evidence_ref": evidence_ref,
                    "active": True,
                    "first_seen": now,
                    "last_seen": now,
                },
            )
        else:
            self.state.update(
                "system_component",
                {"component_id": cid},
                {"active": True, "last_seen": now},
                cur["row_version"],
            )
        self._changed(
            "link", sys_row, actor, {"component_id": cid, "ref_kind": ref_kind, "role": role}
        )
        self._run_rules(system_id, actor, "link")
        return self.get(system_id)

    def unlink(self, system_id: str, component: str, actor: str) -> dict[str, Any]:
        check_user(actor, "actor")
        sys_row = self._need_open(system_id)
        cur = self.state.get("system_component", {"component_id": component})
        if cur is None or cur["system_id"] != system_id or not _on(cur["active"]):
            raise NotFoundError(f"link {component} is not on {system_id}")
        self.state.update(
            "system_component",
            {"component_id": component},
            {"active": False, "last_seen": self.clock.now()},
            cur["row_version"],
        )
        self._changed(
            "unlink",
            sys_row,
            actor,
            {"component_id": component, "ref_kind": cur["ref_kind"], "role": cur["role"]},
        )
        self._run_rules(system_id, actor, "unlink")
        return self.get(system_id)

    # ------------------------------------------------------------------ risk
    def _inventory_levels(self) -> tuple[dict[str, str | None], dict[str, str]]:
        """(effective level by inventory node id, agent id (lower) -> risk_tier fallback)."""
        g = InventoryStore(self.state, self.clock).load_graph()
        eff = g.effective_risk()
        gone = {nid for nid, n in g.nodes.items() if n.status == "gone"}
        levels = {nid: lv for nid, lv in eff.items() if nid not in gone}
        tiers = {
            str(a["agent_id"]).lower(): str(a.get("risk_tier") or "")
            for a in self.state.query("agent")
        }
        return levels, tiers

    def _inherited(
        self,
        components: Iterable[Mapping[str, Any]],
        levels: Mapping[str, str | None],
        tiers: Mapping[str, str],
    ) -> tuple[str, tuple[dict[str, str], ...]]:
        best = "unspecified"
        via: list[dict[str, str]] = []
        for c in components:
            if c["ref_kind"] == "agent":
                raw = levels.get(node_id_for("system", str(c["ref_id"])))
                if raw is None:  # not in the inventory (off or not filled): the registered tier
                    raw = tiers.get(str(c["ref_id"]).lower()) or None
            else:
                raw = levels.get(str(c["ref_id"]))
            lv = INVENTORY_TO_SYSTEM.get(raw or "")
            if lv is None:
                continue
            via.append({"ref_kind": str(c["ref_kind"]), "ref_id": str(c["ref_id"]), "level": lv})
            best = max_level(best, lv)
        return best, tuple(sorted(via, key=lambda v: (v["ref_kind"], v["ref_id"])))

    def _effective(
        self,
        row: Mapping[str, Any],
        components: list[dict[str, Any]],
        levels: Mapping[str, str | None],
        tiers: Mapping[str, str],
    ) -> EffectiveRisk:
        manual = str(row["risk_level"])
        inherited, via = self._inherited(components, levels, tiers)
        # WP-G2: the classifier floor. A system classed high risk under Decision 33 is at least
        # "high", whatever a person typed in the manual level.
        floor = "high" if row.get("decision33_class") == "high_risk" else "unspecified"
        if row.get("autonomy_level") == "l5_self_directed":  # prohibited at the bank by default
            floor = "prohibited"
        if rank(floor) > max(rank(manual), rank(inherited)):
            level, source = floor, "classifier"
        elif rank(inherited) > rank(manual):
            level, source = inherited, "inherited"
        else:
            level, source = manual, str(row["risk_level_source"])
            if source == "inherited":  # an old value; the inherited level did not win now
                source = "manual"
        return EffectiveRisk(str(row["system_id"]), level, source, manual, inherited, via)

    def effective_risk_level(self, system_id: str) -> EffectiveRisk:
        """Maximum of the manual level and the level inherited over the linked agents and
        inventory nodes. Computed on read, never stored. ``source`` says which won."""
        row = self._need(system_id)
        levels, tiers = self._inventory_levels()
        return self._effective(row, self._component_rows(system_id), levels, tiers)

    # ------------------------------------------------------------------ scope
    def teams_of(self, user_id: str) -> frozenset[str]:
        """Teams a person works in: the owner team of the agents they own, and of the systems
        where they are an active system_owner (a role somebody with edit rights gave them).
        Systems a person registered do not widen this: registering needs a team already here.
        (The principal carries no team; see docs/governance.md, open question 1.)"""
        teams: set[str] = set()
        for a in self.state.query("agent", {"owner_user": user_id}):
            if a.get("owner_team"):
                teams.add(str(a["owner_team"]))
        for m in self.state.query("system_team", {"user_id": user_id}):
            if _on(m["active"]) and m["team_role"] == "system_owner":
                s = self.state.get("ai_system", {"system_id": m["system_id"]})
                if s is not None:
                    teams.add(str(s["owner_team"]))
        return frozenset(teams)

    def scope_for(self, user: Any) -> Scope:
        """Systems a person sees: ``ALL`` for admin, auditor, reviewer and approver; for the
        SCOPED_ROLES the systems they are on, own, or that their team owns. A person with no
        role sees nothing. ``user`` needs ``user_id`` and ``roles``."""
        roles = frozenset(getattr(user, "roles", ()) or ())
        if roles & ALL_ROLES:
            return ALL
        if not roles & SCOPED_ROLES:
            return frozenset()
        uid = str(user.user_id)
        ids: set[str] = {
            str(m["system_id"])
            for m in self.state.query("system_team", {"user_id": uid})
            if _on(m["active"])
        }
        ids |= {str(s["system_id"]) for s in self.state.query("ai_system", {"owner_user": uid})}
        teams = self.teams_of(uid)
        if teams:
            ids |= {
                str(s["system_id"])
                for s in self.state.query("ai_system")
                if str(s["owner_team"]) in teams
            }
        return frozenset(ids)

    def can_view(self, user: Any, system_id: str) -> bool:
        return system_id in self.scope_for(user)

    def agents_in_scope(self, user: Any) -> list[dict[str, Any]]:
        """Agents a person works with: those linked to a system in scope, plus unlinked agents
        whose owner team is the person's team. ALL roles get every agent."""
        agents = [dict(a) for a in self.state.query("agent", order_by=("agent_id",))]
        scope = self.scope_for(user)
        if scope is ALL:
            return agents
        linked: dict[str, set[str]] = {}
        for c in self.state.query("system_component", {"ref_kind": "agent"}):
            if _on(c["active"]):
                linked.setdefault(str(c["ref_id"]).lower(), set()).add(str(c["system_id"]))
        teams = self.teams_of(str(user.user_id))
        out = []
        for a in agents:
            systems = linked.get(str(a["agent_id"]).lower())
            if systems:
                if systems & scope:  # type: ignore[operator]
                    out.append(a)
            elif str(a.get("owner_team") or "") in teams:
                out.append(a)
        return out

    # ------------------------------------------------------------------ reads
    def list_systems(
        self, scope: Scope = ALL, filters: Mapping[str, str] | None = None
    ) -> list[dict[str, Any]]:
        f = dict(filters or {})
        unknown = sorted(set(f) - set(FILTERS))
        if unknown:
            raise SystemsError(f"unknown filter: {', '.join(unknown)}")
        if f.get("status") and f["status"] not in STATUSES:
            raise SystemsError(f"status must be one of {', '.join(STATUSES)}")
        if f.get("lifecycle_stage") and f["lifecycle_stage"] not in LIFECYCLE_STAGES:
            raise SystemsError(f"lifecycle_stage must be one of {', '.join(LIFECYCLE_STAGES)}")
        if f.get("risk"):
            choice(f["risk"], RISK_LEVELS, "risk")
        if f.get("system_type"):
            choice(f["system_type"], SYSTEM_TYPES, "system_type")
        levels, tiers = self._inventory_levels()
        comps: dict[str, list[dict[str, Any]]] = {}
        for c in self.state.query("system_component"):
            if _on(c["active"]):
                comps.setdefault(str(c["system_id"]), []).append(dict(c))
        members: dict[str, int] = {}
        for m in self.state.query("system_team"):
            if _on(m["active"]):
                members[str(m["system_id"])] = members.get(str(m["system_id"]), 0) + 1
        out = []
        for row in self.state.query("ai_system", order_by=("name",)):
            sid = str(row["system_id"])
            if sid not in scope:
                continue
            item = self._view(row)
            eff = self._effective(row, comps.get(sid, []), levels, tiers)
            item["effective_risk_level"] = eff.level
            item["effective_risk_source"] = eff.source
            item["components_n"] = len(comps.get(sid, []))
            item["team_n"] = members.get(sid, 0)
            if _fits(item, f):
                out.append(item)
        return out

    def get(self, system_id: str) -> dict[str, Any]:
        row = self._need(system_id)
        item = self._view(row)
        item["team"] = [
            {k: m[k] for k in ("user_id", "team_role", "added_at", "added_by")}
            for m in self._team_rows(system_id)
        ]
        item["components"] = [
            {
                k: c[k]
                for k in ("component_id", "ref_kind", "ref_id", "role", "source", "evidence_ref")
            }
            for c in self._component_rows(system_id)
        ]
        item["effective_risk"] = self.effective_risk_level(system_id).as_dict()
        return _plain(item)  # type: ignore[no-any-return]


def _fits(item: Mapping[str, Any], f: Mapping[str, str]) -> bool:
    if f.get("status") and item["status"] != f["status"]:
        return False
    if f.get("owner_team") and item["owner_team"] != f["owner_team"]:
        return False
    if f.get("lifecycle_stage") and item["lifecycle_stage"] != f["lifecycle_stage"]:
        return False
    if f.get("system_type") and item["system_type"] != f["system_type"]:
        return False
    if f.get("risk") and item["effective_risk_level"] != f["risk"]:
        return False
    if f.get("q"):
        hay = f"{item['system_id']} {item['name']} {item['owner_team']}".lower()
        if f["q"].lower() not in hay:
            return False
    return True
