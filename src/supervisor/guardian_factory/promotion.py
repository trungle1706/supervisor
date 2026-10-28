"""Shadow mode and promotion of a guardian definition (WP-G3, GUARDIAN_FACTORY).

States: ``draft -> benchmarked -> shadow -> approved -> live -> retired`` (``caps.TRANSITIONS`` is
the wall; this module holds the conditions). A version is immutable once it leaves ``draft``:
only ``lifecycle.state``, ``lifecycle.approvals`` and ``lifecycle.allow_list`` change.

====================  ==========================================================================
move                  condition
====================  ==========================================================================
benchmarked -> shadow ``start_shadow``: guardians.edit in the owner group; the newest benchmark
                      run still fits the definition. From now on the gate (GUARDIAN_SHADOW) runs
                      the detector in log-only mode.
shadow -> approved    ``approve`` twice: ``owner_lead`` (the owner group's approver, or an admin)
                      and ``platform_security`` (a member of the platform group, or an admin),
                      two different people; the author of the version never approves
                      (``author_cannot_approve``); the same person twice is ``same_person``; the
                      shadow period is complete and the reviewed false rate is at most
                      ``thresholds.max_fpr_pct``, else ``shadow_not_passed`` with the numbers.
approved -> live      ``go_live``: owner lead or admin. The previous live version becomes
                      retired (and stays readable). The gate attaches the version through the
                      detector slug ``gf:<id>@<version>`` (``attach.py``).
retired -> live       ``rollback``: an admin, with a reason of at least 20 characters. The live
                      version becomes retired.
shadow -> draft       ``stop_shadow`` (guardians.edit); approvals are dropped.
shadow/approved/live  ``retire_version`` on request (guardians.edit in the owner group).
 -> retired
====================  ==========================================================================

Every move writes a ``guardian_def_event`` row and a chain record ``guardian_promotion`` (ids,
hashes, integers; the actor as a keyed short hash). No personal data and no float. Allow-list
entries end by date; an expired entry is ignored by the adapter and removed by the daily job
(``jobs/guardian_shadow.py``) with an event.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Mapping
from typing import Any

from supervisor.controls.model import actor_ref
from supervisor.core import rbac
from supervisor.core.canonical import format_ts
from supervisor.core.errors import ConcurrencyError, NotFoundError
from supervisor.evidence.chain import check_no_floats
from supervisor.guardian_factory import attach, bench, caps
from supervisor.guardian_factory.definition import GuardianFactoryError
from supervisor.guardian_factory.store import (
    GuardianDefStore,
    can_edit,
    check_transition,
    require_on,
)

log = logging.getLogger("supervisor.guardian_factory")
TABLE = "guardian_def"
FINDINGS = "guardian_shadow_finding"
DAYS = "guardian_shadow_day"
RECORD_TYPE = "guardian_promotion"
DAY_RECORD = "guardian_shadow_day"
ALLOW_STATES = ("shadow", "approved", "live")
AUTHOR_ACTIONS = ("created", "saved", "new_version", "reset_to_draft", "reopened")


def same_person(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and str(a).strip().casefold() == str(b).strip().casefold()


def _denied(text: str) -> Exception:
    from supervisor.cases.service import PermissionDenied

    return PermissionDenied(text)


def _clean(text: Any, limit: int) -> str:
    s = "".join(c for c in str(text or "") if c >= " " or c in "\n\t").strip()
    return s[:limit]


class Promotion:
    """Shadow and promotion moves on top of :class:`GuardianDefStore` (same tables and chain)."""

    def __init__(self, store: GuardianDefStore, *, today: Any = None) -> None:
        self.store = store
        self._today = today

    # ------------------------------------------------------------------ plumbing
    @property
    def state(self) -> Any:
        return self.store.state

    def now(self) -> dt.datetime:
        return self.store.clock.now()

    def today(self) -> dt.date:
        return self._today() if self._today else self.now().date()

    def _version(self, def_id: str, version: int | None) -> dict[str, Any]:
        rows = self.store._rows(def_id)  # noqa: SLF001
        if not rows:
            raise NotFoundError(f"guardian definition {def_id} does not exist")
        if version is None:
            return rows[-1]
        for r in rows:
            if int(r["version"]) == version:
                return r
        raise NotFoundError(f"guardian definition {def_id} has no version {version}")

    def _body(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return dict(self.store._body(row))  # noqa: SLF001

    def _edit(self, user: Any, row: Mapping[str, Any]) -> str:
        return self.store._need(user, str(row["owner_group"]))  # noqa: SLF001

    def _put(
        self,
        row: Mapping[str, Any],
        *,
        to_state: str | None = None,
        lifecycle: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = self._body(row)
        life = dict(body.get("lifecycle") or {})
        life.update(lifecycle or {})
        if to_state is not None:
            life["state"] = to_state
        body["lifecycle"] = life
        body["updated_at"] = format_ts(self.now())
        changes: dict[str, Any] = {
            "definition_json": json.dumps(body, sort_keys=True, ensure_ascii=False)
        }
        if to_state is not None:
            changes["state"] = to_state
        try:
            stored = dict(
                self.state.update(
                    TABLE,
                    {"def_id": row["def_id"], "version": row["version"]},
                    changes,
                    row["row_version"],
                )
            )
        except ConcurrencyError:
            raise GuardianFactoryError("conflict", "the definition changed; reload it") from None
        attach.bump()
        return stored

    def _chain(
        self,
        action: str,
        row: Mapping[str, Any],
        before: str,
        actor: str,
        extra: Mapping[str, int | str] | None = None,
    ) -> None:
        sink = self.store.evidence_sink
        if sink is None:
            return
        body = self._body(row)
        payload = {
            "def_id": row["def_id"],
            "version": int(row["version"]),
            "action": action,
            "from": before,
            "to": row["state"],
            "def_sha256": bench.def_sha(body),
            "approvals_n": len((body.get("lifecycle") or {}).get("approvals") or []),
            "actor_ref": actor_ref(self.store.settings, actor, "system"),
            "ts": format_ts(self.now()),
            **(extra or {}),
        }
        try:
            check_no_floats(payload)
            sink.record(
                RECORD_TYPE,
                f"guardian_promotion:{row['def_id']}:{row['version']}:{action}:{payload['ts']}",
                payload,
            )
        except Exception:  # noqa: BLE001 - the row and the event are stored; log and go on
            log.exception("guardian promotion chain record failed")

    def _move(
        self,
        row: Mapping[str, Any],
        to_state: str,
        action: str,
        actor: str,
        *,
        lifecycle: Mapping[str, Any] | None = None,
        extra: Mapping[str, int | str] | None = None,
    ) -> dict[str, Any]:
        before = str(row["state"])
        stored = self._put(row, to_state=to_state, lifecycle=lifecycle)
        self.store._event(stored, action, before, actor)  # noqa: SLF001
        self._chain(action, stored, before, actor, extra)
        return stored

    def authors_of(self, row: Mapping[str, Any]) -> set[str]:
        """Who wrote this version: its creator and every actor who created or saved it."""
        out = {str(row.get("created_by") or "").strip().casefold()}
        for e in self.store.tables.query(
            "guardian_def_event",
            {"def_id": row["def_id"]},
        ):
            if int(e["version"]) == int(row["version"]) and e["action"] in AUTHOR_ACTIONS:
                out.add(str(e["actor"]).strip().casefold())
        out.discard("")
        return out

    # ------------------------------------------------------------------ eligibility
    def eligible(self, kind: str, user: Any, owner_group: str) -> bool:
        from supervisor.factory.registry import load_groups
        from supervisor.factory.store import permits

        roles = frozenset(getattr(user, "roles", ()) or ())
        if not rbac.allowed(roles, "guardians.approve"):
            return False
        groups = frozenset(getattr(user, "groups", ()) or ())
        group = owner_group if kind == "owner_lead" else caps.SECURITY_GROUP
        return permits(roles, group, load_groups(), groups)

    # ------------------------------------------------------------------ shadow
    def shadow_started(self, row: Mapping[str, Any]) -> dt.datetime | None:
        best = None
        for e in self.store.tables.query("guardian_def_event", {"def_id": row["def_id"]}):
            if int(e["version"]) == int(row["version"]) and e["action"] == "shadow_started":
                at = e["at"]
                if best is None or at > best:
                    best = at
        return best

    @staticmethod
    def days_of(body: Mapping[str, Any]) -> int:
        n = int((body.get("lifecycle") or {}).get("shadow_days") or 0)
        return min(n, caps.SHADOW_DAYS_MAX) if n > 0 else caps.SHADOW_DAYS_DEFAULT

    def start_shadow(self, def_id: str, user: Any) -> dict[str, Any]:
        """benchmarked -> shadow."""
        require_on(self.store.settings)
        row = self._version(def_id, None)
        actor = self._edit(user, row)
        check_transition(str(row["state"]), "shadow")
        why = self.store.bench_problem(row)
        if why:
            raise GuardianFactoryError("no_passing_run", why)
        days = self.days_of(self._body(row))
        stored = self._move(
            row,
            "shadow",
            "shadow_started",
            actor,
            lifecycle={"approvals": [], "shadow_days": days},
            extra={"shadow_days": days},
        )
        return self.store.view(stored)

    def stop_shadow(self, def_id: str, user: Any) -> dict[str, Any]:
        """shadow -> draft. The findings stay; the approvals are dropped."""
        require_on(self.store.settings)
        row = self._version(def_id, None)
        actor = self._edit(user, row)
        check_transition(str(row["state"]), "draft")
        if row["state"] != "shadow":
            raise GuardianFactoryError("bad_transition", "only a shadow guardian is stopped")
        stored = self._move(row, "draft", "shadow_stopped", actor, lifecycle={"approvals": []})
        return self.store.view(stored)

    def day_rows(self, def_id: str, version: int) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self.state.query(DAYS, {"def_id": def_id, "version": version})]
        return sorted(rows, key=lambda r: str(r["day"]))

    def status(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """The numbers of the shadow panel and of the ``approve`` check (integers)."""
        body = self._body(row)
        def_id, version = str(row["def_id"]), int(row["version"])
        days_total = self.days_of(body)
        started = self.shadow_started(row)
        now = self.now()
        elapsed = 0
        complete = False
        if started is not None:
            seconds = max(0, int((now - started).total_seconds()))
            elapsed = min(days_total, seconds // 86_400)
            complete = seconds >= days_total * 86_400
        days = self.day_rows(def_id, version)
        found = [
            dict(r) for r in self.state.query(FINDINGS, {"def_id": def_id, "version": version})
        ]
        correct = sum(1 for f in found if f.get("reviewed") == "correct")
        false = sum(1 for f in found if f.get("reviewed") == "false")
        reviewed = correct + false
        max_fpr = int((body.get("thresholds") or {}).get("max_fpr_pct", 5))
        rate = (false * 100) // reviewed if reviewed else 0
        would_act = sum(int(r["would_act"]) for r in days)
        problems: list[str] = []
        if started is None:
            problems.append("the shadow run has not started")
        elif not complete:
            problems.append(f"the shadow period is not complete: day {elapsed} of {days_total}")
        if reviewed and rate > max_fpr:
            problems.append(f"the reviewed false rate is {rate} percent; the limit is {max_fpr}")
        if would_act > 0 and reviewed == 0:
            problems.append("no finding is reviewed yet")
        return {
            "state": str(row["state"]),
            "started_at": format_ts(started) if started else None,
            "days_total": days_total,
            "days_elapsed": elapsed,
            "complete": complete,
            "calls_seen": sum(int(r["calls_seen"]) for r in days),
            "would_act": would_act,
            "skipped_budget": sum(int(r["skipped_budget"]) for r in days),
            "findings_n": len(found),
            "reviewed_correct": correct,
            "reviewed_false": false,
            "reviewed_n": reviewed,
            "pending_n": len(found) - reviewed,
            "false_rate_pct": rate,
            "max_fpr_pct": max_fpr,
            "passed": not problems,
            "problems": problems,
            "days": [
                {
                    "day": r["day"],
                    "calls_seen": int(r["calls_seen"]),
                    "would_act": int(r["would_act"]),
                    "skipped_budget": int(r["skipped_budget"]),
                }
                for r in days
            ],
        }

    def check_passed(self, row: Mapping[str, Any]) -> dict[str, Any]:
        st = self.status(row)
        if not st["passed"]:
            nums = (
                f"day {st['days_elapsed']} of {st['days_total']}, calls seen {st['calls_seen']}, "
                f"would act {st['would_act']}, reviewed {st['reviewed_n']} "
                f"(false {st['reviewed_false']}), false rate {st['false_rate_pct']} percent, "
                f"limit {st['max_fpr_pct']} percent"
            )
            raise GuardianFactoryError(
                "shadow_not_passed", "; ".join(st["problems"]) + f" [{nums}]", [dict(st)]
            )
        return st

    # ------------------------------------------------------------------ review list
    def findings(
        self, def_id: str, version: int | None = None, *, pending_only: bool = False
    ) -> list[dict[str, Any]]:
        require_on(self.store.settings)
        row = self._version(def_id, version)
        rows = [
            dict(r)
            for r in self.state.query(FINDINGS, {"def_id": def_id, "version": int(row["version"])})
        ]
        rows.sort(key=lambda r: (str(r["created_at"]), str(r["finding_id"])), reverse=True)
        if pending_only:
            rows = [r for r in rows if not r.get("reviewed")]
        return [
            {
                "finding_id": r["finding_id"],
                "agent_id": r["agent_id"],
                "call_ref": r["call_ref"],
                "stage": r["stage"],
                "finding_code": r["finding_code"],
                "count": int(r["count"]),
                "value_hash": r["value_hash"],
                "would_action": r["would_action"],
                "reviewed": r.get("reviewed"),
                "reviewed_by": r.get("reviewed_by"),
                "created_at": format_ts(r["created_at"])
                if not isinstance(r["created_at"], str)
                else r["created_at"],
            }
            for r in rows[: caps.REVIEW_LIST_MAX]
        ]

    def review(
        self,
        def_id: str,
        finding_id: str,
        mark: Any,
        user: Any,
        allow: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Mark a finding ``correct`` or ``false``. A false mark may add an allow-list entry."""
        require_on(self.store.settings)
        if mark not in caps.REVIEWS:
            raise GuardianFactoryError("bad_mark", "mark: correct or false")
        row = self._version(def_id, None)
        actor = self._edit(user, row)
        f = self.state.get(FINDINGS, {"finding_id": finding_id})
        if f is None or str(f["def_id"]) != def_id:
            raise NotFoundError(f"finding {finding_id} does not exist for {def_id}")
        frow = self._version(def_id, int(f["version"]))
        if frow["state"] != "shadow":
            raise GuardianFactoryError(
                "not_shadow",
                f"version {frow['version']} is {frow['state']}; only a shadow run is reviewed",
            )
        if allow and mark != "false":
            raise GuardianFactoryError("bad_mark", "an allow-list entry goes with a false mark")
        stored = dict(
            self.state.update(
                FINDINGS,
                {"finding_id": finding_id},
                {"reviewed": mark, "reviewed_by": actor},
                f["row_version"],
            )
        )
        out: dict[str, Any] = {"finding_id": finding_id, "reviewed": stored["reviewed"]}
        if allow:
            entry = self.add_allow(
                def_id,
                int(f["version"]),
                allow.get("agent_id") or str(f["agent_id"]),
                allow.get("reason"),
                allow.get("expires"),
                user,
            )
            out["allow"] = entry
        return out

    # ------------------------------------------------------------------ allow-lists
    def add_allow(
        self,
        def_id: str,
        version: int | None,
        agent_id: Any,
        reason: Any,
        expires: Any,
        user: Any,
    ) -> dict[str, Any]:
        require_on(self.store.settings)
        row = self._version(def_id, version)
        actor = self._edit(user, row)
        if row["state"] not in ALLOW_STATES:
            raise GuardianFactoryError(
                "bad_state", "an allow-list entry belongs to a shadow, approved or live version"
            )
        agent = _clean(agent_id, 64)
        why = _clean(reason, caps.REASON_MAX)
        if not agent:
            raise GuardianFactoryError("bad_allow", "agent_id: the agent the entry is for")
        if not why:
            raise GuardianFactoryError("bad_allow", "reason: say why this agent is allowed")
        if not isinstance(expires, str) or not caps.DATE_RE.match(expires):
            raise GuardianFactoryError("bad_expiry", "expires: a date, like 2026-12-31")
        try:
            end = dt.date.fromisoformat(expires)
        except ValueError:
            raise GuardianFactoryError("bad_expiry", "expires: not a real date") from None
        today = self.today()
        if end < today:
            raise GuardianFactoryError("bad_expiry", "expires: the date is in the past")
        if end > today + dt.timedelta(days=caps.ALLOW_MAX_DAYS):
            raise GuardianFactoryError(
                "bad_expiry", f"expires: at most {caps.ALLOW_MAX_DAYS} days from today"
            )
        body = self._body(row)
        entries = list((body.get("lifecycle") or {}).get("allow_list") or [])
        live_entries = [e for e in entries if e["expires"] >= today.isoformat()]
        if any(e["agent_id"] == agent for e in live_entries):
            raise GuardianFactoryError(
                "allow_exists", f"agent {agent} is already on the allow-list"
            )
        if len(live_entries) >= caps.ALLOW_LIST_MAX:
            raise GuardianFactoryError("allow_list_full", "the allow-list is full")
        entry = {"agent_id": agent, "reason": why, "expires": expires}
        # an expired entry of the same agent is replaced by the new one
        entries = [e for e in entries if e["agent_id"] != agent] + [entry]
        stored = self._put(row, lifecycle={"allow_list": entries})
        self.store._event(stored, "allow_added", str(stored["state"]), actor)  # noqa: SLF001
        self._chain(
            "allow_added",
            stored,
            str(stored["state"]),
            actor,
            {"allow_n": len(entries), "days_n": (end - today).days},
        )
        return entry

    def remove_allow(self, def_id: str, version: int | None, agent_id: Any, user: Any) -> int:
        require_on(self.store.settings)
        row = self._version(def_id, version)
        actor = self._edit(user, row)
        body = self._body(row)
        entries = list((body.get("lifecycle") or {}).get("allow_list") or [])
        keep = [e for e in entries if e["agent_id"] != str(agent_id)]
        if len(keep) == len(entries):
            raise NotFoundError(f"agent {agent_id} is not on the allow-list")
        stored = self._put(row, lifecycle={"allow_list": keep})
        self.store._event(stored, "allow_removed", str(stored["state"]), actor)  # noqa: SLF001
        self._chain("allow_removed", stored, str(stored["state"]), actor, {"allow_n": len(keep)})
        return len(keep)

    def allow_view(self, row: Mapping[str, Any]) -> list[dict[str, Any]]:
        today = self.today().isoformat()
        return [
            {**e, "expired": e["expires"] < today}
            for e in (self._body(row).get("lifecycle") or {}).get("allow_list") or []
        ]

    def expire_allow_entries(self) -> int:
        """The daily job: remove every expired allow-list entry, one event per version."""
        removed = 0
        today = self.today().isoformat()
        for r in [dict(x) for x in self.state.query(TABLE, {})]:
            if r["state"] not in ALLOW_STATES:
                continue
            entries = list((self._body(r).get("lifecycle") or {}).get("allow_list") or [])
            keep = [e for e in entries if e["expires"] >= today]
            if len(keep) == len(entries):
                continue
            stored = self._put(r, lifecycle={"allow_list": keep})
            n = len(entries) - len(keep)
            self.store._event(stored, "allow_expired", str(stored["state"]), "system:expiry")  # noqa: SLF001
            self._chain(
                "allow_expired", stored, str(stored["state"]), "system:expiry", {"expired_n": n}
            )
            removed += n
        return removed

    # ------------------------------------------------------------------ approval
    def approve(self, def_id: str, user: Any, kind: str | None = None) -> dict[str, Any]:
        """One approval of a shadow version; the second one, by another person, approves it."""
        require_on(self.store.settings)
        actor = self.store._actor(user)  # noqa: SLF001
        row = self._version(def_id, None)
        if row["state"] != "shadow":
            check_transition(str(row["state"]), "approved")  # bad_transition for other states
            raise GuardianFactoryError("not_shadow", f"a {row['state']} version is not approved")
        if kind is not None and kind not in caps.APPROVAL_KINDS:
            raise GuardianFactoryError(
                "bad_kind", f"kind must be one of {', '.join(caps.APPROVAL_KINDS)}"
            )
        body = self._body(row)
        given = list((body.get("lifecycle") or {}).get("approvals") or [])
        have = {a.get("kind") for a in given}
        owner = str(row["owner_group"])
        wanted = [kind] if kind else [k for k in caps.APPROVAL_KINDS if k not in have]
        mine = [k for k in wanted if self.eligible(k, user, owner)]
        if not mine:
            raise GuardianFactoryError(
                "not_eligible",
                "owner_lead is the approver of the owner group (or an admin); platform_security "
                "is a member of the platform group (or an admin)",
            )
        if actor.casefold() in self.authors_of(row):
            raise GuardianFactoryError(
                "author_cannot_approve", "the author of a version cannot approve it"
            )
        if any(same_person(a.get("by"), actor) for a in given):
            raise GuardianFactoryError(
                "same_person", "the second approval needs a different person from the first"
            )
        pick = next((k for k in mine if k not in have), None)
        if pick is None:
            raise GuardianFactoryError("already_approved", f"the {mine[0]} approval is given")
        self.check_passed(row)
        group = owner if pick == "owner_lead" else caps.SECURITY_GROUP
        approval = {
            "by": actor[: caps.USER_MAX],
            "group": group,
            "at": self.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "kind": pick,
        }
        approvals = [*given, approval]
        done = {a.get("kind") for a in approvals} >= set(caps.APPROVAL_KINDS)
        if done:
            stored = self._move(
                row,
                "approved",
                "approved",
                actor,
                lifecycle={"approvals": approvals},
                extra={"kind_n": caps.APPROVAL_KINDS.index(pick) + 1},
            )
        else:
            stored = self._put(row, lifecycle={"approvals": approvals})
            self.store._event(stored, "approval", "shadow", actor)  # noqa: SLF001
            self._chain(
                "approval", stored, "shadow", actor, {"kind_n": caps.APPROVAL_KINDS.index(pick) + 1}
            )
        return {**self.store.view(stored), "approval": approval, "approved": done}

    # ------------------------------------------------------------------ live, rollback, retire
    def live_row(self, def_id: str) -> dict[str, Any] | None:
        live = [r for r in self.store._rows(def_id) if r["state"] == "live"]  # noqa: SLF001
        return live[-1] if live else None

    def go_live(self, def_id: str, user: Any) -> dict[str, Any]:
        """approved -> live; the previous live version becomes retired."""
        require_on(self.store.settings)
        actor = self.store._actor(user)  # noqa: SLF001
        row = self._version(def_id, None)
        check_transition(str(row["state"]), "live")
        if row["state"] != "approved":
            raise GuardianFactoryError("not_approved", f"a {row['state']} version does not go live")
        if not self.eligible("owner_lead", user, str(row["owner_group"])):
            raise GuardianFactoryError(
                "not_eligible", "only the owner group's approver or an admin sets a version live"
            )
        kinds = {
            a.get("kind") for a in (self._body(row).get("lifecycle") or {}).get("approvals", [])
        }
        missing = [k for k in caps.APPROVAL_KINDS if k not in kinds]
        if missing:
            raise GuardianFactoryError(
                "approvals_missing", "the approvals are not complete: " + ", ".join(missing)
            )
        prev = self.live_row(def_id)
        if prev is not None and int(prev["version"]) != int(row["version"]):
            self._move(
                prev,
                "retired",
                "retired",
                actor,
                extra={"superseded_by": int(row["version"])},
            )
        stored = self._move(
            row,
            "live",
            "live",
            actor,
            extra={"slug_version": int(row["version"])},
        )
        return {
            **self.store.view(stored),
            "binding": {
                "slug": attach.gf_slug(def_id, int(stored["version"])),
                "agents": self._body(stored).get("scope", {}).get("agents", "*"),
            },
        }

    def rollback(
        self, def_id: str, user: Any, reason: Any, to_version: int | None = None
    ) -> dict[str, Any]:
        """An admin sets an earlier version live again; the live one becomes retired."""
        require_on(self.store.settings)
        actor = self.store._actor(user)  # noqa: SLF001
        if "admin" not in frozenset(getattr(user, "roles", ()) or ()):
            raise GuardianFactoryError("not_admin", "only an admin rolls a guardian back")
        why = _clean(reason, caps.REASON_MAX)
        if len(why) < caps.REASON_MIN:
            raise GuardianFactoryError(
                "reason_needed",
                f"a rollback needs a reason of at least {caps.REASON_MIN} characters",
            )
        rows = self.store._rows(def_id)  # noqa: SLF001
        if not rows:
            raise NotFoundError(f"guardian definition {def_id} does not exist")
        cur = self.live_row(def_id)
        was_live = {
            int(e["version"])
            for e in self.store.tables.query("guardian_def_event", {"def_id": def_id})
            if e["action"] in ("live", "rolled_back") and e["to_state"] == "live"
        }
        pool = [
            r
            for r in rows
            if r["state"] == "retired"
            and int(r["version"]) in was_live
            and (cur is None or int(r["version"]) < int(cur["version"]))
        ]
        if to_version is not None:
            target = next((r for r in rows if int(r["version"]) == to_version), None)
            if target is None or target not in pool:
                raise GuardianFactoryError(
                    "not_rollbackable", "only a retired version that was live can be set live again"
                )
        elif pool:
            target = pool[-1]
        else:
            raise GuardianFactoryError(
                "no_previous_version", "there is no earlier live version to roll back to"
            )
        if cur is not None:
            self._move(cur, "retired", "rolled_back", actor, extra={"reason_len": len(why)})
        stored = self._move(target, "live", "rolled_back", actor, extra={"reason_len": len(why)})
        return self.store.view(stored)

    def retire_version(self, def_id: str, version: int | None, user: Any) -> dict[str, Any]:
        """Retire a shadow, approved or live version on request."""
        require_on(self.store.settings)
        row = self._version(def_id, version)
        actor = self._edit(user, row)
        check_transition(str(row["state"]), "retired")
        stored = self._move(row, "retired", "retired", actor)
        return self.store.view(stored)

    # ------------------------------------------------------------------ summary for the panels
    def summary(self, def_id: str, user: Any | None = None) -> dict[str, Any]:
        row = self._version(def_id, None)
        body = self._body(row)
        approvals = list((body.get("lifecycle") or {}).get("approvals") or [])
        have = {a.get("kind") for a in approvals}
        live = self.live_row(def_id)
        out: dict[str, Any] = {
            "state": str(row["state"]),
            "version": int(row["version"]),
            "live_version": int(live["version"]) if live else None,
            "slug": attach.gf_slug(def_id, int(row["version"])),
            "approvals": approvals,
            "missing": [k for k in caps.APPROVAL_KINDS if k not in have],
            "allow_list": self.allow_view(row),
            "shadow": self.status(row) if row["state"] in ("shadow", "approved", "live") else None,
            "prior": [
                {"version": int(r["version"]), "state": str(r["state"])}
                for r in self.store._rows(def_id)  # noqa: SLF001
                if r["state"] == "retired"
            ],
        }
        if user is not None:
            out["can"] = {
                "edit": self._can_edit(user, row),
                "owner_lead": self.eligible("owner_lead", user, str(row["owner_group"])),
                "platform_security": self.eligible(
                    "platform_security", user, str(row["owner_group"])
                ),
                "admin": "admin" in frozenset(getattr(user, "roles", ()) or ()),
            }
        return out

    def _can_edit(self, user: Any, row: Mapping[str, Any]) -> bool:
        roles = frozenset(getattr(user, "roles", ()) or ())
        return rbac.allowed(roles, "guardians.edit") and can_edit(user, str(row["owner_group"]))

    def annotate(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Add ``shadow_days`` (days elapsed, only in state shadow) and ``live_version`` (the live
        version of the id, if any) to the rows of the registry list."""
        lives: dict[str, int] = {}
        for r in self.state.query(TABLE, {"state": "live"}):
            lives[str(r["def_id"])] = max(lives.get(str(r["def_id"]), 0), int(r["version"]))
        for g in rows:
            g["live_version"] = lives.get(str(g["id"]))
            g["shadow_days"] = None
            if g["state"] == "shadow":
                row = self._version(str(g["id"]), int(g["version"]))
                g["shadow_days"] = self.status(row)["days_elapsed"]
        return rows

    # ------------------------------------------------------------------ the daily job
    def close_days(self) -> int:
        """Write one ``guardian_shadow_day`` chain record per closed day (before today) that has
        none yet. Counts only. Returns the number of records."""
        sink = self.store.evidence_sink
        today = self.today().isoformat()
        n = 0
        for r in [dict(x) for x in self.state.query(DAYS, {})]:
            if r["day"] >= today or _truthy(r.get("chained")):
                continue
            if sink is not None:
                found = [
                    dict(f)
                    for f in self.state.query(
                        FINDINGS, {"def_id": r["def_id"], "version": r["version"]}
                    )
                    if str(format_ts(f["created_at"]))[:10] == r["day"]
                ]
                payload = {
                    "def_id": r["def_id"],
                    "version": int(r["version"]),
                    "day": r["day"],
                    "calls_seen": int(r["calls_seen"]),
                    "would_act": int(r["would_act"]),
                    "skipped_budget": int(r["skipped_budget"]),
                    "findings_n": int(r["findings_n"]),
                    "reviewed_correct_n": sum(1 for f in found if f.get("reviewed") == "correct"),
                    "reviewed_false_n": sum(1 for f in found if f.get("reviewed") == "false"),
                    "ts": format_ts(self.now()),
                }
                try:
                    check_no_floats(payload)
                    sink.record(
                        DAY_RECORD,
                        f"guardian_shadow_day:{r['def_id']}:{r['version']}:{r['day']}",
                        payload,
                    )
                except Exception:  # noqa: BLE001
                    log.exception("guardian_shadow_day chain record failed")
                    continue
            self.state.update(
                DAYS,
                {"def_id": r["def_id"], "version": r["version"], "day": r["day"]},
                {"chained": True},
                r["row_version"],
            )
            n += 1
        return n


def _truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true")
    return bool(v)
