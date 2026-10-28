"""The agent factory store (WP-F2, flag ``AGENT_FACTORY``): ``factory_agent`` and
``factory_agent_event``.

Public API (the orchestrator, WP-F4, reads ``live_agent_for`` and ``portfolio``; see
``docs/factory.md`` "Catalogue"):

* ``FactoryStore(state, tables, clock, tools=None, groups=None)``
* ``create_from_template(dimension_id, agent_id, name, actor) -> row``
* ``save_draft(agent_id, version, definition, actor, expected_version) -> row``
* ``new_version(agent_id, from_version, actor) -> row``
* ``retire(agent_id, version, actor, reason) -> row``
* ``get(agent_id, version=None) -> row | None`` (``None`` = the newest version)
* ``versions(agent_id) -> list[row]``, ``list_agents(...) -> list[row]`` (newest version of each)
* ``events(agent_id, version=None) -> list[row]``, ``record_event(...)``
* ``live_agent_for(dimension_id) -> row | None``, ``portfolio() -> list[dict]``
* ``validate_definition(raw, tools, groups) -> AgentDefinitionV1`` (module function)
* ``permits(roles, owner_group, groups) -> bool`` (module function; who may edit a group's agents)

A row has the table columns plus ``definition`` (the parsed ``definition_json``). Every save
validates the definition with ``agent_definition_v1`` and the registry. The state changes only
through ``TRANSITIONS``: in WP-F2 a draft can be retired and nothing else; ``tested``,
``approved`` and ``live`` belong to WP-F3, which extends the table. A version that is not a draft
is never edited. No personal data and no float is stored; the event detail is masked.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import ValidationError

from supervisor.core.errors import ConcurrencyError, SupervisorError
from supervisor.core.ports import Clock, StateStore, TableStore
from supervisor.factory import caps, registry
from supervisor.factory.schemas.agent_definition_v1 import AgentDefinitionV1
from supervisor.factory.templates import build_definition, load_template
from supervisor.onboard.agent_log import clean

AGENT_TABLE = "factory_agent"
EVENT_TABLE = "factory_agent_event"
EVENT_KINDS = (
    "created",
    "saved",
    "new_version",
    "retired",
    "helper_accepted",
    "helper_dropped",
    "golden_uploaded",
)
MAX_DETAIL = 300
FLAG_TEXT = "the agent factory is off (AGENT_FACTORY=1 turns it on; needs GOVERNANCE_ENABLED)"

# The lifecycle rules of this WP: from state -> states it may move to. WP-F3 adds tested,
# approved and live here (with the gate and the approvals); nothing else changes a state.
TRANSITIONS: dict[str, tuple[str, ...]] = {"draft": ("retired",), "retired": ()}


class FactoryError(SupervisorError):
    """A refused request. ``code`` is the stable machine word; the message starts with it."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code


def enabled(settings: Any) -> bool:
    return bool(
        getattr(settings, "agent_factory", False) and getattr(settings, "governance_enabled", False)
    )


def require_on(settings: Any) -> None:
    if not enabled(settings):
        raise FactoryError("agent_factory_off", FLAG_TEXT)


# ------------------------------------------------------------------------------ validation


def _loc(parts: tuple[Any, ...]) -> str:
    out = ""
    for p in parts:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out


def validation_errors(exc: ValidationError) -> list[tuple[str, str]]:
    out = []
    for e in exc.errors(include_url=False, include_input=False):
        msg = str(e["msg"]).removeprefix("Value error, ")
        out.append((_loc(tuple(e["loc"])) or "definition", msg))
    return out


def validate_definition(
    raw: Mapping[str, Any], tools: registry.ToolRegistry, groups: registry.GroupRegistry
) -> AgentDefinitionV1:
    """The one validation of the factory: the schema, then the registry. A failure is a
    ``FactoryError`` ``invalid_definition`` whose text lists ``field: message`` pairs."""
    try:
        model = AgentDefinitionV1.model_validate(raw)
    except ValidationError as exc:
        pairs = validation_errors(exc)
        raise FactoryError(
            "invalid_definition", "; ".join(f"{f}: {m}" for f, m in pairs[:6])
        ) from None
    found = registry.check_definition(model, tools, groups)
    if found:
        raise FactoryError("invalid_definition", "; ".join(f"{f}: {m}" for f, m in found[:6]))
    return model


def permits(roles: Iterable[str], owner_group: str, groups: registry.GroupRegistry) -> bool:
    """Who may edit the agents of a group: ``admin`` edits all; any other role must be one of
    the roles the group lists in ``config/factory_groups.yaml``."""
    held = set(roles)
    if "admin" in held:
        return True
    group = groups.get(owner_group)
    return group is not None and bool(held & set(group.roles))


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return default if value is None else value


# ------------------------------------------------------------------------------ the store


