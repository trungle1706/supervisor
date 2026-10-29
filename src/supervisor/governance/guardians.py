"""Per-system guardian bindings and the mandatory floor (WP-S1, docs/guardian-bindings.md).

A product owner may switch a guardian feature off for the agents of one AI system. The switch
only narrows. Effective state of a feature for an agent::

    effective = instance has it on (flags, config/detectors.yaml, the agent's policy override)
                AND (no off binding OR the slug is in the system's guardian floor)

* No row means on. With the flag off, or with no off row, nothing here changes any engine.
* A binding never turns on what the instance has off: the engines only ever receive a set of
  slugs to switch off, and they add it to what they already switch off.
* The floor is read from ``RulesService.guardian_floor`` every time it is needed; it is never
  copied. A floor slug cannot be set off (HTTP 400), and a floor added after an off row was
  written overrides that row at resolution time.
* The gate rules (``policy_rules``) are never bindable.
* An agent on several systems loses a feature only when every system has it off and none holds
  it in its floor. An agent on no system is unchanged.

Two parts: :class:`GuardianService` (reads and writes the table, one ``binding_change`` chain
record per change: ids, enums and a reason hash, no text) and :class:`GuardianNarrower` (a read
only, cached lookup the engines call: ``off(agent_id)``). Neither imports a database driver.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from supervisor.controls.model import actor_ref
from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import ConcurrencyError, NotFoundError
from supervisor.governance.model import SystemsError, check_system_id, check_user, ensure_on

log = logging.getLogger("supervisor.governance")

STATES = ("on", "off")
MAX_REASON = 500
# WP-P2 (phase 8, CONSOLE_STATE_ACTIONS): a switch-off on a system in one of these stages, or at
# these risk levels, or classed high risk, needs a second person.
LIVE_STAGES = ("deployment", "operation", "re_evaluation")
SECOND_PERSON_RISK = ("high", "prohibited")

# Feature slugs that are not detectors. Detector slugs are the keys of config/detectors.yaml.
SESSION = "session_monitor"
JUDGE_SLUGS = ("judge_t2_sample", "judge_challenger")
MONITOR_SLUGS = ("monitor_quality", "monitor_fairness", "monitor_split_payment", "monitor_drift")
NEVER_BINDABLE = frozenset({"policy_rules"})  # the gate rules block; a person never switches them
CACHE_TTL_S = 5.0

_generation = 0  # bumped by every write in this process, so a narrower never serves a stale set


def _on(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)


class GuardianOffError(SystemsError):
    """A refused switch-off step. The message starts with a short code (HTTP 400)."""


def state_actions_on(settings: Any) -> bool:
    return bool(getattr(settings, "console_state_actions", False))


def needs_second_person(system: Mapping[str, Any]) -> bool:
    """True when the system is live (deployment, operation, re-evaluation), has a high risk
    level, or is classed high risk under Decision 33."""
    return (
        str(system.get("lifecycle_stage")) in LIVE_STAGES
        or str(system.get("risk_level")) in SECOND_PERSON_RISK
        or str(system.get("decision33_class")) == "high_risk"
    )


def bump() -> None:
    """Drop every narrower cache in this process. Called after anything that can change what an
    agent's systems resolve to: a binding write, a rules run (the floor), a link, an unlink."""
    global _generation
    _generation += 1


def guardian_bindings_on(settings: Any) -> bool:
    return bool(
        getattr(settings, "guardian_bindings_enabled", False)
        and getattr(settings, "governance_enabled", False)
    )


def ensure_bindings_on(settings: Any) -> None:
    ensure_on(settings)
    if not getattr(settings, "guardian_bindings_enabled", False):
        raise SystemsError("guardian bindings are off (GUARDIAN_BINDINGS_ENABLED=1 turns them on)")


def detector_entries(settings: Any) -> dict[str, bool]:
    """``slug -> enabled`` from the detector file; empty when it cannot be read."""
    try:
        doc = yaml.safe_load(Path(settings.detectors_config).read_text(encoding="utf-8")) or {}
        return {
            str(k): bool((v or {}).get("enabled", True))
            for k, v in (doc.get("detectors") or {}).items()
        }
    except (OSError, yaml.YAMLError, AttributeError, TypeError):
        return {}


def bindable_slugs(settings: Any) -> list[str]:
    """Every slug a binding may name, in display order."""
    return [*sorted(detector_entries(settings)), SESSION, *JUDGE_SLUGS, *MONITOR_SLUGS]


