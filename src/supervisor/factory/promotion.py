"""Promotion of a factory agent version (WP-F3, flag ``AGENT_FACTORY_GATE``).

States: ``draft -> tested -> approved -> live -> retired`` (``store.TRANSITIONS`` is the wall; this
module holds the conditions). A version is immutable once it leaves ``draft``: only
``lifecycle.state`` and ``lifecycle.approvals`` change.

====================  =========================================================================
move                  condition
====================  =========================================================================
draft -> tested       a ``full`` gate run of this exact version and definition sha passed
                      (``mark_tested``, called by the gate when the run ends)
tested -> approved    ``submit`` first (no unreferenced checklist item); then the approvals the
                      change needs (``required_approvals``); an approver is never the author;
                      a high-tier agent needs ``owner_lead`` and ``second_line`` from two
                      different people (``same_person``)
approved -> live      ``activate``; the previous live version of the agent id becomes retired
live -> retired       by ``activate`` of the next version, by ``retire`` or by ``rollback``
retired -> live       ``rollback`` only: an admin, with a reason; the live version becomes retired
tested/approved ->    ``reject`` (reason of at least 20 characters), ``reopen`` by the author, a
draft                 failed ``full`` gate run, or a definition that differs from the tested sha
====================  =========================================================================

Every move writes a ``factory_agent_event`` row and a chain record ``factory_promotion`` (ids,
hashes, integers; the actor as a keyed short hash). No personal data and no float.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from supervisor.core.canonical import format_ts
from supervisor.evidence.chain import check_no_floats
from supervisor.factory import caps, linter
from supervisor.factory.store import (
    FactoryError,
    FactoryStore,
    _version_key,
    definition_sha256,
    permits,
)
from supervisor.onboard.agent_log import clean

log = logging.getLogger("supervisor.factory")
RECORD_TYPE = "factory_promotion"
RUN_TABLE = "gate_run"
APPROVER_ROLES = ("approver", "admin")
# A change of any of these re-opens the full approval (plan WP-F3).
CRITICAL_KEYS = ("tools", "guardians", "output_schema")


@dataclass(frozen=True)
class Actor:
    """Who acts: user id, roles and (optional) factory groups."""

    user_id: str
    roles: frozenset[str] = field(default_factory=frozenset)
    groups: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles


def actor_of(me: Any) -> Actor:
    return Actor(
        str(me.user_id),
        frozenset(getattr(me, "roles", ()) or ()),
        frozenset(getattr(me, "groups", ()) or ()),
    )


def same_person(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and str(a).strip().casefold() == str(b).strip().casefold()


def actor_ref(user: str) -> str:
    return "p-" + hashlib.sha256(user.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------------------ tier and change


def tier_of(defn: Mapping[str, Any]) -> str:
    """``high`` for the model, cybersecurity and legal_compliance dimensions and for any agent with
    a ``high`` severity item; else ``standard``."""
    if defn.get("dimension_id") in caps.HIGH_TIER_DIMENSIONS:
        return "high"
    if any(c.get("severity") == "high" for c in defn.get("checklist") or []):
        return "high"
    return "standard"


def _norm(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def classify_change(old: Mapping[str, Any] | None, new: Mapping[str, Any]) -> str:
    """``critical`` when tools, guardians, harness permissions, the output schema or the tier
    differ from ``old``; ``content`` when only other fields (instructions, checklist, ...) differ;
    ``none`` when they are the same; ``new`` when there is no ``old``."""
    if old is None:
        return "new"
    perm = lambda d: (d.get("harness") or {}).get("hitl", {}).get("permissions", [])  # noqa: E731
    if any(_norm(old.get(k)) != _norm(new.get(k)) for k in CRITICAL_KEYS):
        return "critical"
    if _norm(perm(old)) != _norm(perm(new)) or tier_of(old) != tier_of(new):
        return "critical"
    return "none" if definition_sha256(old) == definition_sha256(new) else "content"


def baseline_row(store: FactoryStore, row: Mapping[str, Any]) -> dict[str, Any] | None:
    """The newest earlier version of the agent that is live or has been live."""
    best = None
    for v in store.versions(row["id"]):
        if _version_key(v["version"]) >= _version_key(row["version"]):
            continue
        was_live = v["state"] == "live" or any(
            e["kind"] == "live" for e in store.events(row["id"], v["version"])
        )
        if was_live:
            best = v
    return best


def required_approvals(store: FactoryStore, row: Mapping[str, Any]) -> dict[str, Any]:
    defn = row["definition"]
    base = baseline_row(store, row)
    change = classify_change(base["definition"] if base else None, defn)
    tier = tier_of(defn)
    if change in ("content", "none"):
        kinds = ["owner_lead"]  # instructions or checklist only: re-test, then the owner
    elif tier == "high":
        kinds = ["owner_lead", "second_line"]
    else:
        kinds = ["owner_lead"]
    return {
        "kinds": kinds,
        "change": change,
        "tier": tier,
        "baseline": base["version"] if base else "",
    }


def authors_of(store: FactoryStore, row: Mapping[str, Any]) -> set[str]:
    """Who wrote this version: its creator and everyone who saved or created it."""
    out = {str(row.get("created_by") or "").casefold()}
    for e in store.events(row["id"], row["version"]):
        if e["kind"] in ("created", "saved", "new_version", "helper_accepted"):
            out.add(str(e["actor_ref"]).casefold())
    out.discard("")
    return out


def eligible(kind: str, actor: Actor, owner_group: str, store: FactoryStore) -> bool:
    if not (actor.roles & set(APPROVER_ROLES)):
        return False
    if kind == "owner_lead":
        return permits(actor.roles, owner_group, store.groups, actor.groups)
    return any(permits(actor.roles, g, store.groups, actor.groups) for g in caps.SECOND_LINE_GROUPS)


# ------------------------------------------------------------------------------ helpers


def _chain(
    sink: Any,
    store: FactoryStore,
    action: str,
    row: Mapping[str, Any],
    before: str,
    after: str,
    who: str,
    extra: Mapping[str, Any] | None = None,
) -> None:
    if sink is None:
        return
    now = store.clock.now()
    payload = {
        "factory_agent_id": row["id"],
        "version": row["version"],
        "action": action,
        "from": before,
        "to": after,
        "actor_ref": actor_ref(who),
        "definition_sha256": definition_sha256(row["definition"]),
        "approvals_n": len((row["definition"].get("lifecycle") or {}).get("approvals") or []),
        "ts": format_ts(now),
        **(extra or {}),
    }
    try:
        check_no_floats(payload)
        sink.record(
            RECORD_TYPE,
            f"factory_promotion:{row['id']}:{row['version']}:{action}:{format_ts(now)}",
            payload,
        )
    except Exception:  # noqa: BLE001 - the row and the event are stored; log and go on
        log.exception("factory promotion chain record failed")


def _need(store: FactoryStore, agent_id: str, version: str) -> dict[str, Any]:
    row = store.get(agent_id, version)
    if row is None:
        raise FactoryError("not_found", f"agent {agent_id} version {version} does not exist")
    return row


def runs_of(store: FactoryStore, agent_id: str, version: str | None = None) -> list[dict[str, Any]]:
    where: dict[str, Any] = {"agent_id": agent_id}
    if version is not None:
        where["version"] = version
    rows = [dict(r) for r in store.state.query(RUN_TABLE, where)]
    return sorted(rows, key=lambda r: (str(r["started_at"]), str(r["run_id"])))


def passed_full_run(store: FactoryStore, row: Mapping[str, Any]) -> dict[str, Any] | None:
    """The newest ``full`` run of this version that passed, if it tested this exact definition."""
    sha = definition_sha256(row["definition"])
    for r in reversed(runs_of(store, row["id"], row["version"])):
        if r["kind"] == "full" and r["status"] == "done" and r["verdict"] == "pass":
            return r if r["definition_sha256"] == sha else None
        if r["kind"] == "full" and r["status"] == "done":
            return None  # the newest finished full run did not pass
    return None


def _guard_sha(store: FactoryStore, row: Mapping[str, Any], who: str, sink: Any) -> dict[str, Any]:
    """The tested definition must be the stored one; else the version goes back to draft."""
    run = passed_full_run(store, row)
    if run is None:
        if row["state"] in ("tested", "approved"):
            new = store.transition(
                row,
                "draft",
                who,
                "definition_changed",
                "the definition differs from the tested sha",
            )
            _chain(sink, store, "definition_changed", new, row["state"], "draft", who)
        raise FactoryError(
            "definition_changed",
            "the definition is not the one the passed full gate run tested; the version is a draft "
            "again: run the full gate again",
        )
    return run


# ------------------------------------------------------------------------------ gate hooks


def mark_tested(
    store: FactoryStore, sink: Any, row: Mapping[str, Any], run: Mapping[str, Any]
) -> dict[str, Any]:
    """draft -> tested, only by a passed full run of this version and definition sha."""
    if (
        run["kind"] != "full"
        or run["verdict"] != "pass"
        or run["status"] != "done"
        or run["version"] != row["version"]
        or run["agent_id"] != row["id"]
        or run["definition_sha256"] != definition_sha256(row["definition"])
    ):
        raise FactoryError(
            "gate_not_passed", "only a passed full gate run of this version and definition tests it"
        )
    who = f"gate:{run['run_id']}"
    new = store.transition(row, "tested", who, "tested", f"full gate run {run['run_id']} passed")
    _chain(
        sink,
        store,
        "tested",
        new,
        "draft",
        "tested",
        who,
        {"gate_run_id": run["run_id"], "report_sha256": run.get("report_sha256") or ""},
    )
    return new


def gate_failed(
    store: FactoryStore, sink: Any, row: Mapping[str, Any], run: Mapping[str, Any]
) -> dict[str, Any]:
    """A failed full run sends a tested or approved version back to draft."""
    if row["state"] not in ("tested", "approved"):
        return dict(row)
    who = f"gate:{run['run_id']}"
    new = store.transition(
        row, "draft", who, "reopened", f"full gate run {run['run_id']} failed", approvals=[]
    )
    _chain(
        sink, store, "gate_failed", new, row["state"], "draft", who, {"gate_run_id": run["run_id"]}
    )
    return new


# ------------------------------------------------------------------------------ people's moves


def unreferenced(row: Mapping[str, Any]) -> list[str]:
    return [
        i.message.split()[2]
        for i in linter.lint_definition(row["definition"])
        if i.rule == "checklist_unreferenced"
    ]


def submit(store: FactoryStore, sink: Any, row: Mapping[str, Any], actor: Actor) -> dict[str, Any]:
    if row["state"] != "tested":
        raise FactoryError(
            "not_tested", f"a {row['state']} version cannot be submitted; it must be tested"
        )
    issues = linter.lint_definition(row["definition"])
    if linter.has_errors(issues) or not linter.is_ready(issues):
        raise FactoryError(
            "lint_not_ready",
            "the instructions must name every checklist item before approval: "
            + (", ".join(unreferenced(row)) or "fix the lint errors"),
        )
    run = _guard_sha(store, row, actor.user_id, sink)
    store.record_event(
        row["id"],
        row["version"],
        "submitted",
        actor.user_id,
        f"for approval; gate run {run['run_id']}",
    )
    need = required_approvals(store, row)
    _chain(
        sink,
        store,
        "submitted",
        row,
        "tested",
        "tested",
        actor.user_id,
        {"gate_run_id": run["run_id"], "required_n": len(need["kinds"])},
    )
    return dict(store.get(row["id"], row["version"]) or row)


def is_submitted(store: FactoryStore, row: Mapping[str, Any]) -> bool:
    """A ``submitted`` event after the newest ``tested`` event of this version."""
    last = ""
    for e in store.events(row["id"], row["version"]):
        if e["kind"] == "tested":
            last = ""
        elif e["kind"] == "submitted":
            last = "submitted"
    return last == "submitted"


def approvals_of(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list((row["definition"].get("lifecycle") or {}).get("approvals") or [])


def approve(
    store: FactoryStore,
    sink: Any,
    row: Mapping[str, Any],
    actor: Actor,
    kind: str,
    note: str = "",
) -> dict[str, Any]:
    if kind not in caps.APPROVAL_KINDS:
        raise FactoryError(
            "bad_kind", f"approval kind must be one of {', '.join(caps.APPROVAL_KINDS)}"
        )
    if row["state"] != "tested":
        raise FactoryError(
            "not_tested", f"only a tested version is approved; this one is {row['state']}"
        )
    if not is_submitted(store, row):
        raise FactoryError("not_submitted", "submit the version for approval first")
    _guard_sha(store, row, actor.user_id, sink)
    need = required_approvals(store, row)
    if kind not in need["kinds"]:
        raise FactoryError(
            "kind_not_required",
            f"this change needs {' and '.join(need['kinds'])}, not {kind}",
        )
    given = approvals_of(row)
    if any(a["role"] == kind for a in given):
        raise FactoryError("already_approved", f"the {kind} approval is already given")
    if actor.user_id.casefold() in authors_of(store, row):
        raise FactoryError("author_cannot_approve", "the author of a version cannot approve it")
    if any(same_person(a["by"], actor.user_id) for a in given):
        raise FactoryError(
            "same_person", "the second approval needs a different person from the first"
        )
    if not eligible(kind, actor, row["owner_group"], store):
        raise FactoryError(
            "not_eligible",
            "owner_lead is the approver of the owner group (or an admin); second_line is a "
            "member of the platform group (or an admin)",
        )
    at = store.clock.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    approval = {
        "by": actor.user_id[:120],
        "role": kind,
        "at": at,
        "note": clean(note, caps.NOTE_MAX),
    }
    updated = store.add_approval(row, approval, actor.user_id, f"{kind} approved")
    _chain(
        sink,
        store,
        "approval",
        updated,
        "tested",
        "tested",
        actor.user_id,
        {"kind_n": caps.APPROVAL_KINDS.index(kind) + 1},
    )
    have = {a["role"] for a in approvals_of(updated)}
    if set(need["kinds"]) <= have:
        done = store.transition(
            updated,
            "approved",
            actor.user_id,
            "approved",
            "all approvals given: " + ", ".join(need["kinds"]),
        )
        _chain(sink, store, "approved", done, "tested", "approved", actor.user_id)
        return done
    return updated


def reject(
    store: FactoryStore, sink: Any, row: Mapping[str, Any], actor: Actor, reason: str
) -> dict[str, Any]:
    reason = (reason or "").strip()
    if len(reason) < caps.REJECT_REASON_MIN:
        raise FactoryError(
            "reason_too_short",
            f"a rejection needs a reason of at least {caps.REJECT_REASON_MIN} characters",
        )
    if row["state"] not in ("tested", "approved"):
        raise FactoryError("bad_transition", f"a {row['state']} version cannot be rejected")
    if not (
        eligible("owner_lead", actor, row["owner_group"], store)
        or eligible("second_line", actor, row["owner_group"], store)
    ):
        raise FactoryError(
            "not_eligible",
            "only an approver of the owner group, the second line or an admin rejects",
        )
    new = store.transition(
        row, "draft", actor.user_id, "rejected", clean(reason, caps.NOTE_MAX), approvals=[]
    )
    _chain(
        sink,
        store,
        "reject",
        new,
        row["state"],
        "draft",
        actor.user_id,
        {"reason_len": len(reason)},
    )
    return new


def reopen(
    store: FactoryStore, sink: Any, row: Mapping[str, Any], actor: Actor, reason: str
) -> dict[str, Any]:
    """The author (or an editor of the group) takes a tested or approved version back to draft."""
    reason = (reason or "").strip()
    if len(reason) < caps.REASON_MIN:
        raise FactoryError(
            "reason_needed", f"a reopen needs a reason of at least {caps.REASON_MIN} characters"
        )
    if row["state"] not in ("tested", "approved"):
        raise FactoryError("bad_transition", f"a {row['state']} version cannot be reopened")
    if not permits(actor.roles, row["owner_group"], store.groups, actor.groups):
        raise FactoryError("not_eligible", "your role may not edit the agents of this group")
    new = store.transition(
        row, "draft", actor.user_id, "reopened", clean(reason, caps.NOTE_MAX), approvals=[]
    )
    _chain(sink, store, "reopen", new, row["state"], "draft", actor.user_id)
    return new


def activate(
    store: FactoryStore, sink: Any, row: Mapping[str, Any], actor: Actor
) -> dict[str, Any]:
    if row["state"] != "approved":
        raise FactoryError(
            "not_approved", f"only an approved version goes live; this one is {row['state']}"
        )
    run = _guard_sha(store, row, actor.user_id, sink)
    if not eligible("owner_lead", actor, row["owner_group"], store):
        raise FactoryError(
            "not_eligible", "only the owner group's approver or an admin sets a version live"
        )
    need = required_approvals(store, row)
    have = {a["role"] for a in approvals_of(row)}
    if not set(need["kinds"]) <= have:
        raise FactoryError(
            "approvals_missing",
            "the approvals are not complete: " + ", ".join(sorted(set(need["kinds"]) - have)),
        )
    prev = store.live_version(row["id"])
    if prev is not None and prev["version"] != row["version"]:
        old = store.transition(
            prev, "retired", actor.user_id, "retired", f"superseded by version {row['version']}"
        )
        _chain(sink, store, "retire_previous", old, "live", "retired", actor.user_id)
    new = store.transition(row, "live", actor.user_id, "live", f"live; gate run {run['run_id']}")
    _chain(
        sink,
        store,
        "live",
        new,
        "approved",
        "live",
        actor.user_id,
        {"gate_run_id": run["run_id"], "report_sha256": run.get("report_sha256") or ""},
    )
    return new


def _was_live(store: FactoryStore, agent_id: str, version: str) -> bool:
    return any(e["kind"] == "live" for e in store.events(agent_id, version))


def rollback_target(store: FactoryStore, agent_id: str) -> dict[str, Any] | None:
    """The newest retired version, older than the live one, that was live before."""
    cur = store.live_version(agent_id)
    older = [
        r
        for r in store.versions(agent_id)
        if r["state"] == "retired"
        and _was_live(store, agent_id, r["version"])
        and (cur is None or _version_key(r["version"]) < _version_key(cur["version"]))
    ]
    return older[-1] if older else None


def rollback(
    store: FactoryStore,
    sink: Any,
    agent_id: str,
    actor: Actor,
    reason: str,
    to_version: str = "",
) -> dict[str, Any]:
    """An admin sets the previous version live again. The live version becomes retired (and stays
    readable). ``to_version`` empty = the newest retired version that was live before."""
    if not actor.is_admin:
        raise FactoryError("not_admin", "only an admin rolls an agent back")
    reason = (reason or "").strip()
    if len(reason) < caps.REASON_MIN:
        raise FactoryError(
            "reason_needed", f"a rollback needs a reason of at least {caps.REASON_MIN} characters"
        )
    rows = store.versions(agent_id)
    if not rows:
        raise FactoryError("not_found", f"agent {agent_id} does not exist")
    cur = store.live_version(agent_id)
    if to_version:
        target = next((r for r in rows if r["version"] == to_version), None)
    else:
        target = rollback_target(store, agent_id)
    if target is None:
        raise FactoryError(
            "no_previous_version", "there is no earlier live version to roll back to"
        )
    if target["state"] != "retired" or not _was_live(store, agent_id, target["version"]):
        raise FactoryError(
            "not_rollbackable", "only a retired version that was live can be set live again"
        )
    if cur is not None:
        store.transition(
            cur,
            "retired",
            actor.user_id,
            "rolled_back",
            f"rolled back to {target['version']}: {clean(reason, 200)}",
        )
    new = store.transition(
        target, "live", actor.user_id, "rolled_back", f"live again: {clean(reason, 200)}"
    )
    _chain(
        sink, store, "rollback", new, "retired", "live", actor.user_id, {"reason_len": len(reason)}
    )
    return new


def summary(store: FactoryStore, row: Mapping[str, Any]) -> dict[str, Any]:
    """What the promotion panel shows: gate result, required and given approvals, next step."""
    run = passed_full_run(store, row)
    need = required_approvals(store, row)
    given = approvals_of(row)
    have = {a["role"] for a in given}
    return {
        "state": row["state"],
        "tier": need["tier"],
        "change": need["change"],
        "baseline": need["baseline"],
        "required": need["kinds"],
        "missing": [k for k in need["kinds"] if k not in have],
        "approvals": given,
        "submitted": is_submitted(store, row) if row["state"] == "tested" else False,
        "passed_run": run["run_id"] if run else "",
        "unreferenced": unreferenced(row),
        "was_live": _was_live(store, row["id"], row["version"]),
    }


__all__ = [
    "Actor",
    "actor_of",
    "approve",
    "activate",
    "classify_change",
    "gate_failed",
    "mark_tested",
    "reject",
    "reopen",
    "required_approvals",
    "rollback",
    "rollback_target",
    "submit",
    "summary",
    "tier_of",
]