class FactoryStore:
    def __init__(
        self,
        state: StateStore,
        tables: TableStore,
        clock: Clock,
        tools: registry.ToolRegistry | None = None,
        groups: registry.GroupRegistry | None = None,
    ) -> None:
        self.state = state
        self.tables = tables
        self.clock = clock
        self.tools = tools or registry.load_tools()
        self.groups = groups or registry.load_groups()

    # ------------------------------------------------------------------ rows
    @staticmethod
    def _row(raw: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        row["definition"] = dict(_json(row.get("definition_json"), {}))
        return row

    def versions(self, agent_id: str) -> list[dict[str, Any]]:
        rows = [self._row(r) for r in self.state.query(AGENT_TABLE, {"id": agent_id})]
        return sorted(rows, key=lambda r: _version_key(r["version"]))

    def get(self, agent_id: str, version: str | None = None) -> dict[str, Any] | None:
        if version is not None:
            raw = self.state.get(AGENT_TABLE, {"id": agent_id, "version": version})
            return self._row(raw) if raw is not None else None
        rows = self.versions(agent_id)
        return rows[-1] if rows else None

    def list_agents(
        self,
        *,
        owner_group: str | None = None,
        dimension_id: str | None = None,
        state: str | None = None,
    ) -> list[dict[str, Any]]:
        """The newest version of every agent, ordered by dimension then id."""
        where: dict[str, Any] = {}
        if owner_group:
            where["owner_group"] = owner_group
        if dimension_id:
            where["dimension_id"] = dimension_id
        newest: dict[str, dict[str, Any]] = {}
        for raw in self.state.query(AGENT_TABLE, where):
            row = self._row(raw)
            cur = newest.get(row["id"])
            if cur is None or _version_key(row["version"]) > _version_key(cur["version"]):
                newest[row["id"]] = row
        rows = [r for r in newest.values() if state is None or r["state"] == state]
        order = {d: i for i, d in enumerate(caps.DIMENSIONS)}
        return sorted(rows, key=lambda r: (order.get(r["dimension_id"], 99), r["id"]))

    def events(
        self, agent_id: str, version: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {"agent_id": agent_id}
        if version is not None:
            where["version"] = version
        rows = self.tables.query(EVENT_TABLE, where, order_by=("created_at", "event_id"))
        out = [dict(r) for r in rows]
        return out[-limit:] if limit else out

    # ------------------------------------------------------------------ events
    def record_event(
        self, agent_id: str, version: str, kind: str, actor_ref: str, detail: str
    ) -> dict[str, Any]:
        if kind not in EVENT_KINDS:
            raise FactoryError("bad_event", f"kind {kind!r} is not one of {', '.join(EVENT_KINDS)}")
        row = {
            "event_id": uuid.uuid4().hex,
            "agent_id": agent_id,
            "version": version,
            "kind": kind,
            "actor_ref": str(actor_ref)[:120],
            "detail": clean(detail, MAX_DETAIL),
            "created_at": self.clock.now(),
        }
        self.tables.append(EVENT_TABLE, [row])
        return row

    # ------------------------------------------------------------------ create and save
    def create_from_template(
        self, dimension_id: str, agent_id: str, name: str, actor: str
    ) -> dict[str, Any]:
        if not caps.ID_RE.match(agent_id or ""):
            raise FactoryError(
                "invalid_definition", "id: lowercase letters, digits and hyphen, at most 64"
            )
        if self.versions(agent_id):
            raise FactoryError("exists", f"an agent with the id {agent_id} already exists")
        owner = self.groups.owner_of(dimension_id)
        if owner is None:
            raise FactoryError("invalid_definition", f"dimension_id: no group owns {dimension_id}")
        template = load_template(dimension_id)
        raw = build_definition(template, agent_id=agent_id, name=(name or "").strip() or None)
        raw["owner_group"] = owner.group_id
        model = validate_definition(raw, self.tools, self.groups)
        doc = model.model_dump(mode="json")
        row = self.state.insert(
            AGENT_TABLE,
            {
                "id": agent_id,
                "version": doc["lifecycle"]["version"],
                "owner_group": doc["owner_group"],
                "dimension_id": doc["dimension_id"],
                "definition_json": doc,
                "state": "draft",
                "created_by": actor,
            },
        )
        self.record_event(
            agent_id, doc["lifecycle"]["version"], "created", actor, f"from template {dimension_id}"
        )
        return self._row(row)

    def save_draft(
        self,
        agent_id: str,
        version: str,
        definition: Mapping[str, Any],
        actor: str,
        expected_version: int,
    ) -> dict[str, Any]:
        row = self.get(agent_id, version)
        if row is None:
            raise FactoryError("not_found", f"agent {agent_id} version {version} does not exist")
        if row["state"] != "draft":
            raise FactoryError(
                "not_draft", f"version {version} is {row['state']}; make a new version to change it"
            )
        raw = json.loads(json.dumps(definition))  # a private copy
        for key in ("id", "owner_group", "dimension_id"):
            if raw.get(key) != row[key]:
                raise FactoryError("invalid_definition", f"{key}: cannot be changed after creation")
        lifecycle = raw.get("lifecycle")
        if not isinstance(lifecycle, dict) or lifecycle.get("version") != version:
            raise FactoryError("invalid_definition", f"lifecycle.version: must stay {version}")
        raw["lifecycle"] = {"state": "draft", "version": version, "approvals": []}
        model = validate_definition(raw, self.tools, self.groups)
        doc = model.model_dump(mode="json")
        try:
            updated = self.state.update(
                AGENT_TABLE,
                {"id": agent_id, "version": version},
                {"definition_json": doc},
                expected_version,
            )
        except ConcurrencyError:
            raise FactoryError(
                "stale", "the agent was changed in another window; reload the page"
            ) from None
        changed = sorted(k for k in doc if doc.get(k) != row["definition"].get(k))
        self.record_event(
            agent_id, version, "saved", actor, "changed: " + ", ".join(changed or ["nothing"])
        )
        return self._row(updated)

    def new_version(self, agent_id: str, from_version: str, actor: str) -> dict[str, Any]:
        rows = self.versions(agent_id)
        src = next((r for r in rows if r["version"] == from_version), None)
        if src is None:
            raise FactoryError(
                "not_found", f"agent {agent_id} version {from_version} does not exist"
            )
        if any(r["state"] == "draft" for r in rows):
            raise FactoryError(
                "draft_open", "this agent already has a draft version; edit that one"
            )
        top = _version_key(rows[-1]["version"])
        version = f"{top[0]}.{(top[1] if len(top) > 1 else 0) + 1}"
        raw = json.loads(json.dumps(src["definition"]))
        raw["lifecycle"] = {"state": "draft", "version": version, "approvals": []}
        model = validate_definition(raw, self.tools, self.groups)
        row = self.state.insert(
            AGENT_TABLE,
            {
                "id": agent_id,
                "version": version,
                "owner_group": src["owner_group"],
                "dimension_id": src["dimension_id"],
                "definition_json": model.model_dump(mode="json"),
                "state": "draft",
                "created_by": actor,
            },
        )
        self.record_event(agent_id, version, "new_version", actor, f"copied from {from_version}")
        return self._row(row)

    def retire(self, agent_id: str, version: str, actor: str, reason: str) -> dict[str, Any]:
        row = self.get(agent_id, version)
        if row is None:
            raise FactoryError("not_found", f"agent {agent_id} version {version} does not exist")
        reason = (reason or "").strip()
        if not reason:
            raise FactoryError("reason_needed", "retiring an agent needs a reason")
        return self._move(row, "retired", actor, "retired", clean(reason, 200))

    def _move(
        self, row: Mapping[str, Any], to: str, actor: str, kind: str, detail: str
    ) -> dict[str, Any]:
        """The only place the state of a version changes."""
        if to not in TRANSITIONS.get(row["state"], ()):
            raise FactoryError("bad_transition", f"a {row['state']} agent cannot become {to}")
        doc = json.loads(json.dumps(row["definition"]))
        doc["lifecycle"]["state"] = to
        try:
            updated = self.state.update(
                AGENT_TABLE,
                {"id": row["id"], "version": row["version"]},
                {"state": to, "definition_json": doc},
                int(row["row_version"]),
            )
        except ConcurrencyError:
            raise FactoryError(
                "stale", "the agent was changed in another window; reload the page"
            ) from None
        self.record_event(row["id"], row["version"], kind, actor, detail)
        return self._row(updated)

    # ------------------------------------------------------------------ for the orchestrator
    def live_agent_for(self, dimension_id: str) -> dict[str, Any] | None:
        """The newest ``live`` version for a dimension, or ``None`` (the orchestrator then uses
        the rule proposal of WP-C2). WP-F2 never sets ``live``; WP-F3 does."""
        rows = [
            self._row(r)
            for r in self.state.query(AGENT_TABLE, {"dimension_id": dimension_id, "state": "live"})
        ]
        rows.sort(key=lambda r: _version_key(r["version"]))
        return rows[-1] if rows else None

    def portfolio(self) -> list[dict[str, Any]]:
        """One entry per dimension: a live agent, or a rule proposal."""
        out = []
        for dim in caps.DIMENSIONS:
            live = self.live_agent_for(dim)
            owner = self.groups.owner_of(dim)
            out.append(
                {
                    "dimension_id": dim,
                    "owner_group": owner.group_id if owner else "",
                    "kind": "live_agent" if live else "rule_proposal",
                    "agent_id": live["id"] if live else None,
                    "version": live["version"] if live else None,
                }
            )
        return out