def group_of(slug: str) -> str:
    if slug.startswith("gf:"):
        return "detect"
    if slug in JUDGE_SLUGS:
        return "judge"
    if slug in MONITOR_SLUGS:
        return "monitor"
    if slug == SESSION:
        return "gate"
    return "detect"


def instance_on(settings: Any, slug: str, detectors: Mapping[str, bool] | None = None) -> bool:
    """Whether this instance has the feature on (flags and ``config/detectors.yaml``). A
    per-agent policy override (``agents.<id>.detectors``) is applied by the engine itself."""
    g = lambda name: bool(getattr(settings, name, False))  # noqa: E731
    if slug.startswith("gf:"):  # WP-G3: a live guardian of the guardian factory
        return g("guardian_factory") and g("detectors_enabled")
    if slug == SESSION:
        return g("session_monitor_enabled")
    if slug == "judge_t2_sample":
        return g("judge_enabled") and int(getattr(settings, "judge_t2_sample_bp", 0) or 0) > 0
    if slug == "judge_challenger":
        return g("judge_enabled") and bool(getattr(settings, "judge_challenger_model", ""))
    flags = {
        "monitor_quality": "quality_enabled",
        "monitor_fairness": "fairness_enabled",
        "monitor_split_payment": "multiagent_enabled",
        "monitor_drift": "drift_enabled",
    }
    if slug in flags:
        return g(flags[slug])
    det = detector_entries(settings) if detectors is None else detectors
    if slug == "document_intake":  # WP-D1: the yaml entry alone does not switch it on
        return (
            g("detectors_enabled") and g("document_intake_enabled") and bool(det.get(slug, False))
        )
    return g("detectors_enabled") and bool(det.get(slug, False))


def _floor(settings: Any, state: Any, system_id: str) -> list[dict[str, Any]]:
    """The guardian floor of the system, read from the assignment rules service."""
    from supervisor.governance.rules_service import RulesService

    return RulesService(state, None, None, settings).guardian_floor(system_id)


