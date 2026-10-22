"""Incidents of the governance loop (WP-G5, docs/incidents.md).

An incident is made by the governance action job from an event, never by a person and never by
a judge. Its title comes from a template (no free text from an event). A person moves it on
(``investigating``, ``resolved``) and closes it; nothing automatic can close one. Every change
writes an ``incident_change`` chain record: ids, enums, integers and hashes, no title, no
root-cause text, no user id, no float.

States and moves::

    open --> investigating --> resolved --> closed
      |            |               |
      +------------+---------------+--> closed        (a person; closed is final)
      open --> resolved      resolved --> investigating (the fix did not hold)
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from supervisor.controls.model import actor_ref
from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import ConcurrencyError, DuplicateKeyError, NotFoundError
from supervisor.governance.actions_model import SEVERITIES, GovernanceActionsError, GovernanceEvent
from supervisor.governance.systems import ALL, _plain

log = logging.getLogger("supervisor.governance.incidents")

STATUSES: tuple[str, ...] = ("open", "investigating", "resolved", "closed")
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "open": ("investigating", "resolved", "closed"),
    "investigating": ("resolved", "closed"),
    "resolved": ("investigating", "closed"),
    "closed": (),
}
# The title of an incident: a fixed text per event kind. Only the rule id of an alert (a checked
# id) is filled in. An event never supplies text.
TITLES: dict[str, str] = {
    "alert": "Alert {rule} raised",
    "gate_stop": "Gate stopped a call to a money, credit or data export tool",
    "detector_failed": "A detector could not run",
    "monitor_failing": "A monitor found a breach",
    "pack_no_go": "A required assurance pack gave a NO-GO",
    "chain_break": "The evidence chain failed its verification",
    "model_version_change": "The model behind an agent changed",
    "judge_escalation": "A judge asked for a person to look",
}
MAX_TEXT = 1000
FETCH_LIMIT = 2000
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_RULE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_ID = re.compile(r"^inc_[0-9a-f]{24}$")


class IncidentError(GovernanceActionsError):
    """A bad incident input or a move the incident refuses (HTTP 400)."""


def incident_id_for(event_key: str) -> str:
    return "inc_" + event_key[:24]


def title_for(kind: str, rule_id: str = "") -> str:
    template = TITLES[kind]
    return template.format(rule=rule_id if _RULE.match(rule_id or "") else "(unknown)")


def _text(value: Any, what: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise IncidentError(f"{what} must be text")
    text = value.strip()
    if _CTRL.search(text.replace("\n", " ").replace("\t", " ")):
        raise IncidentError(f"{what} has a control character")
    if len(text) > MAX_TEXT:
        raise IncidentError(f"{what} is longer than {MAX_TEXT} characters")
    return text or None


class IncidentService:
    def __init__(
        self, state: Any, clock: Any, settings: Any, *, evidence: Any = None, systems: Any = None
    ) -> None:
        self.state = state
        self.clock = clock
        self.settings = settings
        self.evidence_sink = evidence
        self.systems = systems  # SystemService, for scope; None = no scoping (the job)

    # ------------------------------------------------------------------ plumbing
    def _chain(self, action: str, row: Mapping[str, Any], actor: str, **extra: Any) -> None:
        if self.evidence_sink is None:
            return
        payload: dict[str, Any] = {
            "incident_id": row["incident_id"],
            "action": action,
            "kind": row["kind"],
            "severity": row["severity"],
            "status": row["status"],
            "system_id": row.get("system_id") or "",
            "agent": row["agent_id"],  # not "agent_id": the record stays on the root lane
            "event_ref": row["event_ref"],
            "case_id": row.get("case_id") or "",
            "actor_ref": actor_ref(self.settings, actor, "system"),
            "ts": format_ts(self.clock.now()),
            **extra,
        }
        try:
            self.evidence_sink.record("incident_change", f"incident:{row['incident_id']}", payload)
        except Exception:  # noqa: BLE001 - the row is stored; log and go on
            log.exception("incident chain record failed")

    def _need(self, incident_id: str) -> dict[str, Any]:
        if not isinstance(incident_id, str) or not _ID.match(incident_id):
            raise NotFoundError(f"incident {str(incident_id)[:64]} does not exist")
        row = self.state.get("incident", {"incident_id": incident_id})
        if row is None:
            raise NotFoundError(f"incident {incident_id} does not exist")
        return dict(row)

    # ------------------------------------------------------------------ create (the job only)
    def open_from_event(
        self, event: GovernanceEvent, actor: str = "system:governance_actions"
    ) -> tuple[dict[str, Any], bool]:
        """Make the incident of an event. The id comes from the event key, so a repeat finds the
        same incident: ``(row, False)``. There is no route and no other caller."""
        iid = incident_id_for(event.key)
        try:
            row = dict(
                self.state.insert(
                    "incident",
                    {
                        "incident_id": iid,
                        "system_id": event.system_id,
                        "agent_id": event.agent_id,
                        "kind": event.kind,
                        "severity": event.severity,
                        "title": title_for(event.kind, event.rule_id),
                        "event_ref": event.ref,
                        "status": "open",
                        "opened_at": self.clock.now(),
                        "case_id": event.case_id,
                    },
                )
            )
        except DuplicateKeyError:
            return self._need(iid), False
        self._chain("create", row, actor)
        return row, True

    # ------------------------------------------------------------------ reads
    def view(self, row: Mapping[str, Any]) -> dict[str, Any]:
        out = dict(row)
        out["next"] = list(TRANSITIONS.get(str(row["status"]), ()))
        return _plain(out)  # type: ignore[no-any-return]

    def visible(self, row: Mapping[str, Any], me: Any, agents: set[str] | None = None) -> bool:
        """A person sees the incidents of the systems in their scope, and the incidents with no
        system for agents in their scope. Without a system service everything is visible."""
        if self.systems is None:
            return True
        scope = self.systems.scope_for(me)
        if scope is ALL:
            return True
        if row.get("system_id"):
            return str(row["system_id"]) in scope
        if agents is None:
            agents = {str(a["agent_id"]).lower() for a in self.systems.agents_in_scope(me)}
        return str(row["agent_id"]).lower() in agents

    def list_incidents(
        self, me: Any = None, filters: Mapping[str, str] | None = None, limit: int = FETCH_LIMIT
    ) -> list[dict[str, Any]]:
        f = dict(filters or {})
        unknown = sorted(set(f) - {"status", "severity", "kind", "system", "agent", "q"})
        if unknown:
            raise IncidentError(f"unknown filter: {', '.join(unknown)}")
        if f.get("status") and f["status"] not in (*STATUSES, "all", "active"):
            raise IncidentError(f"status must be one of {', '.join(STATUSES)}, active or all")
        if f.get("severity") and f["severity"] not in SEVERITIES:
            raise IncidentError(f"severity must be one of {', '.join(SEVERITIES)}")
        if f.get("kind") and f["kind"] not in TITLES:
            raise IncidentError(f"kind must be one of {', '.join(TITLES)}")
        where: dict[str, str] = {
            col: f[key]
            for key, col in (
                ("severity", "severity"),
                ("kind", "kind"),
                ("system", "system_id"),
                ("agent", "agent_id"),
            )
            if f.get(key)
        }
        status = f.get("status") or "active"
        wanted = (
            ("open", "investigating", "resolved")
            if status == "active"
            else (() if status == "all" else (status,))
        )
        if wanted:  # the store filters; one query for each wanted status
            rows = [
                dict(r)
                for st in wanted
                for r in self.state.query("incident", {**where, "status": st})
            ]
        else:
            rows = [dict(r) for r in self.state.query("incident", where or None)]
        agents = None
        if me is not None and self.systems is not None:
            agents = {str(a["agent_id"]).lower() for a in self.systems.agents_in_scope(me)}
        out = []
        for r in rows:
            if me is not None and not self.visible(r, me, agents):
                continue
            if not _fits(r, f):
                continue
            out.append(r)
        out.sort(key=lambda r: (r["opened_at"], r["incident_id"]), reverse=True)
        return [self.view(r) for r in out[:limit]]

    def counts(self, me: Any = None) -> dict[str, int]:
        out = dict.fromkeys(STATUSES, 0)
        for r in self.list_incidents(me, {"status": "all"}):
            out[str(r["status"])] += 1
        return out

    def get(self, incident_id: str, me: Any = None) -> dict[str, Any]:
        row = self._need(incident_id)
        if me is not None and not self.visible(row, me):
            raise NotFoundError(f"incident {incident_id} does not exist")
        return self.view(row)

    def for_system(self, system_id: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self.state.query("incident", {"system_id": system_id})]
        rows.sort(key=lambda r: (r["opened_at"], r["incident_id"]), reverse=True)
        return [self.view(r) for r in rows[:limit]]

    # ------------------------------------------------------------------ a person moves it on
    def transition(
        self,
        incident_id: str,
        to_status: str,
        who: Any,
        *,
        root_cause: Any = None,
        affected_scope: Any = None,
        expected_version: int | None = None,
        me_scope: Any = None,
    ) -> dict[str, Any]:
        """Move an incident. Only a signed-in person can (``who.kind == "user"``); the route
        has checked the permission. ``root_cause`` and ``affected_scope`` are typed by the
        person; the chain keeps a hash of each."""
        if getattr(who, "kind", None) != "user":
            raise IncidentError("an incident is moved by a signed-in person, not by a system")
        actor = str(getattr(who, "user_id", ""))
        if not actor:
            raise IncidentError("an incident is moved by a signed-in person")
        cur = self._need(incident_id)
        if me_scope is not None and not self.visible(cur, me_scope):
            raise NotFoundError(f"incident {incident_id} does not exist")
        if to_status not in STATUSES:
            raise IncidentError(f"status must be one of {', '.join(STATUSES)}")
        if cur["status"] == "closed":
            raise IncidentError("the incident is closed; a closed incident does not move")
        if to_status not in TRANSITIONS[str(cur["status"])]:
            raise IncidentError(
                f"an incident that is {cur['status']} can become "
                f"{', '.join(TRANSITIONS[str(cur['status'])])}, not {to_status}"
            )
        cause = _text(root_cause, "root_cause")
        scope = _text(affected_scope, "affected_scope")
        changes: dict[str, Any] = {"status": to_status}
        if cause is not None:
            changes["root_cause"] = cause
        if scope is not None:
            changes["affected_scope"] = scope
        if to_status == "closed":
            changes.update(closed_at=self.clock.now(), closed_by=actor)
        version = expected_version if expected_version is not None else cur["row_version"]
        try:
            stored = dict(
                self.state.update("incident", {"incident_id": incident_id}, changes, int(version))
            )
        except ConcurrencyError:
            raise IncidentError("the incident was changed by someone else; reload") from None
        self._chain(
            "transition",
            stored,
            actor,
            from_status=cur["status"],
            root_cause_hash=sha256_hex({"t": stored.get("root_cause") or ""}),
            affected_hash=sha256_hex({"t": stored.get("affected_scope") or ""}),
        )
        return self.view(stored)


def _fits(row: Mapping[str, Any], f: Mapping[str, str]) -> bool:
    status = f.get("status") or "active"
    if status == "active" and row["status"] == "closed":
        return False
    if status not in ("active", "all") and row["status"] != status:
        return False
    if f.get("severity") and row["severity"] != f["severity"]:
        return False
    if f.get("kind") and row["kind"] != f["kind"]:
        return False
    if f.get("system") and row.get("system_id") != f["system"]:
        return False
    if f.get("agent") and str(row["agent_id"]).lower() != f["agent"].lower():
        return False
    if f.get("q"):
        hay = f"{row['incident_id']} {row['title']} {row['agent_id']} {row['event_ref']}".lower()
        if f["q"].lower() not in hay:
            return False
    return True
