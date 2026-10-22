"""The governance action runner (WP-G5, docs/governance-actions.md).

One pass: read the new events of every source, match them to the rules of
``config/governance_actions.yaml``, run the actions, remember the event.

* Deterministic: an event, the rules and the facts of the system give the same planned actions
  (``actions_model.plan`` is pure).
* Once per event: the marker row (``governance_event``, key = hash of kind, ref and system) is
  written before the first action. A second run finds it and does nothing. A marker still
  ``started`` (a crash) is resumed: actions already recorded in it are not run again.
* A raising action does not stop the others: each action runs in its own try block and the
  result (done, skipped, refused, failed) goes into the marker.
* No action pauses or blocks an agent. Incidents are made here and closed only by a person.
* Dry run: nothing is written (no marker, no cursor, no row, no record); the result lists what
  would fire.

The runner holds the services it calls; the job and the tests build it the same way.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from supervisor.core.canonical import format_ts
from supervisor.core.errors import ConcurrencyError, DuplicateKeyError, SupervisorError
from supervisor.governance import event_sources as src
from supervisor.governance.actions_model import (
    GovernanceEvent,
    PlannedAction,
    Rule,
    SystemFacts,
    autonomy_rank,
    plan,
    rules_digest,
)
from supervisor.governance.model import SystemsError
from supervisor.monitors.common import MonitorContext, as_dt, get_state, put_state

log = logging.getLogger("supervisor.governance.actions")

ACTOR = "system:governance_actions"
MONITOR = "governance_actions"
MAX_NEW_PER_RUN = 200  # events newly handled in one run; the cursor waits for the rest
REVIEWER_ROLES = ("reviewer", "oversight_manager", "compliance_specialist")
RE_EVAL_FROM = ("deployment", "operation")
MAX_TRIES = 3  # runs for one action; then it is failed_final
LEASE_S = 120  # a runner holds a started event for this long
PENDING_CAP = 100  # started events taken up again in one run


def _on(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)


@dataclass
class Outcome:
    """What one action did: ``status`` is one of ACTION_STATUSES, ``ref`` a short id or code."""

    status: str
    ref: str = ""


@dataclass
class RunResult:
    events: int = 0
    unmatched: int = 0
    already: int = 0
    handled: int = 0
    done: int = 0
    skipped: int = 0
    refused: int = 0
    failed: int = 0
    source_errors: int = 0
    deferred: int = 0
    busy: int = 0
    retrying: int = 0
    planned: list[dict[str, Any]] = field(default_factory=list)  # dry run

    def as_dict(self) -> dict[str, int]:
        return {
            "events": self.events,
            "unmatched": self.unmatched,
            "already": self.already,
            "handled": self.handled,
            "done": self.done,
            "skipped": self.skipped,
            "refused": self.refused,
            "failed": self.failed,
            "source_errors": self.source_errors,
            "deferred": self.deferred,
            "busy": self.busy,
            "retrying": self.retrying,
        }


class ActionRunner:
    def __init__(
        self,
        ctx: MonitorContext,
        settings: Any,
        rules: list[Rule],
        *,
        systems: Any,
        lifecycle: Any,
        reviews: Any,
        incidents: Any,
        notifier: Any,
        controls: Any = None,
        sources: Mapping[str, Callable[..., list[GovernanceEvent]]] | None = None,
    ) -> None:
        self.ctx = ctx
        self.settings = settings
        self.rules = rules
        self.systems = systems
        self.lifecycle = lifecycle
        self.reviews = reviews
        self.incidents = incidents
        self.notifier = notifier
        self.controls = controls
        self.sources = dict(sources) if sources is not None else dict(src.SOURCES)
        self._facts: dict[str, SystemFacts | None] = {}
        self.runner_id = uuid.uuid4().hex[:16]
        self._touched: set[str] = set()

    # ------------------------------------------------------------------ facts
    def facts(self, system_id: str | None) -> SystemFacts | None:
        if system_id is None:
            return None
        if system_id not in self._facts:
            try:
                row = self.ctx.state.get("ai_system", {"system_id": system_id})
                if row is None:
                    self._facts[system_id] = None
                else:
                    level = self.systems.effective_risk_level(system_id).level
                    self._facts[system_id] = SystemFacts(
                        decision33_class=str(row["decision33_class"]),
                        risk_level=level,
                        autonomy_level=autonomy_rank(row.get("autonomy_level")),  # WP-G2 column
                    )
            except Exception:  # noqa: BLE001 - no facts: a filter on the system does not match
                log.exception("system facts of %s could not be read", system_id)
                self._facts[system_id] = None
        return self._facts[system_id]

    # ------------------------------------------------------------------ one pass
    def run(self, *, dry_run: bool = False) -> RunResult:
        res = RunResult()
        now = self.ctx.clock.now()
        links = src.systems_of(self.ctx.state)
        budget = MAX_NEW_PER_RUN
        self._touched = set()
        if not dry_run:
            self._resume_pending(res)
        for name, reader in sorted(self.sources.items()):
            saved = get_state(self.ctx, MONITOR, f"cursor:{name}")
            if saved and saved.get("ts"):
                lo = as_dt(saved["ts"]) - src.OVERLAP
            else:
                lo = now - timedelta(seconds=int(self.settings.governance_actions_lookback_s))
            try:
                events = src.attach_systems(reader(self.ctx, lo, now), links)
            except Exception:  # noqa: BLE001 - one source failing never stops the others
                log.exception("event source %s failed", name)
                res.source_errors += 1
                continue
            res.events += len(events)
            hold: GovernanceEvent | None = None  # first event this run could not take yet
            for ev in events:
                if hold is not None:
                    res.deferred += 1
                    continue
                outcome = self._one(ev, res, dry_run, budget > 0)
                if outcome == "deferred":
                    hold = ev
                    res.deferred += 1
                elif outcome == "new":
                    budget -= 1
            if not dry_run:
                nxt = hold.at if hold is not None else now
                put_state(self.ctx, MONITOR, f"cursor:{name}", {"ts": format_ts(nxt)})
        return res

    def _one(self, ev: GovernanceEvent, res: RunResult, dry_run: bool, can_take: bool) -> str:
        """Handle one event. Returns ``skip`` (no rule, or already done), ``new`` or
        ``deferred`` (over this run's budget)."""
        planned = plan(ev, self.rules, self.facts(ev.system_id))
        if not planned:
            res.unmatched += 1
            return "skip"
        marker = self.ctx.state.get("governance_event", {"event_key": ev.key})
        if ev.key in self._touched or (marker is not None and marker["status"] == "done"):
            res.already += 1
            return "skip"
        if dry_run:
            res.planned.append(
                {
                    "event": ev.kind,
                    "severity": ev.severity,
                    "agent_id": ev.agent_id,
                    "system_id": ev.system_id,
                    "ref": ev.ref,
                    "key": ev.key,
                    "rules": sorted({r for p in planned for r in p.rules}),
                    "actions": [p.action for p in planned],
                    "resume": marker is not None,
                }
            )
            return "new"
        if not can_take:
            return "deferred"
        self._handle(ev, planned, marker, res)
        return "new"

    # ------------------------------------------------------------------ handle
    def _claim(self, marker: Mapping[str, Any]) -> dict[str, Any] | None:
        """Take the lease of a started event. None when a live runner holds it or the claim
        was lost: this runner then leaves the event alone."""
        now = self.ctx.clock.now()
        holder, until = marker.get("runner_id"), marker.get("lease_until")
        if holder and holder != self.runner_id and until is not None and as_dt(until) > now:
            return None
        try:
            return dict(
                self.ctx.state.update(
                    "governance_event",
                    {"event_key": marker["event_key"]},
                    {"runner_id": self.runner_id, "lease_until": now + timedelta(seconds=LEASE_S)},
                    int(marker["row_version"]),
                )
            )
        except (ConcurrencyError, SupervisorError):
            return None

    def _handle(
        self,
        ev: GovernanceEvent,
        planned: list[PlannedAction],
        marker: Mapping[str, Any] | None,
        res: RunResult,
    ) -> None:
        state = self.ctx.state
        rule_ids = sorted({r for p in planned for r in p.rules})
        self._touched.add(ev.key)
        if marker is None:
            now = self.ctx.clock.now()
            try:
                claimed: dict[str, Any] | None = dict(
                    state.insert(
                        "governance_event",
                        {
                            "event_key": ev.key,
                            "kind": ev.kind,
                            "severity": ev.severity,
                            "agent_id": ev.agent_id,
                            "system_id": ev.system_id,
                            "ref": ev.ref,
                            "event_at": ev.at,
                            "status": "started",
                            "rules": rule_ids,
                            "actions": [],
                            "started_at": now,
                            "detail": {
                                "rule_id": ev.rule_id,
                                "case_id": ev.case_id,
                                "evidence": list(ev.evidence) if ev.evidence else None,
                            },
                            "runner_id": self.runner_id,
                            "lease_until": now + timedelta(seconds=LEASE_S),
                        },
                    )
                )
            except DuplicateKeyError:  # another runner won the race: it owns the event
                res.busy += 1
                return
        else:
            claimed = self._claim(marker)
            if claimed is None:
                res.busy += 1
                return
        results: list[dict[str, Any]] = [dict(a) for a in _list(claimed.get("actions"))]
        version = int(claimed["row_version"])

        def entry_of(action: str) -> dict[str, Any] | None:
            return next((a for a in results if a["action"] == action), None)

        def save() -> None:
            nonlocal version
            version = self._save(ev, results, version)

        incident_id = next(
            (
                a["ref"]
                for a in results
                if a["action"] == "create_incident" and a["status"] == "done"
            ),
            "",
        )
        for p in planned:
            entry = entry_of(p.action)
            tries = 0
            if entry is not None:
                if entry["status"] == "attempting":  # a crash after the effect, maybe before save
                    entry.update(status="skipped", ref="maybe_done")
                    save()
                    continue
                if entry["status"] != "failed":  # done, skipped, refused or failed_final
                    continue
                tries = int(entry.get("tries") or 1)
            else:
                entry = {"action": p.action}
                results.append(entry)
            entry.update(status="attempting", ref="", tries=tries)
            save()  # written BEFORE the action: a crash now never repeats it
            out = self._run_action(ev, p, incident_id)
            tries += 1
            status = out.status
            if status == "failed" and tries >= MAX_TRIES:
                status = "failed_final"
            entry.update(status=status, ref=out.ref[:128], tries=tries)
            if p.action == "create_incident" and out.status == "done":
                incident_id = out.ref
            save()
        self._finish(ev, rule_ids, results, version, res)

    def _save(self, ev: GovernanceEvent, results: list[dict[str, Any]], version: int) -> int:
        """Store the action list and renew the lease. Returns the new row version."""
        try:
            row = self.ctx.state.update(
                "governance_event",
                {"event_key": ev.key},
                {
                    "actions": [dict(a) for a in results],
                    "lease_until": self.ctx.clock.now() + timedelta(seconds=LEASE_S),
                },
                version,
            )
            return int(row["row_version"])
        except (ConcurrencyError, SupervisorError):
            log.exception("governance event marker %s could not be saved", ev.key)
            row = self.ctx.state.get("governance_event", {"event_key": ev.key})
            return int(row["row_version"]) if row is not None else version

    def _finish(
        self,
        ev: GovernanceEvent,
        rule_ids: list[str],
        results: list[dict[str, Any]],
        version: int,
        res: RunResult,
    ) -> None:
        now = self.ctx.clock.now()
        if any(a["status"] == "failed" for a in results):
            # a failed action is tried again on a later run (up to MAX_TRIES); the event stays
            # started and the lease is let go
            res.retrying += 1
            try:
                self.ctx.state.update(
                    "governance_event",
                    {"event_key": ev.key},
                    {"runner_id": None, "lease_until": None, "rules": rule_ids},
                    version,
                )
            except (ConcurrencyError, SupervisorError):
                log.exception("governance event marker %s could not be released", ev.key)
            return
        try:
            self.ctx.state.update(
                "governance_event",
                {"event_key": ev.key},
                {
                    "status": "done",
                    "done_at": now,
                    "actions": [dict(a) for a in results],
                    "rules": rule_ids,
                    "runner_id": None,
                    "lease_until": None,
                },
                version,
            )
        except (ConcurrencyError, SupervisorError):
            log.exception("governance event marker %s could not be closed", ev.key)
        tally = {s: sum(1 for a in results if a["status"] == s) for s in _STATUSES}
        res.handled += 1
        res.done += tally["done"]
        res.skipped += tally["skipped"]
        res.refused += tally["refused"]
        res.failed += tally["failed_final"]
        try:
            self.ctx.evidence.record(
                "governance_action",
                f"governance_event:{ev.key}",
                {
                    "event_key": ev.key,
                    "kind": ev.kind,
                    "severity": ev.severity,
                    "agent": ev.agent_id,  # not "agent_id": the record stays on the root lane
                    "system_id": ev.system_id or "",
                    "event_ref": ev.ref,
                    "rules": rule_ids,
                    "actions": [f"{a['action']}:{a['status']}" for a in results],
                    "done_n": tally["done"],
                    "skipped_n": tally["skipped"],
                    "refused_n": tally["refused"],
                    "failed_n": tally["failed_final"],
                    "failed_final_n": tally["failed_final"],
                    "tries_n": sum(int(a.get("tries") or 0) for a in results),
                    "rules_hash": rules_digest(self.rules),
                    "ts": format_ts(now),
                },
            )
        except Exception:  # noqa: BLE001 - the marker is stored; log and go on
            log.exception("governance_action chain record failed")

    def _event_of(self, m: Mapping[str, Any]) -> GovernanceEvent:
        d = m.get("detail")
        if not isinstance(d, Mapping):
            d = {}
        ev = d.get("evidence")
        return GovernanceEvent(
            kind=str(m["kind"]),
            severity=str(m["severity"]),
            agent_id=str(m["agent_id"]),
            ref=str(m["ref"]),
            at=as_dt(m["event_at"]),
            system_id=m.get("system_id"),
            rule_id=str(d.get("rule_id") or ""),
            case_id=d.get("case_id"),
            evidence=(str(ev[0]), str(ev[1])) if isinstance(ev, list) and len(ev) == 2 else None,
        )

    def _resume_pending(self, res: RunResult) -> None:
        """Events whose marker is still ``started`` (a failed action to retry, or a crash): take
        them up again, whatever their age. The source read alone would only find young ones."""
        rows = self.ctx.state.query(
            "governance_event", {"status": "started"}, order_by=("started_at",), limit=PENDING_CAP
        )
        for m in rows:
            try:
                ev = self._event_of(m)
            except Exception:  # noqa: BLE001 - a marker this code cannot read is left alone
                log.exception("governance event marker %s cannot be read", m.get("event_key"))
                continue
            if ev.key != m["event_key"]:
                continue
            planned = plan(ev, self.rules, self.facts(ev.system_id))
            self._handle(ev, planned, m, res)

    # ------------------------------------------------------------------ the actions
    def _run_action(self, ev: GovernanceEvent, p: PlannedAction, incident_id: str) -> Outcome:
        fn = getattr(self, f"_do_{p.action}")
        try:
            out: Outcome = fn(ev, p, incident_id)
        except Exception as exc:  # noqa: BLE001 - a raising action never stops the others
            log.exception("governance action %s failed for %s", p.action, ev.key)
            return Outcome("failed", type(exc).__name__)
        if p.action in ("raise_risk_level", "move_to_re_evaluation") and out.status == "done":
            self._facts.pop(ev.system_id or "", None)  # the level or the stage changed
        return out

    def _do_create_incident(self, ev: GovernanceEvent, p: PlannedAction, _inc: str) -> Outcome:
        row, _created = self.incidents.open_from_event(ev, ACTOR)
        return Outcome("done", str(row["incident_id"]))

    def _owner_of(self, ev: GovernanceEvent) -> str | None:
        if ev.system_id:
            row = self.ctx.state.get("ai_system", {"system_id": ev.system_id})
            if row is not None and row.get("owner_user"):
                return str(row["owner_user"])
        if ev.agent_id != src.NO_AGENT:
            for a in self.ctx.state.query("agent", {"agent_id": ev.agent_id}):
                if a.get("owner_user"):
                    return str(a["owner_user"])
        return None

    def _do_notify_owner(self, ev: GovernanceEvent, p: PlannedAction, inc: str) -> Outcome:
        owner = self._owner_of(ev)
        if owner is None:
            return Outcome("skipped", "no_owner")
        lines = [
            f"event: {ev.kind}",
            f"severity: {ev.severity}",
            f"agent: {ev.agent_id}",
            f"system: {ev.system_id or '-'}",
            f"ref: {ev.ref}",
            f"rules: {', '.join(p.rules)}",
        ]
        if inc:
            lines.append(f"incident: {inc}")
        self.notifier.notify(
            f"owner:{owner}"[:64], f"Governance event: {ev.kind} ({ev.severity})", "\n".join(lines)
        )
        return Outcome("done", "notice")

    def _raised_before(self, ev: GovernanceEvent) -> bool:
        """True when a ``system_change`` chain record of this system already carries the event key
        (the level was raised, the crash came before the marker was saved)."""
        tables = self.ctx.tables
        rows = tables.query(
            "chain_entry",
            {"record_ref": f"system:{ev.system_id}", "record_type": "system_change"},
            order_by=("-ts",),
            limit=200,
        )
        for r in rows:
            for pl in tables.query("chain_payload", {"lane": r["lane"], "seq": r["seq"]}):
                try:
                    body = json.loads(pl["payload"])
                except (TypeError, ValueError):
                    continue
                if body.get("action") == "risk_raise" and body.get("event_key") == ev.key:
                    return True
        return False

    def _do_raise_risk_level(self, ev: GovernanceEvent, p: PlannedAction, _inc: str) -> Outcome:
        if self._raised_before(ev):
            return Outcome("skipped", "already_raised")
        try:
            out = self.systems.raise_risk_from_event(str(ev.system_id), ACTOR, ev.key)
        except SystemsError:
            return Outcome("skipped", "not_raised")
        return Outcome("done", f"{out['from_level']}>{out['to_level']}")

    def _do_move_to_re_evaluation(
        self, ev: GovernanceEvent, p: PlannedAction, _inc: str
    ) -> Outcome:
        row = self.ctx.state.get("ai_system", {"system_id": ev.system_id})
        if row is None or row["lifecycle_stage"] not in RE_EVAL_FROM:
            return Outcome("skipped", "not_deployed")
        try:
            self.lifecycle.move(str(ev.system_id), "re_evaluation", ACTOR)
        except SystemsError:
            return Outcome("refused", "move_refused")
        return Outcome("done", "re_evaluation")

    def _reviewer_for(self, system_id: str) -> str | None:
        team = self.systems._team_rows(system_id)  # noqa: SLF001 - same package
        for role in REVIEWER_ROLES:
            names = sorted(str(m["user_id"]) for m in team if m["team_role"] == role)
            if names:
                return names[0]
        return None

    def _do_create_review(self, ev: GovernanceEvent, p: PlannedAction, _inc: str) -> Outcome:
        reviewer = self._reviewer_for(str(ev.system_id))
        if reviewer is None:
            return Outcome("skipped", "no_reviewer")
        try:
            row = self.reviews.create(
                str(ev.system_id),
                {
                    "kind": "internal",
                    "title": f"Review after governance event: {ev.kind}",
                    "scope": [{"kind": "event", "id": ev.ref}],
                    "reviewer_user": reviewer,
                },
                ACTOR,
            )
        except SystemsError:
            return Outcome("refused", "review_refused")
        return Outcome("done", str(row["review_id"]))

    def _do_fire_webhook(self, ev: GovernanceEvent, p: PlannedAction, _inc: str) -> Outcome:
        from supervisor.governance import events

        row = events.emit(
            self.ctx.state,
            self.ctx.clock,
            self.settings,
            "governance_action",
            str(ev.system_id),
            {
                "event_kind": ev.kind,
                "severity": ev.severity,
                "event_key": ev.key,
                "rule_id": p.rules[0],
            },
        )
        if row is None:
            return Outcome("failed", "not_written")
        return Outcome("done", str(row["event_id"]))

    def _controls_for(self, ev: GovernanceEvent, p: PlannedAction) -> list[str]:
        ids = set(p.controls)
        if ev.evidence is not None:
            kind, target = ev.evidence
            for m in self.ctx.state.query("control_map", {"kind": kind, "target": target}):
                if _on(m["active"]):
                    ids.add(str(m["control_id"]))
        return sorted(ids)

    def _do_reopen_control(self, ev: GovernanceEvent, p: PlannedAction, _inc: str) -> Outcome:
        if self.controls is None:
            return Outcome("skipped", "controls_off")
        if ev.agent_id == src.NO_AGENT:
            return Outcome("skipped", "no_agent")
        opened: list[str] = []
        for cid in self._controls_for(ev, p):
            try:
                self.controls.reopen(cid, ev.agent_id, ev.key, ACTOR)
                opened.append(cid)
            except SupervisorError:  # not active, not in scope for the agent, unknown
                continue
        if not opened:
            return Outcome("skipped", "no_control")
        return Outcome("done", ",".join(opened))


_STATUSES = ("done", "skipped", "refused", "failed", "failed_final")


def _list(value: Any) -> list[Any]:
    import json

    if isinstance(value, list):
        return value
    try:
        out = json.loads(value) if value else []
    except (TypeError, ValueError):
        return []
    return out if isinstance(out, list) else []