# ----------------------------------------------------------------------------- the service
class GuardianService:
    def __init__(
        self, state: Any, tables: Any, clock: Any, settings: Any, *, evidence: Any = None
    ) -> None:
        self.state = state
        self.tables = tables
        self.clock = clock
        self.settings = settings
        self.evidence_sink = evidence

    @classmethod
    def from_adapters(cls, adapters: Any, evidence: Any = None) -> GuardianService:
        return cls(
            adapters.state, adapters.tables, adapters.clock, adapters.settings, evidence=evidence
        )

    def _chain(self, payload: Mapping[str, Any]) -> str | None:
        if self.evidence_sink is None:
            return None
        try:
            return str(
                self.evidence_sink.record(
                    "binding_change", f"system:{payload['system_id']}", payload
                )
            )
        except Exception:  # noqa: BLE001 - the row is stored; log and go on
            log.exception("binding_change chain record failed")
            return None

    def _system(self, system_id: str) -> dict[str, Any]:
        check_system_id(system_id)
        row = self.state.get("ai_system", {"system_id": system_id})
        if row is None:
            raise NotFoundError(f"AI system {system_id} does not exist")
        return dict(row)

    def _rows(self, system_id: str) -> dict[str, dict[str, Any]]:
        return {
            str(r["feature_slug"]): dict(r)
            for r in self.state.query("guardian_binding", {"system_id": system_id})
        }

    # ------------------------------------------------------------------ WP-G3
    def _gf_slugs(self) -> list[str]:
        """Live guardians of the guardian factory (gf:<id>@<version>); none with the flag off."""
        if not getattr(self.settings, "guardian_factory", False):
            return []
        from supervisor.guardian_factory.attach import live_slugs

        return live_slugs(self.state)

    def _gf_live(self, slug: str) -> bool:
        if not getattr(self.settings, "guardian_factory", False):
            return False
        from supervisor.guardian_factory.attach import bindable

        return bindable(self.state, slug)

    # ------------------------------------------------------------------ read
    def get(self, system_id: str) -> dict[str, Any]:
        """Every bindable feature with the binding, the floor lock and the effective state."""
        ensure_bindings_on(self.settings)
        self._system(system_id)
        rows = self._rows(system_id)
        floor = {f["slug"]: f["rules"] for f in _floor(self.settings, self.state, system_id)}
        det = detector_entries(self.settings)
        out = []
        for slug in [*bindable_slugs(self.settings), *self._gf_slugs()]:
            row = rows.get(slug)
            bound = str(row["state"]) if row is not None else "on"
            locked = slug in floor
            has = instance_on(self.settings, slug, det)
            out.append(
                {
                    "slug": slug,
                    "group": group_of(slug),
                    "state": bound,
                    "default": row is None,
                    "locked": locked,
                    "floor_rules": floor.get(slug, []),
                    "instance_on": has,
                    "effective": has and (bound == "on" or locked),
                    "set_by": str(row["set_by"]) if row is not None else None,
                    "set_at": format_ts(row["set_at"]) if row is not None else None,
                    "reason": (row.get("reason") if row is not None else None),
                }
            )
        res: dict[str, Any] = {
            "system_id": system_id,
            "count": len(out),
            "guardians": out,
            "never_bindable": sorted(NEVER_BINDABLE),
        }
        if state_actions_on(self.settings):  # WP-P2 (phase 8): off path adds no key
            res["pending_off"] = self.pending_off(system_id)
        return res

    # ------------------------------------------------------------------ write
    def set(
        self,
        system_id: str,
        slug: Any,
        state: Any,
        actor: str,
        reason: Any = None,
    ) -> dict[str, Any]:
        """Set one binding. Refused (400) for a floor slug set off, for a gate rule, for an
        unknown slug, for an archived system. A repeat of the current state changes nothing."""
        ensure_bindings_on(self.settings)
        check_user(actor, "actor")
        row = self._system(system_id)
        if row["status"] == "archived":
            raise SystemsError(f"AI system {system_id} is archived; it cannot be changed")
        if not isinstance(slug, str) or not slug:
            raise SystemsError("feature slug must be a text")
        if slug in NEVER_BINDABLE:
            raise SystemsError(
                f"{slug} is never bindable: the gate rules block or pause and no product owner "
                "switches them"
            )
        known = bindable_slugs(self.settings)
        if slug not in known and not self._gf_live(slug):
            raise SystemsError(f"unknown feature slug {slug!r}; it must be one of {known}")
        if not isinstance(state, str) or state not in STATES:
            raise SystemsError(f"state must be one of {', '.join(STATES)}")
        if reason is not None and (not isinstance(reason, str) or len(reason) > MAX_REASON):
            raise SystemsError(f"reason must be a text of at most {MAX_REASON} characters")
        if isinstance(reason, str) and any(ord(c) < 32 and c not in "\n\t" for c in reason):
            raise SystemsError("reason must not hold control characters")
        reason = (reason or "").strip() or None
        floor = {f["slug"]: f["rules"] for f in _floor(self.settings, self.state, system_id)}
        mandatory = slug in floor
        if mandatory and state == "off":
            raise SystemsError(
                f"{slug} is in the guardian floor of this system (rules {', '.join(floor[slug])}); "
                "it cannot be switched off"
            )
        cur = self.state.get("guardian_binding", {"system_id": system_id, "feature_slug": slug})
        if (cur is not None and str(cur["state"]) == state) or (cur is None and state == "on"):
            return self._one(system_id, slug)  # no effective change: write nothing
        if state == "off" and state_actions_on(self.settings):  # WP-P2 (phase 8)
            if not reason:
                raise GuardianOffError("reason_required: give the reason for switching it off")
            if needs_second_person(row):
                req = self._request_off(row, slug, actor, reason)
                return {**self._one(system_id, slug), "pending_request": req}
        self._write(system_id, slug, state, actor, reason, mandatory, cur)
        return self._one(system_id, slug)

    def _write(
        self,
        system_id: str,
        slug: str,
        state: str,
        actor: str,
        reason: str | None,
        mandatory: bool,
        cur: Mapping[str, Any] | None,
        approver: str | None = None,
    ) -> None:
        now = self.clock.now()
        fields = {
            "state": state,
            "mandatory": mandatory,
            "set_by": actor,
            "set_at": now,
            "reason": reason,
        }
        if cur is None:
            self.state.insert(
                "guardian_binding", {"system_id": system_id, "feature_slug": slug, **fields}
            )
        else:
            self.state.update(
                "guardian_binding",
                {"system_id": system_id, "feature_slug": slug},
                fields,
                cur["row_version"],
            )
        bump()
        payload: dict[str, Any] = {
            "system_id": system_id,
            "feature_slug": slug,
            "from_state": str(cur["state"]) if cur is not None else "default",
            "to_state": state,
            "mandatory": mandatory,
            "actor_ref": actor_ref(self.settings, actor, "system"),
            "ts": format_ts(now),
        }
        if approver:
            payload["approver_ref"] = actor_ref(self.settings, approver, "system")
        if reason:
            payload["reason_sha256"] = sha256_hex(reason)
        self._chain(payload)

    # ------------------------------------------------------- WP-P2: second person for switch-off
    def pending_off(self, system_id: str) -> list[dict[str, Any]]:
        """Switch-off requests that wait for a second person (oldest first)."""
        rows = [
            dict(r)
            for r in self.state.query(
                "guardian_off_request", {"system_id": system_id, "status": "pending"}
            )
        ]
        rows.sort(key=lambda r: (r["created_at"], r["request_id"]))
        return [
            {
                "request_id": r["request_id"],
                "system_id": r["system_id"],
                "feature_slug": r["feature_slug"],
                "requested_by": r["requested_by"],
                "reason": r["reason"],
                "created_at": format_ts(r["created_at"]),
            }
            for r in rows
        ]

    def _request_off(
        self, system: Mapping[str, Any], slug: str, actor: str, reason: str
    ) -> dict[str, Any]:
        system_id = str(system["system_id"])
        if any(r["feature_slug"] == slug for r in self.pending_off(system_id)):
            raise GuardianOffError(
                f"request_pending: a request to switch {slug} off is already waiting for a "
                "second person"
            )
        now = self.clock.now()
        row = dict(
            self.state.insert(
                "guardian_off_request",
                {
                    "request_id": "gof_" + uuid.uuid4().hex[:24],
                    "system_id": system_id,
                    "feature_slug": slug,
                    "requested_by": actor,
                    "reason": reason,
                    "status": "pending",
                    "created_at": now,
                },
            )
        )
        self._chain(
            {
                "system_id": system_id,
                "feature_slug": slug,
                "from_state": "on",
                "to_state": "off",
                "status": "requested",
                "request_id": row["request_id"],
                "actor_ref": actor_ref(self.settings, actor, "system"),
                "reason_sha256": sha256_hex(reason),
                "ts": format_ts(now),
            }
        )
        return {
            "request_id": row["request_id"],
            "feature_slug": slug,
            "requested_by": actor,
            "status": "pending",
        }

    def decide_off(
        self, system_id: str, request_id: str, approver: str, decision: str = "approve"
    ) -> dict[str, Any]:
        """A second person approves or rejects a switch-off request. The requester cannot answer
        (code ``same_person``). Approval writes the binding; the floor is read again first."""
        ensure_bindings_on(self.settings)
        if not state_actions_on(self.settings):
            raise GuardianOffError(
                "switch-off approval is off (CONSOLE_STATE_ACTIONS=1 turns it on)"
            )
        check_user(approver, "approver")
        row = self._system(system_id)
        if decision not in ("approve", "reject"):
            raise GuardianOffError("decision must be approve or reject")
        req = self.state.get("guardian_off_request", {"request_id": request_id})
        if req is None or req["system_id"] != system_id:
            raise NotFoundError(f"switch-off request {request_id} does not exist")
        if req["status"] != "pending":
            raise GuardianOffError(f"the request was already answered ({req['status']})")
        if str(req["requested_by"]).casefold() == approver.casefold():
            raise GuardianOffError(
                "same_person: the person who asked for the switch-off cannot answer it; "
                "a second person does"
            )
        slug = str(req["feature_slug"])
        status = "approved" if decision == "approve" else "rejected"
        if status == "approved":
            floor = {f["slug"]: f["rules"] for f in _floor(self.settings, self.state, system_id)}
            if slug in floor:
                raise GuardianOffError(
                    f"{slug} is in the guardian floor of this system (rules "
                    f"{', '.join(floor[slug])}); it cannot be switched off"
                )
            if row["status"] == "archived":
                raise GuardianOffError(f"AI system {system_id} is archived; it cannot be changed")
        now = self.clock.now()
        try:  # claim the request first: a lost race leaves the binding untouched
            self.state.update(
                "guardian_off_request",
                {"request_id": request_id},
                {"status": status, "decided_by": approver, "decided_at": now},
                int(req["row_version"]),
            )
        except ConcurrencyError:
            raise GuardianOffError("the request was answered by someone else; reload") from None
        if status == "approved":
            cur = self.state.get("guardian_binding", {"system_id": system_id, "feature_slug": slug})
            if cur is None or str(cur["state"]) != "off":
                self._write(
                    system_id,
                    slug,
                    "off",
                    str(req["requested_by"]),
                    str(req["reason"]),
                    False,
                    cur,
                    approver=approver,
                )
        else:
            self._chain(
                {
                    "system_id": system_id,
                    "feature_slug": slug,
                    "from_state": "on",
                    "to_state": "off",
                    "status": "rejected",
                    "request_id": request_id,
                    "actor_ref": actor_ref(self.settings, approver, "system"),
                    "ts": format_ts(now),
                }
            )
        return {**self._one(system_id, slug), "request_id": request_id, "request_status": status}

    def _one(self, system_id: str, slug: str) -> dict[str, Any]:
        for g in self.get(system_id)["guardians"]:
            if g["slug"] == slug:
                return {"system_id": system_id, **g}
        raise SystemsError(f"unknown feature slug {slug!r}")  # pragma: no cover


