"""The guardian definition store (WP-G1): create, save, new version, list, get, retire.

One ``guardian_def`` row per version; ``guardian_def_event`` is the append-only history. Only a
draft is edited in place; any other change is a new version. In WP-G1 the only state changes are
draft -> retired and retired -> draft (``caps.ALLOWED_NOW``); the later states belong to WP-G2
and WP-G3 and are refused here with a message that says so.

Every save and state change writes a ``guardian_def`` chain record: ids, enums, integers and the
SHA-256 of the canonical definition. The rule text, the keywords and the prompt are not in it.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from typing import Any

from supervisor.controls.model import actor_ref
from supervisor.core import rbac
from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import ConcurrencyError, NotFoundError
from supervisor.guardian_factory import bench, caps
from supervisor.guardian_factory.definition import (
    GuardianDefinition,
    GuardianFactoryError,
    validate_definition,
)

log = logging.getLogger("supervisor.guardian_factory")

TABLE = "guardian_def"
EVENTS = "guardian_def_event"
OFF_MESSAGE = "the guardian factory is off (GUARDIAN_FACTORY=1 and DETECTORS_ENABLED=1 turn it on)"
LATER_STATES = "the states shadow, approved and live come with WP-G3"
EDITABLE = ("draft", "benchmarked")  # a change of a benchmarked version sends it back to draft


def enabled(settings: Any) -> bool:
    return bool(getattr(settings, "guardian_factory", False)) and bool(
        getattr(settings, "detectors_enabled", False)
    )


def require_on(settings: Any) -> None:
    """HTTP 400 ``guardian_factory_off`` unless the flag and DETECTORS_ENABLED are on."""
    if not enabled(settings):
        raise GuardianFactoryError("guardian_factory_off", OFF_MESSAGE)


def check_transition(from_state: str, to_state: str) -> None:
    """Raises unless ``from_state -> to_state`` is in the table and allowed in this work package."""
    if to_state not in caps.TRANSITIONS.get(from_state, ()):
        raise GuardianFactoryError(
            "bad_transition", f"a guardian in state {from_state} cannot go to {to_state}"
        )
    if (from_state, to_state) not in caps.ALLOWED_NOW:
        raise GuardianFactoryError(
            "transition_not_yet_allowed",
            f"{from_state} -> {to_state} is not allowed yet: {LATER_STATES}",
        )


def can_edit(user: Any, owner_group: str) -> bool:
    """A member of the owner group edits its guardians (a role listed for the group in
    config/factory_groups.yaml); an admin edits all."""
    roles = frozenset(getattr(user, "roles", ()) or ())
    if "admin" in roles:
        return True
    from supervisor.factory.registry import load_groups

    grp = load_groups().get(owner_group)
    return bool(grp and roles & set(grp.roles))


def _stamp(value: Any) -> str:
    return value if isinstance(value, str) else format_ts(value)


class GuardianDefStore:
    def __init__(
        self, state: Any, tables: Any, clock: Any, settings: Any, *, evidence: Any = None
    ) -> None:
        self.state = state
        self.tables = tables
        self.clock = clock
        self.settings = settings
        self.evidence_sink = evidence

    # ------------------------------------------------------------------ plumbing
    def _actor(self, user: Any) -> str:
        uid = str(getattr(user, "user_id", "") or "")
        if not uid or getattr(user, "kind", "user") != "user":
            raise GuardianFactoryError("person_required", "this step needs a signed-in person")
        return uid[: caps.USER_MAX]

    def _perm(self, user: Any) -> str:
        actor = self._actor(user)
        if not rbac.allowed(frozenset(getattr(user, "roles", ()) or ()), "guardians.edit"):
            from supervisor.cases.service import PermissionDenied

            raise PermissionDenied("editing a guardian definition needs guardians.edit")
        return actor

    def _group(self, user: Any, owner_group: str) -> None:
        if not can_edit(user, owner_group):
            from supervisor.cases.service import PermissionDenied

            raise PermissionDenied(
                f"only members of the group {owner_group} (or an admin) edit its guardians"
            )

    def _need(self, user: Any, owner_group: str) -> str:
        actor = self._perm(user)
        self._group(user, owner_group)
        return actor

    def _rows(self, def_id: str) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self.state.query(TABLE, {"def_id": def_id})]
        rows.sort(key=lambda r: int(r["version"]))
        return rows

    def _latest(self, def_id: str) -> dict[str, Any]:
        rows = self._rows(def_id)
        if not rows:
            raise NotFoundError(f"guardian definition {def_id} does not exist")
        return rows[-1]

    def _event(
        self, row: Mapping[str, Any], action: str, from_state: str | None, actor: str
    ) -> None:
        sha = sha256_hex(self._body(row))
        try:
            self.tables.append(
                EVENTS,
                [
                    {
                        "event_id": "gde_" + uuid.uuid4().hex[:24],
                        "def_id": row["def_id"],
                        "version": int(row["version"]),
                        "action": action,
                        "from_state": from_state,
                        "to_state": row["state"],
                        "actor": actor,
                        "def_sha256": sha,
                        "at": self.clock.now(),
                    }
                ],
            )
        except Exception:  # noqa: BLE001 - the row is stored; log and go on
            log.exception("guardian_def_event not written")
        if self.evidence_sink is None:
            return
        try:
            self.evidence_sink.record(
                "guardian_def",
                f"guardian:{row['def_id']}",
                {
                    "def_id": row["def_id"],
                    "version": int(row["version"]),
                    "action": action,
                    "from_state": from_state,
                    "to_state": row["state"],
                    "type": row["type"],
                    "stage": row["stage"],
                    "owner_group": row["owner_group"],
                    "def_sha256": sha,
                    "actor_ref": actor_ref(self.settings, actor, "system"),
                    "ts": format_ts(self.clock.now()),
                },
            )
        except Exception:  # noqa: BLE001
            log.exception("guardian_def chain record failed")

    @staticmethod
    def _body(row: Mapping[str, Any]) -> Any:
        raw = row.get("definition_json")
        return raw if isinstance(raw, dict) else json.loads(raw or "{}")

    def view(self, row: Mapping[str, Any]) -> dict[str, Any]:
        body = dict(self._body(row))
        return {
            "id": row["def_id"],
            "version": int(row["version"]),
            "state": row["state"],
            "owner_group": row["owner_group"],
            "type": row["type"],
            "stage": row["stage"],
            "name": body.get("name", ""),
            "created_by": row["created_by"],
            "updated_at": _stamp(row["updated_at"]) if row.get("updated_at") else None,
            "row_version": int(row.get("row_version") or 1),
            "definition": body,
        }

    def _prepare(
        self,
        data: Mapping[str, Any],
        actor: str,
        *,
        state: str,
        version: int,
        created_by: str,
        approvals: list[Any] | None = None,
    ) -> tuple[GuardianDefinition, dict[str, Any]]:
        now = format_ts(self.clock.now())
        raw = dict(data)
        raw["created_by"] = created_by
        raw["created_at"] = raw.get("created_at") or now
        raw["updated_at"] = now
        life = dict(raw.get("lifecycle") or {})
        life["state"], life["version"] = state, version
        life["approvals"] = list(approvals or [])
        raw["lifecycle"] = life
        d = validate_definition(raw)
        return d, d.model_dump(mode="json")

    def _row(self, d: GuardianDefinition, body: dict[str, Any]) -> dict[str, Any]:
        return {
            "def_id": d.id,
            "version": d.lifecycle.version,
            "owner_group": d.owner_group,
            "type": d.type,
            "stage": d.stage,
            "definition_json": json.dumps(body, sort_keys=True, ensure_ascii=False),
            "state": d.lifecycle.state,
            "created_by": d.created_by,
        }

    # ------------------------------------------------------------------ writes
    def create(self, data: Mapping[str, Any], user: Any) -> dict[str, Any]:
        """A new draft, version 1. State, version and creator are set here, not by the caller."""
        require_on(self.settings)
        actor = self._perm(user)
        d, body = self._prepare(data, actor, state="draft", version=1, created_by=actor)
        self._group(user, d.owner_group)
        if self._rows(d.id):
            raise GuardianFactoryError("duplicate_id", f"a guardian with id {d.id} exists")
        stored = dict(self.state.insert(TABLE, self._row(d, body)))
        self._event(stored, "created", None, actor)
        return self.view(stored)

    def save(self, def_id: str, data: Mapping[str, Any], user: Any) -> dict[str, Any]:
        """Replace the newest version in place. Only a draft is saved in place."""
        require_on(self.settings)
        row = self._latest(def_id)
        actor = self._need(user, str(row["owner_group"]))
        if row["state"] not in EDITABLE:
            raise GuardianFactoryError(
                "not_draft",
                f"version {row['version']} is {row['state']}; make a new version to change it",
            )
        if data.get("id", def_id) != def_id:
            raise GuardianFactoryError(
                "invalid_definition", "id: cannot change; make a new guardian"
            )
        if data.get("owner_group", row["owner_group"]) != row["owner_group"]:
            self._need(user, str(data.get("owner_group")))
        body_in = {**dict(data), "id": def_id}
        old = self._body(row)
        d, body = self._prepare(
            body_in,
            actor,
            state="draft",
            version=int(row["version"]),
            created_by=str(row["created_by"]),
            approvals=old.get("lifecycle", {}).get("approvals", []),
        )
        body["created_at"] = old.get("created_at") or body["created_at"]
        was, action = str(row["state"]), "saved"
        if was == "benchmarked":
            if bench.def_sha(body) == bench.def_sha(old):
                d, body = self._prepare(
                    body_in,
                    actor,
                    state="benchmarked",
                    version=int(row["version"]),
                    created_by=str(row["created_by"]),
                    approvals=old.get("lifecycle", {}).get("approvals", []),
                )
                body["created_at"] = old.get("created_at") or body["created_at"]
            else:
                action = "reset_to_draft"  # WP-G2: the benchmark no longer fits this definition
        try:
            stored = dict(
                self.state.update(
                    TABLE,
                    {"def_id": def_id, "version": row["version"]},
                    {k: v for k, v in self._row(d, body).items() if k not in ("def_id", "version")},
                    row["row_version"],
                )
            )
        except ConcurrencyError:
            raise GuardianFactoryError("conflict", "the definition changed; reload it") from None
        self._event(stored, action, was, actor)
        return self.view(stored)

    def new_version(self, def_id: str, user: Any) -> dict[str, Any]:
        """Copy the newest version into version + 1 as a draft (it must not already be one)."""
        require_on(self.settings)
        row = self._latest(def_id)
        actor = self._need(user, str(row["owner_group"]))
        if row["state"] == "draft":
            raise GuardianFactoryError("draft_exists", f"version {row['version']} is still a draft")
        old = self._body(row)
        nxt = int(row["version"]) + 1
        d, body = self._prepare(
            old, actor, state="draft", version=nxt, created_by=str(row["created_by"])
        )
        stored = dict(self.state.insert(TABLE, self._row(d, body)))
        self._event(stored, "new_version", str(row["state"]), actor)
        return self.view(stored)

    def _move(self, def_id: str, to_state: str, action: str, user: Any) -> dict[str, Any]:
        require_on(self.settings)
        row = self._latest(def_id)
        actor = self._need(user, str(row["owner_group"]))
        check_transition(str(row["state"]), to_state)
        body = dict(self._body(row))
        body["lifecycle"] = {**body.get("lifecycle", {}), "state": to_state}
        body["updated_at"] = format_ts(self.clock.now())
        try:
            stored = dict(
                self.state.update(
                    TABLE,
                    {"def_id": def_id, "version": row["version"]},
                    {
                        "state": to_state,
                        "definition_json": json.dumps(body, sort_keys=True, ensure_ascii=False),
                    },
                    row["row_version"],
                )
            )
        except ConcurrencyError:
            raise GuardianFactoryError("conflict", "the definition changed; reload it") from None
        self._event(stored, action, str(row["state"]), actor)
        return self.view(stored)

    def bench_problem(self, row: Mapping[str, Any]) -> str:
        """Why this version cannot be marked benchmarked, or an empty string when the newest run
        of this version passed for this exact definition and the pack it names (WP-G2)."""
        body = self._body(row)
        run = bench.newest_run(self.state, str(row["def_id"]), int(row["version"]))
        if run is None:
            return "there is no benchmark run of this version"
        if run["status"] != "done":
            return f"the newest run is {run['status']}"
        if run["gate"] != "pass":
            return f"the newest run did not pass ({run['failing_threshold'] or run['gate']})"
        if run["def_sha256"] != bench.def_sha(body):
            return "the definition changed after the newest run; run the benchmark again"
        if run["pack_id"] != (body.get("benchmark_pack") or ""):
            return "the newest run used another pack than benchmark_pack of the definition"
        return ""

    def mark_benchmarked(self, def_id: str, user: Any) -> dict[str, Any]:
        """draft -> benchmarked, only when the newest benchmark run of this version passed for
        this exact definition (same hash) and the pack the definition names (WP-G2)."""
        require_on(self.settings)
        row = self._latest(def_id)
        self._need(user, str(row["owner_group"]))
        check_transition(str(row["state"]), "benchmarked")
        why = self.bench_problem(row)
        if why:
            raise GuardianFactoryError("no_passing_run", why)
        return self._move(def_id, "benchmarked", "benchmarked", user)

    def retire(self, def_id: str, user: Any) -> dict[str, Any]:
        return self._move(def_id, "retired", "retired", user)

    def reopen(self, def_id: str, user: Any) -> dict[str, Any]:
        return self._move(def_id, "draft", "reopened", user)

    # ------------------------------------------------------------------ reads
    def get(self, def_id: str, version: int | None = None) -> dict[str, Any]:
        require_on(self.settings)
        rows = self._rows(def_id)
        if not rows:
            raise NotFoundError(f"guardian definition {def_id} does not exist")
        if version is None:
            return {**self.view(rows[-1]), "versions": [int(r["version"]) for r in rows]}
        for r in rows:
            if int(r["version"]) == version:
                return {**self.view(r), "versions": [int(x["version"]) for x in rows]}
        raise NotFoundError(f"guardian definition {def_id} has no version {version}")

    def list_defs(self, filters: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        """The newest version of each guardian, filtered by state, owner_group, stage, type."""
        require_on(self.settings)
        f = {k: v for k, v in (filters or {}).items() if v}
        bad = sorted(set(f) - {"state", "owner_group", "stage", "type"})
        if bad:
            raise GuardianFactoryError("bad_filter", f"unknown filter: {', '.join(bad)}")
        latest: dict[str, dict[str, Any]] = {}
        for r in self.state.query(TABLE, {}):
            cur = latest.get(str(r["def_id"]))
            if cur is None or int(r["version"]) > int(cur["version"]):
                latest[str(r["def_id"])] = dict(r)
        out = [self.view(r) for r in latest.values() if all(str(r[k]) == v for k, v in f.items())]
        out.sort(key=lambda v: str(v["id"]))
        for v in out:
            v.pop("definition", None)
        return out

    def counts(self) -> dict[str, int]:
        c = dict.fromkeys(caps.STATES, 0)
        for v in self.list_defs():
            c[v["state"]] += 1
        return c
