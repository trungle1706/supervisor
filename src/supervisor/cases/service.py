"""Case workflow (WP8): open, triage, contain, sign off, close. Every step is evidence.

Sources that open a case (one ``case_link`` row per source; intake is idempotent):

* ``gate``    a Tier 0 verdict with action block or pause (``open_from_gate_decision``).
              A second decision for the same agent and rule joins the open case
              (alert grouping) instead of opening a new one.
* ``judge``   a judge ``CaseRequest`` (open_case / raise_severity). Judges advise: a request
              opens a case or raises its severity; it never touches the gate.
* ``monitor`` a monitor finding (WP7) via ``open_from_monitor``.

State machine::

    open --triage (assignee)--> triaged --contain (note)--> contained --close--> closed
                                triaged --close (resolution false_alarm only)--> closed

``close`` needs a resolution (confirmed | false_alarm) and a reason. A high or critical
case also needs two sign-offs (``approve``) from two different people, at least one of
them an approver. Signers are human users (never a service principal).

Every mutating call takes ``expected_version`` (the ``row_version`` the user saw): a stale
page gets ``CaseError`` (HTTP 400, "reload"), never a silent overwrite. Each action writes
one ``case_event`` row (actor, actor_kind, auth_method) and one evidence record. Free text
is masked before storage; the chain gets only its SHA-256. Sign-off reasons are stored
verbatim in ``signoff`` (exported verbatim in the case file); the chain gets the hash.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from supervisor.core import rbac
from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import ConcurrencyError, DuplicateKeyError, SupervisorError
from supervisor.core.ports import Clock, EvidenceSink, Masker, Notifier, StateStore, TableStore
from supervisor.evidence.casefile.builder import (
    CaseFile,
    SbvClocks,
    build_case_file,
    load_case_inputs,
)

log = logging.getLogger("supervisor.cases")

SEVERITIES = ("low", "medium", "high", "critical")
TWO_PERSON_SEVERITIES = ("high", "critical")
RESOLUTIONS = ("confirmed", "false_alarm")
SIGNOFF_DECISIONS = ("approve", "reject")
MAX_TEXT = 4000
# Role tuples come from the role matrix (core/rbac.py); the old names stay as aliases.
WORKFLOW_ROLES = rbac.roles_for("case.transition")
COMMENT_ROLES = rbac.roles_for("case.comment")
SIGN_ROLES = rbac.roles_for("case.signoff")
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "open": ("triaged",),
    "triage": ("triaged",),  # legacy value
    "triaged": ("contained", "closed"),
    "contained": ("closed",),
}


class CaseError(SupervisorError):
    """A case action is not allowed (shown to the user as HTTP 400)."""


class PermissionDenied(CaseError):
    """The principal lacks the role for this action."""


class Actor(Protocol):
    user_id: str
    kind: str
    auth_method: str


@dataclass(frozen=True)
class SystemActor:
    """Background identity (laptop system, or the App service principal)."""

    user_id: str = "supervisor-system"
    kind: str = "system"
    auth_method: str = "local_system"
    roles: frozenset[str] = field(default_factory=frozenset)


def _roles(actor: Actor) -> frozenset[str]:
    return frozenset(getattr(actor, "roles", ()) or ())


def require(actor: Actor, roles: Sequence[str], what: str) -> None:
    if actor.kind != "user":
        raise PermissionDenied(f"{what} needs a signed-in person, not a {actor.kind}")
    if not (_roles(actor) & set(roles)):
        raise PermissionDenied(f"{actor.user_id} cannot {what}: needs role {' or '.join(roles)}")


def require_permission(actor: Actor, permission: str, what: str) -> None:
    """Like ``require`` but the roles come from the role matrix."""
    require(actor, rbac.roles_for(permission), what)


def _sev_rank(sev: str) -> int:
    return SEVERITIES.index(sev) if sev in SEVERITIES else 1


def _text(value: str | None, name: str, *, required: bool) -> str:
    text = (value or "").strip()
    if required and not text:
        raise CaseError(f"{name} is required")
    if len(text) > MAX_TEXT:
        raise CaseError(f"{name} is longer than {MAX_TEXT} characters")
    return text


def case_id_for(source_kind: str, source_ref: str) -> str:
    """Deterministic case id for a source: a retried intake recreates the same case."""
    digest = hashlib.sha256(f"{source_kind}:{source_ref}".encode()).hexdigest()
    return f"CASE-{digest[:10].upper()}"


class CaseService:
    def __init__(
        self,
        state: StateStore,
        tables: TableStore,
        evidence: EvidenceSink,
        clock: Clock,
        *,
        masker: Masker | None = None,
        notifier: Notifier | None = None,
        system: Actor | None = None,
        decision33_text: str = "",
        mask_version: str = "",
    ) -> None:
        self.state = state
        self.tables = tables
        self.evidence = evidence
        self.clock = clock
        self.masker = masker
        self.notifier = notifier
        self.system: Actor = system or SystemActor()
        self.decision33_text = decision33_text
        self.mask_version = mask_version
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ reads

    def get(self, case_id: str) -> dict[str, Any]:
        row = self.state.get("cases", {"case_id": case_id})
        if row is None:
            raise CaseError(f"case {case_id[:64]} does not exist")
        return row

    def list_cases(
        self,
        *,
        statuses: Iterable[str] | None = None,
        severity: str | None = None,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Sorted by severity (critical first), then age (oldest first)."""
        where: dict[str, Any] = {}
        if agent_id:
            where["agent_id"] = agent_id
        if severity:
            where["severity"] = severity
        rows = self.state.query("cases", where or None)
        if statuses is not None:
            wanted = set(statuses)
            rows = [r for r in rows if r["status"] in wanted]
        rows.sort(key=lambda r: (-_sev_rank(r["severity"]), r["opened_at"], r["case_id"]))
        return rows

    def events(self, case_id: str) -> list[dict[str, Any]]:
        return self.tables.query("case_event", {"case_id": case_id}, order_by=("seq",))

    def signoffs(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.tables.query("signoff", {"case_id": case_id})
        rows.sort(key=lambda r: (r["ts"], r["signoff_id"]))
        return rows

    def links(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.tables.query("case_link", {"case_id": case_id})
        rows.sort(key=lambda r: (r["ts"], r["source_ref"]))
        return rows

    def linked_verdicts(self, case_id: str) -> list[dict[str, Any]]:
        """Verdict rows of the case's sources (gate decisions and judge verdicts)."""
        out: dict[str, dict[str, Any]] = {}
        for link in self.links(case_id):
            if link["source_kind"] == "gate":
                rows = self.tables.query("verdict", {"event_id": link["source_ref"]})
            elif link["source_kind"] == "judge":
                rows = self.tables.query("verdict", {"verdict_id": link["source_ref"]})
            else:
                rows = []
            for r in rows:
                out[r["verdict_id"]] = r
        return sorted(out.values(), key=lambda r: (r["ts"], r["verdict_id"]))

    def case_file(self, case_id: str, *, now: datetime | None = None) -> CaseFile:
        now = now or self.clock.now()
        inputs = load_case_inputs(self.tables, self.state, case_id, now=now)
        linked = {v["verdict_id"] for v in self.linked_verdicts(case_id)}
        if linked:  # precise links beat the time-window heuristic of the loader
            from supervisor.core.models import Verdict

            inputs["verdicts"] = [
                Verdict.model_validate(v)
                for v in self.tables.query("verdict", {"agent_id": inputs["case"].agent_id})
                if v["verdict_id"] in linked
            ]
        return build_case_file(
            **inputs,
            decision33_text=self.decision33_text,
            mask_version=self.mask_version,
            generated_at=now,
            rule_regulation_refs=self._rule_refs(),
        )

    def clocks(self, case_id: str) -> SbvClocks:
        """SBV clocks (24 h report, 5-day remediation) from the case-file builder."""
        return self.case_file(case_id).sbv

    # ------------------------------------------------------------------ helpers

    def _rule_refs(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for r in self.state.query("rule"):
            if r.get("regulation_ref"):
                out[r["rule_id"]] = [r["regulation_ref"]]
        return out

    def _rule(self, rule_id: str | None) -> dict[str, Any] | None:
        if not rule_id:
            return None
        rows = self.state.query("rule", {"rule_id": rule_id})
        return max(rows, key=lambda r: r["version"]) if rows else None

    def _mask(self, text: str) -> str:
        return self.masker.mask(text) if (self.masker is not None and text) else text

    def _notify(self, channel: str, subject: str, body: str) -> None:
        if self.notifier is not None:
            try:
                self.notifier.notify(channel, subject, body)
            except Exception as exc:  # noqa: BLE001 - a notice never blocks the workflow
                log.warning("notice failed: %s", type(exc).__name__)

    def _event(
        self,
        case: Mapping[str, Any],
        actor: Actor,
        action: str,
        *,
        comment: str | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> int:
        """Append one case_event + evidence record. Returns the seq."""
        case_id = case["case_id"]
        seq = len(self.tables.query("case_event", {"case_id": case_id}))
        now = self.clock.now()
        masked = self._mask(comment) if comment else None
        self.tables.append(
            "case_event",
            [
                {
                    "case_id": case_id,
                    "seq": seq,
                    "ts": now,
                    "actor": actor.user_id,
                    "actor_kind": actor.kind,
                    "action": action,
                    "comment_masked": masked,
                    "auth_method": actor.auth_method,
                }
            ],
        )
        payload: dict[str, Any] = {
            "agent_id": case["agent_id"],
            "case_id": case_id,
            "seq": seq,
            "action": action,
            "actor": actor.user_id,
            "actor_kind": actor.kind,
            "auth_method": actor.auth_method,
            "status": case["status"],
            "severity": case["severity"],
            "row_version": int(case.get("row_version") or 0),
            "ts": format_ts(now),
            **(extra or {}),
        }
        if masked:
            payload["comment_sha256"] = sha256_hex(masked)
        self.evidence.record("case_event", f"case_event:{case_id}:{seq}", payload)
        return seq

    def _update(
        self, case_id: str, changes: Mapping[str, Any], expected_version: int | None
    ) -> dict[str, Any]:
        current = self.get(case_id)
        if expected_version is None:
            raise CaseError("row_version is required (reload the page)")
        if int(expected_version) != int(current["row_version"]):
            raise CaseError(
                f"case {case_id} changed since you loaded it (version {expected_version}, "
                f"now {current['row_version']}); reload and try again"
            )
        if current["status"] == "closed":
            raise CaseError(f"case {case_id} is closed")
        try:
            return self.state.update(
                "cases",
                {"case_id": case_id},
                dict(changes) or {"status": current["status"]},
                int(expected_version),
            )
        except ConcurrencyError as exc:
            raise CaseError(f"case {case_id} changed while saving; reload and try again") from exc

    # ------------------------------------------------------------------ open

    def _link(self, kind: str, ref: str, case_id: str, agent_id: str) -> bool:
        """Record the source. False when the source is already linked (idempotent)."""
        try:
            self.tables.append(
                "case_link",
                [
                    {
                        "source_kind": kind,
                        "source_ref": ref,
                        "case_id": case_id,
                        "agent_id": agent_id,
                        "ts": self.clock.now(),
                    }
                ],
            )
        except DuplicateKeyError:
            return False
        return True

    def linked_case(self, kind: str, ref: str) -> str | None:
        rows = self.tables.query("case_link", {"source_kind": kind, "source_ref": ref})
        return rows[0]["case_id"] if rows else None

    def open_case(
        self,
        *,
        agent_id: str,
        severity: str,
        summary: str,
        source_kind: str,
        source_ref: str,
        actor: Actor | None = None,
        regulation_refs: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Open a case for a source, or return the case already opened for it."""
        if severity not in SEVERITIES:
            raise CaseError(f"severity must be one of {', '.join(SEVERITIES)}")
        actor = actor or self.system
        summary = self._mask(_text(summary, "summary", required=True))
        case_id = case_id_for(source_kind, source_ref)
        with self._lock:
            existing = self.linked_case(source_kind, source_ref)
            if existing is not None and self.state.get("cases", {"case_id": existing}):
                return self.get(existing)
            self._link(source_kind, source_ref, case_id, agent_id)
            now = self.clock.now()
            row = {
                "case_id": case_id,
                "agent_id": agent_id,
                "severity": severity,
                "status": "open",
                "opened_at": now,
                "assignee": None,
                "itsm_ref": None,
                "regulation_refs": sorted(set(regulation_refs)),
                "summary": summary,
                "report_due_at": None,
                "closed_at": None,
            }
            try:
                case = self.state.insert("cases", row)
            except DuplicateKeyError:
                return self.get(case_id)
            due = self.case_file(case_id, now=now).sbv.report_due_at
            case = self.state.update(
                "cases", {"case_id": case_id}, {"report_due_at": due}, case["row_version"]
            )
            self.evidence.record(
                "case",
                f"case:{case_id}",
                {
                    "agent_id": agent_id,
                    "case_id": case_id,
                    "severity": severity,
                    "source_kind": source_kind,
                    "source_ref": source_ref,
                    "summary_sha256": sha256_hex(summary),
                    "report_due_at": format_ts(due),
                    "opened_by": actor.user_id,
                    "auth_method": actor.auth_method,
                    "ts": format_ts(now),
                },
            )
            self._event(
                case, actor, "open", extra={"source_kind": source_kind, "source_ref": source_ref}
            )
        self._notify(
            "reviewers",
            f"[{severity}] new case {case_id} ({agent_id})",
            f"{summary}\nSBV report due {format_ts(due)}",
        )
        return case

    def _join(self, case: Mapping[str, Any], kind: str, ref: str, actor: Actor) -> None:
        if self._link(kind, ref, case["case_id"], case["agent_id"]):
            self._event(case, actor, "link_source", extra={"source_kind": kind, "source_ref": ref})

    def open_from_case_request(self, req: Any, actor: Actor | None = None) -> dict[str, Any]:
        """Judge ``CaseRequest`` (open_case | raise_severity). Advice only: never gates."""
        actor = actor or self.system
        ref = (list(req.verdict_ids) or [uuid.uuid4().hex])[0]
        severity = req.severity if req.severity in SEVERITIES else "medium"
        if req.kind == "raise_severity":
            with self._lock:
                open_cases = [
                    c for c in self.list_cases(agent_id=req.agent_id) if c["status"] != "closed"
                ]
                if open_cases:
                    case = max(open_cases, key=lambda c: c["opened_at"])
                    if self.linked_case("judge", ref) is None:
                        self._join(case, "judge", ref, actor)
                    if _sev_rank(severity) > _sev_rank(case["severity"]):
                        before = case["severity"]
                        case = self.state.update(
                            "cases",
                            {"case_id": case["case_id"]},
                            {"severity": severity},
                            case["row_version"],
                        )
                        self._event(
                            case,
                            actor,
                            "raise_severity",
                            comment=req.reason,
                            extra={"from_severity": before, "to_severity": severity},
                        )
                    return self.get(case["case_id"])
        return self.open_case(
            agent_id=req.agent_id,
            severity=severity,
            summary=f"Judge (advisory): {req.reason}",
            source_kind="judge",
            source_ref=ref,
            actor=actor,
        )

    def open_from_gate_decision(
        self, verdicts: Sequence[Mapping[str, Any]], actor: Actor | None = None
    ) -> dict[str, Any] | None:
        """Tier 0 verdict rows of one gate decision (same event_id). None if it allowed."""
        stops = [
            v
            for v in verdicts
            if int(v["tier"]) == 0 and v["action"] in ("block", "pause") and not v["advisory"]
        ]
        if not stops:
            return None
        actor = actor or self.system
        first = min(stops, key=lambda v: (v["action"] != "pause", v["ts"]))
        decision_id = str(first["event_id"] or first["verdict_id"])
        agent_id = first["agent_id"]
        rule_id = first.get("rule_id")
        with self._lock:
            linked = self.linked_case("gate", decision_id)
            if linked is not None and self.state.get("cases", {"case_id": linked}):
                return self.get(linked)
            group = self._open_gate_case_for(agent_id, rule_id)
            if group is not None:
                self._join(group, "gate", decision_id, actor)
                return self.get(group["case_id"])
            rule = self._rule(rule_id)
            sev = (rule or {}).get("severity") or (
                "high" if first["action"] == "pause" else "medium"
            )
            if first["action"] == "pause" and _sev_rank(sev) < _sev_rank("high"):
                sev = "high"
            refs = [rule["regulation_ref"]] if rule and rule.get("regulation_ref") else []
            reason = (first.get("rationale_masked") or "").strip()
            summary = f"Gate {first['action']} by rule {rule_id or '-'}" + (
                f": {reason}" if reason else ""
            )
            return self.open_case(
                agent_id=agent_id,
                severity=sev,
                summary=summary[:MAX_TEXT],
                source_kind="gate",
                source_ref=decision_id,
                actor=actor,
                regulation_refs=refs,
            )

    def _open_gate_case_for(self, agent_id: str, rule_id: str | None) -> dict[str, Any] | None:
        """Alert grouping: an open case of this agent already opened by the same rule."""
        if not rule_id:
            return None
        for case in self.list_cases(agent_id=agent_id):
            if case["status"] == "closed":
                continue
            for link in self.links(case["case_id"]):
                if link["source_kind"] != "gate":
                    continue
                rows = self.tables.query("verdict", {"event_id": link["source_ref"]})
                if any(r.get("rule_id") == rule_id for r in rows):
                    return case
        return None

    def open_from_monitor(
        self,
        *,
        agent_id: str,
        monitor_id: str,
        finding_ref: str,
        severity: str,
        summary: str,
        actor: Actor | None = None,
    ) -> dict[str, Any]:
        """A monitor finding (WP7: drift, fairness, multi-agent pattern)."""
        return self.open_case(
            agent_id=agent_id,
            severity=severity,
            summary=f"Monitor {monitor_id}: {summary}",
            source_kind="monitor",
            source_ref=f"{monitor_id}:{finding_ref}",
            actor=actor,
        )

    def sync_gate_cases(self, actor: Actor | None = None) -> list[str]:
        """Open (or join) cases for every gate block/pause not yet linked. Idempotent."""
        linked = {r["source_ref"] for r in self.tables.query("case_link", {"source_kind": "gate"})}
        decisions: dict[str, list[dict[str, Any]]] = {}
        for action in ("block", "pause"):
            for v in self.tables.query("verdict", {"tier": 0, "action": action}):
                key = str(v["event_id"] or v["verdict_id"])
                if key not in linked:
                    decisions.setdefault(key, []).append(v)
        touched: list[str] = []
        for _, rows in sorted(decisions.items(), key=lambda kv: min(r["ts"] for r in kv[1])):
            case = self.open_from_gate_decision(rows, actor)
            if case is not None:
                touched.append(case["case_id"])
        return touched

    # ------------------------------------------------------------------ workflow

    def assign(
        self, case_id: str, assignee: str, actor: Actor, expected_version: int | None
    ) -> dict[str, Any]:
        require_permission(actor, "case.assign", "assign a case")
        assignee = _text(assignee, "assignee", required=True)[:128]
        with self._lock:
            case = self._update(case_id, {"assignee": assignee}, expected_version)
            self._event(case, actor, "assign", extra={"assignee": assignee})
        return case

    def comment(
        self, case_id: str, text: str, actor: Actor, expected_version: int | None
    ) -> dict[str, Any]:
        require_permission(actor, "case.comment", "comment on a case")
        text = _text(text, "comment", required=True)
        with self._lock:
            case = self._update(case_id, {}, expected_version)
            self._event(case, actor, "comment", comment=text)
        return case

    def set_itsm_ref(
        self, case_id: str, ref: str, actor: Actor, expected_version: int | None
    ) -> dict[str, Any]:
        require_permission(actor, "case.itsm", "set the ITSM reference")
        ref = _text(ref, "ITSM reference", required=True)
        if len(ref) > 64 or not all(ch.isalnum() or ch in "-_.:/#" for ch in ref):
            raise CaseError("ITSM reference: letters, digits and - _ . : / # only (max 64)")
        with self._lock:
            case = self._update(case_id, {"itsm_ref": ref}, expected_version)
            self._event(case, actor, "itsm_ref", extra={"itsm_ref": ref})
        return case

    def transition(
        self,
        case_id: str,
        to: str,
        actor: Actor,
        expected_version: int | None,
        *,
        note: str = "",
        assignee: str | None = None,
        resolution: str | None = None,
    ) -> dict[str, Any]:
        require_permission(actor, "case.transition", f"move a case to {to}")
        with self._lock:
            current = self.get(case_id)
            frm = current["status"]
            if to not in TRANSITIONS.get(frm, ()):
                raise CaseError(f"case {case_id} is {frm}; cannot move to {to}")
            changes: dict[str, Any] = {"status": to}
            extra: dict[str, Any] = {"from_status": frm, "to_status": to}
            if to == "triaged":
                who = (assignee or "").strip() or (current["assignee"] or "")
                if not who:
                    raise CaseError("triage needs an assignee")
                changes["assignee"] = who[:128]
                extra["assignee"] = changes["assignee"]
                note = _text(note, "triage note", required=False)
            elif to == "contained":
                note = _text(note, "containment note (what was done)", required=True)
            elif to == "closed":
                if resolution not in RESOLUTIONS:
                    raise CaseError(f"close needs a resolution: {' or '.join(RESOLUTIONS)}")
                if frm == "triaged" and resolution != "false_alarm":
                    raise CaseError("only a false alarm can close before containment")
                note = _text(note, "closing reason", required=True)
                extra["resolution"] = resolution
                if current["severity"] in TWO_PERSON_SEVERITIES:
                    approvers = self._approvals(case_id)
                    if len(approvers) < 2:
                        raise CaseError(
                            f"a {current['severity']} case needs two sign-offs by two "
                            f"different people before closing ({len(approvers)} so far)"
                        )
                changes["closed_at"] = self.clock.now()
            case = self._update(case_id, changes, expected_version)
            action = {"triaged": "triage", "contained": "contain"}.get(to, f"close:{resolution}")
            self._event(case, actor, action, comment=note or None, extra=extra)
            if to == "closed" and current["severity"] not in TWO_PERSON_SEVERITIES:
                # A closing note is not a signed statement: store it masked like comments.
                self._signoff_row(
                    case, actor, f"close:{resolution}", self._mask(note), role="reviewer"
                )
        if to == "contained" and current["severity"] in TWO_PERSON_SEVERITIES:
            self._notify(
                "approvers",
                f"sign-off needed: {case_id} ({current['severity']})",
                f"Case {case_id} for {current['agent_id']} is contained and needs two "
                "sign-offs before it can close.",
            )
        if to == "closed":
            self._notify("reviewers", f"case {case_id} closed ({resolution})", note)
        return case

    # ------------------------------------------------------------------ sign-off

    def _approvals(self, case_id: str) -> dict[str, str]:
        """Current approvals {reviewer_id: role}; a reject clears earlier approvals."""
        out: dict[str, str] = {}
        for s in self.signoffs(case_id):
            decision, _, role = str(s["decision"]).partition(":")
            if decision == "reject":
                out.clear()
            elif decision == "approve":
                out[s["reviewer_id"]] = role
        return out

    def _signoff_row(
        self, case: Mapping[str, Any], actor: Actor, decision: str, reason: str, *, role: str
    ) -> dict[str, Any]:
        now = self.clock.now()
        row = {
            "signoff_id": uuid.uuid4().hex,
            "case_id": case["case_id"],
            "reviewer_id": actor.user_id,
            "decision": f"{decision}:{role}" if decision in SIGNOFF_DECISIONS else decision,
            "reason": reason,  # verbatim human text (bank guide 6: export it verbatim)
            "ts": now,
            "auth_method": actor.auth_method,
        }
        self.tables.append("signoff", [row])
        self.evidence.record(
            "signoff",
            f"signoff:{row['signoff_id']}",
            {
                "agent_id": case["agent_id"],
                "case_id": case["case_id"],
                "signoff_id": row["signoff_id"],
                "reviewer_id": actor.user_id,
                "actor_kind": actor.kind,
                "auth_method": actor.auth_method,
                "role": role,
                "decision": row["decision"],
                "reason_sha256": sha256_hex(reason),
                "ts": format_ts(now),
            },
        )
        return row

    def sign_off(
        self,
        case_id: str,
        actor: Actor,
        decision: str,
        reason: str,
        expected_version: int | None,
    ) -> dict[str, Any]:
        """Two-person sign-off for closing a high / critical case."""
        require_permission(actor, "case.signoff", "sign off a case")
        if decision not in SIGNOFF_DECISIONS:
            raise CaseError(f"decision must be {' or '.join(SIGNOFF_DECISIONS)}")
        reason = _text(reason, "sign-off statement", required=True)
        roles = _roles(actor)
        role = "approver" if "approver" in roles else ("admin" if "admin" in roles else "reviewer")
        with self._lock:
            current = self.get(case_id)
            if current["status"] not in ("triaged", "contained"):
                raise CaseError(
                    f"case {case_id} is {current['status']}; sign-off needs triaged or contained"
                )
            approvals = self._approvals(case_id)
            if decision == "approve":
                if actor.user_id in approvals:
                    raise CaseError(
                        f"{actor.user_id} already signed this case; the second sign-off must "
                        "come from a different person"
                    )
                if approvals and role != "approver" and "approver" not in approvals.values():
                    raise CaseError("the second sign-off must come from an approver")
                if len(approvals) >= 2:
                    raise CaseError("this case already has two sign-offs; it can be closed")
            case = self._update(case_id, {}, expected_version)
            row = self._signoff_row(case, actor, decision, reason, role=role)
            self._event(
                case,
                actor,
                f"signoff:{decision}",
                extra={"signoff_id": row["signoff_id"], "role": role},
            )
        return {"case": case, "signoff": row, "approvals": self._approvals(case_id)}


__all__ = [
    "Actor",
    "CaseError",
    "CaseService",
    "PermissionDenied",
    "RESOLUTIONS",
    "SEVERITIES",
    "SystemActor",
    "TRANSITIONS",
    "case_id_for",
    "require",
]