# ----------------------------------------------------------------------------- the lookup
class GuardianNarrower:
    """What the engines call: ``off(agent_id)`` is the set of feature slugs switched off for the
    agent by its systems' bindings. Cached for a few seconds. Never raises: a failure gives the
    empty set, which leaves every feature as the instance has it (more coverage, not less)."""

    def __init__(self, state: Any, settings: Any, *, ttl_s: float = CACHE_TTL_S) -> None:
        self.state = state
        self.settings = settings
        self.ttl_s = ttl_s
        self._cache: dict[str, tuple[float, int, frozenset[str]]] = {}

    def off(self, agent_id: str) -> frozenset[str]:
        base = str(agent_id).split("/", 1)[0]  # a consumer id never has its own binding
        now = time.monotonic()
        hit = self._cache.get(base)
        if hit is not None and now - hit[0] < self.ttl_s and hit[1] == _generation:
            return hit[2]
        try:
            out = self._resolve(base)
        except Exception:  # noqa: BLE001 - never break the gate, the judge or a monitor
            log.exception("guardian bindings lookup failed for %s", base)
            out = frozenset()
        if len(self._cache) > 2048:
            self._cache.clear()
        self._cache[base] = (now, _generation, out)
        return out

    def is_off(self, agent_id: str, slug: str) -> bool:
        return slug in self.off(agent_id)

    def _resolve(self, agent_id: str) -> frozenset[str]:
        off_rows = self.state.query("guardian_binding", {"state": "off"})
        if not off_rows:
            return frozenset()
        by_system: dict[str, set[str]] = {}
        for r in off_rows:
            by_system.setdefault(str(r["system_id"]), set()).add(str(r["feature_slug"]))
        low = agent_id.lower()
        systems = sorted(
            {
                str(c["system_id"])
                for c in self.state.query("system_component", {"ref_kind": "agent"})
                if _on(c["active"]) and str(c["ref_id"]).lower() == low
            }
        )
        live = []
        for sid in systems:
            sysrow = self.state.get("ai_system", {"system_id": sid})
            if sysrow is not None and sysrow["status"] != "archived":
                live.append(sid)
        if not live:
            return frozenset()
        result: frozenset[str] | None = None
        for sid in live:
            wanted = by_system.get(sid, set())
            if wanted:  # the floor is read now, never copied
                floor = {f["slug"] for f in _floor(self.settings, self.state, sid)}
                wanted = {s for s in wanted if s not in floor and s not in NEVER_BINDABLE}
            result = frozenset(wanted) if result is None else result & frozenset(wanted)
            if not result:
                return frozenset()
        return result or frozenset()


def make_narrower(settings: Any, state: Any) -> GuardianNarrower | None:
    """None unless GOVERNANCE_ENABLED and GUARDIAN_BINDINGS_ENABLED are on: the engines then do
    not call into this module at all (the off path)."""
    if state is None or not guardian_bindings_on(settings):
        return None
    return GuardianNarrower(state, settings)


__all__ = [
    "GuardianNarrower",
    "GuardianService",
    "bindable_slugs",
    "ensure_bindings_on",
    "guardian_bindings_on",
    "instance_on",
    "make_narrower",
]
