"""Agent state machine (ADR D03) and pause / resume authority (ADR D04).

States live in ``agent.gate_state`` (RUNNING / SHADOW / PAUSED / QUARANTINED / RETIRED);
``agent.status`` mirrors them (enforced / shadow / paused / retired; QUARANTINED -> paused,
``gate_state`` tells them apart). The ``gate_control`` table holds the active pause
(with the state to resume to) and pending resume approvals.

* Pause: one principal, one call (also a rule with action ``pause``).
* Resume: two different principals within ``resume_window_s``: the agent owner
  and a reviewer. The first call records a pending approval; the second completes it.
* Quarantine: everything is denied, read-only tools too. Only an admin can release
  it, and release goes to PAUSED (the normal two-person resume then applies).

* Retire (WP19, D03 amendment): one-way, only from PAUSED or SHADOW, admin only. Nothing
  leaves RETIRED. RUNNING must pause first; QUARANTINED must be released to PAUSED first.

Every transition is written with ``row_version`` optimistic concurrency and recorded
through the EvidenceSink. Free-text reasons stay in ``gate_control``; the chain gets
only their SHA-256 (PII never enters the chain).
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any, Literal

from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import ConcurrencyError, SupervisorError
from supervisor.core.ports import Clock, EvidenceSink, StateStore
from supervisor.gateway.policy import Policy, PolicyProvider

log = logging.getLogger("supervisor.gateway.state")

GateStateT = Literal["RUNNING", "SHADOW", "PAUSED", "QUARANTINED", "RETIRED"]
STATUS_FOR_STATE = {
    "RUNNING": "enforced",
    "SHADOW": "shadow",
    "PAUSED": "paused",
    "QUARANTINED": "paused",
    "RETIRED": "retired",
}
MAX_REASON = 2000


class TransitionError(SupervisorError):
    """A state change is not allowed (shown to the user as HTTP 400)."""


def _reason(text: str | None) -> str:
    value = (text or "").strip()
    if len(value) > MAX_REASON:
        raise TransitionError(f"reason is longer than {MAX_REASON} characters")
    return value


class AgentStateMachine:
    def __init__(
        self,
        state: StateStore,
        evidence: EvidenceSink,
        clock: Clock,
        policy: PolicyProvider,
        *,
        cache_ttl_s: float = 1.0,
        resume_window_s: int = 3600,
        retries: int = 3,
    ) -> None:
        self.state = state
        self.evidence = evidence
        self.clock = clock
        self.policy = policy
        self.cache_ttl_s = cache_ttl_s
        self.resume_window_s = resume_window_s
        self.retries = retries
        self._cache: dict[str, tuple[dict[str, Any] | None, float]] = {}
        self._lock = threading.RLock()
        # WP27: called (agent_id, principal) after a completed two-person resume.
        self.on_resume: Callable[[str, str], None] | None = None

    # ------------------------------------------------------------ reads

    def _row(self, agent_id: str, fresh: bool = False) -> dict[str, Any] | None:
        now = time.monotonic()
        cached = self._cache.get(agent_id)
        if not fresh and cached is not None and now - cached[1] < self.cache_ttl_s:
            return cached[0]
        row = self.state.get("agent", {"agent_id": agent_id})
        self._cache[agent_id] = (row, now)
        return row

    def last_known_state(self, agent_id: str) -> str | None:
        """Last state read from the store (any age); used only to pick a fail mode."""
        cached = self._cache.get(agent_id)
        return cached[0]["gate_state"] if cached and cached[0] else None

    def invalidate(self, agent_id: str | None = None) -> None:
        with self._lock:
            if agent_id is None:
                self._cache.clear()
            else:
                self._cache.pop(agent_id, None)

    def get_state(self, agent_id: str, policy: Policy | None = None) -> GateStateT | None:
        """Current state, or None for an unknown agent (not registered, not in the policy)."""
        row = self._row(agent_id)
        if row is not None:
            return row["gate_state"]
        pol = policy or self.policy.current()
        manifest = pol.doc.agents.get(agent_id)
        return manifest.initial_state if manifest else None

    def describe(self, agent_id: str) -> dict[str, Any]:
        state = self.get_state(agent_id)
        if state is None:
            raise TransitionError(f"unknown agent {agent_id}")
        row = self._row(agent_id)
        pending = [
            {
                "principal": c["principal"],
                "role": c["role"],
                "expires_at": format_ts(c["expires_at"]),
            }
            for c in self._pending_resumes(agent_id)
        ]
        return {
            "agent_id": agent_id,
            "state": state,
            "status": row["status"] if row else STATUS_FOR_STATE[state],
            "row_version": int(row["row_version"]) if row else 0,
            "registered": row is not None,
            "pending_resume": pending,
        }

    # ------------------------------------------------------------ helpers

    def _ensure_row(self, agent_id: str) -> dict[str, Any]:
        row = self._row(agent_id, fresh=True)
        if row is not None:
            return row
        manifest = self.policy.current().doc.agents.get(agent_id)
        if manifest is None:
            raise TransitionError(f"unknown agent {agent_id}")
        state = manifest.initial_state
        try:
            row = self.state.insert(
                "agent",
                {
                    "agent_id": agent_id,
                    "name": manifest.name,
                    "owner_team": manifest.owner_team,
                    "owner_user": manifest.owner_user,
                    "risk_tier": manifest.risk_tier,
                    "host_type": manifest.host_type,
                    "plug_point": manifest.plug_point,
                    "model_family": manifest.model_family,
                    "status": STATUS_FOR_STATE[state],
                    "gate_state": state,
                    "created_at": self.clock.now(),
                },
            )
        except SupervisorError:
            row = self._row(agent_id, fresh=True)
            if row is None:
                raise
        self._cache[agent_id] = (row, time.monotonic())
        return row

    def _transition(
        self,
        agent_id: str,
        allowed_from: tuple[str, ...],
        to: GateStateT,
        principal: str,
        reason: str,
        event: str,
        extra: Mapping[str, Any] | None = None,
        *,
        auth_method: str | None = None,
        actor_kind: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Change ``gate_state`` with the row_version check; retry on a lost race."""
        last_error: Exception | None = None
        for _ in range(self.retries):
            row = self._ensure_row(agent_id)
            current = row["gate_state"]
            if current not in allowed_from:
                raise TransitionError(f"agent {agent_id} is {current}; cannot {event}")
            try:
                new = self.state.update(
                    "agent",
                    {"agent_id": agent_id},
                    {"gate_state": to, "status": STATUS_FOR_STATE[to]},
                    int(row["row_version"]),
                )
            except ConcurrencyError as exc:
                last_error = exc
                self.invalidate(agent_id)
                continue
            self._cache[agent_id] = (new, time.monotonic())
            payload = {
                "agent_id": agent_id,
                "event": event,
                "from_state": current,
                "to_state": to,
                "principal": principal,
                "reason_sha256": sha256_hex(reason),
                "row_version": int(new["row_version"]),
                "ts": format_ts(self.clock.now()),
                **(extra or {}),
            }
            # M5: who acted and how they were identified (keys only when known)
            if auth_method is not None:
                payload["auth_method"] = auth_method
            if actor_kind is not None:
                payload["actor_kind"] = actor_kind
            self.evidence.record("gate_state_change", agent_id, payload)
            return new, current
        raise TransitionError(f"agent {agent_id}: state changed concurrently; retry ({last_error})")

    def _controls(self, agent_id: str, action: str, status: str) -> list[dict[str, Any]]:
        rows = self.state.query("gate_control", {"agent_id": agent_id, "status": status})
        return [r for r in rows if r["action"] == action]

    def _close_control(self, row: Mapping[str, Any], status: str) -> None:
        try:
            self.state.update(
                "gate_control",
                {"control_id": row["control_id"]},
                {"status": status},
                int(row["row_version"]),
            )
        except ConcurrencyError as exc:
            raise TransitionError("approval changed concurrently; retry") from exc

    def _pending_resumes(self, agent_id: str) -> list[dict[str, Any]]:
        now = self.clock.now()
        out = []
        for row in self._controls(agent_id, "resume", "pending"):
            if row["expires_at"] is not None and row["expires_at"] <= now:
                self._close_control(row, "expired")
                continue
            out.append(row)
        return out

    def _close_pending_resumes(self, agent_id: str) -> None:
        """Approvals answer one pause; a quarantine or release voids them."""
        for row in self._controls(agent_id, "resume", "pending"):
            self._close_control(row, "void")

    def _new_control(self, agent_id: str, action: str, principal: str, **fields: Any) -> None:
        self.state.insert(
            "gate_control",
            {
                "control_id": uuid.uuid4().hex,
                "agent_id": agent_id,
                "action": action,
                "principal": principal,
                "created_at": self.clock.now(),
                **fields,
            },
        )

    # ------------------------------------------------------------ transitions

    def pause(
        self,
        agent_id: str,
        principal: str,
        reason: str = "",
        *,
        auth_method: str | None = None,
        actor_kind: str | None = None,
    ) -> dict[str, Any]:
        """One principal, one call. Pausing a paused agent is a no-op."""
        reason = _reason(reason)
        if not principal:
            raise TransitionError("principal is required")
        with self._lock:
            row = self._ensure_row(agent_id)
            if row["gate_state"] == "PAUSED":
                return {"agent_id": agent_id, "state": "PAUSED", "changed": False}
            _, before = self._transition(
                agent_id,
                ("RUNNING", "SHADOW"),
                "PAUSED",
                principal,
                reason,
                "pause",
                auth_method=auth_method,
                actor_kind=actor_kind,
            )
            self._close_pending_resumes(agent_id)
            for old in self._controls(agent_id, "pause", "active"):
                self._close_control(old, "superseded")
            self._new_control(
                agent_id, "pause", principal, reason=reason, resume_to=before, status="active"
            )
            return {"agent_id": agent_id, "state": "PAUSED", "changed": True, "from": before}

    def quarantine(
        self,
        agent_id: str,
        principal: str,
        reason: str = "",
        *,
        auth_method: str | None = None,
        actor_kind: str | None = None,
    ) -> dict[str, Any]:
        reason = _reason(reason)
        if not principal:
            raise TransitionError("principal is required")
        with self._lock:
            row = self._ensure_row(agent_id)
            if row["gate_state"] == "QUARANTINED":
                return {"agent_id": agent_id, "state": "QUARANTINED", "changed": False}
            _, before = self._transition(
                agent_id,
                ("RUNNING", "SHADOW", "PAUSED"),
                "QUARANTINED",
                principal,
                reason,
                "quarantine",
                auth_method=auth_method,
                actor_kind=actor_kind,
            )
            self._close_pending_resumes(agent_id)
            if before != "PAUSED":
                self._new_control(
                    agent_id, "pause", principal, reason=reason, resume_to=before, status="active"
                )
            return {"agent_id": agent_id, "state": "QUARANTINED", "changed": True, "from": before}

    def release_quarantine(
        self,
        agent_id: str,
        principal: str,
        reason: str,
        *,
        auth_method: str | None = None,
        actor_kind: str | None = None,
    ) -> dict[str, Any]:
        """Admin only. QUARANTINED -> PAUSED; the two-person resume still applies."""
        reason = _reason(reason)
        if not reason:
            raise TransitionError("a reason is required to release a quarantine")
        admins = self.policy.current().doc.admins
        if principal not in admins:
            raise TransitionError(f"{principal} is not an admin; only an admin can release")
        with self._lock:
            self._transition(
                agent_id,
                ("QUARANTINED",),
                "PAUSED",
                principal,
                reason,
                "release_quarantine",
                auth_method=auth_method,
                actor_kind=actor_kind,
            )
            self._close_pending_resumes(agent_id)
            return {"agent_id": agent_id, "state": "PAUSED", "changed": True}

    def retire(
        self,
        agent_id: str,
        principal: str,
        reason: str,
        *,
        auth_method: str | None = None,
        actor_kind: str | None = None,
    ) -> dict[str, Any]:
        """Admin only (``policy.doc.admins``, like a quarantine release). One-way.

        Allowed from PAUSED or SHADOW. A RUNNING agent must be paused first and a
        QUARANTINED agent released to PAUSED first. Retiring a RETIRED agent is a no-op.
        """
        reason = _reason(reason)
        if not reason:
            raise TransitionError("a reason is required to retire an agent")
        admins = self.policy.current().doc.admins
        if principal not in admins:
            raise TransitionError(f"{principal} is not an admin; only an admin can retire")
        with self._lock:
            row = self._ensure_row(agent_id)
            current = row["gate_state"]
            if current == "RETIRED":
                return {"agent_id": agent_id, "state": "RETIRED", "changed": False}
            if current == "RUNNING":
                raise TransitionError(f"agent {agent_id} is RUNNING; pause it first")
            if current == "QUARANTINED":
                raise TransitionError(f"agent {agent_id} is QUARANTINED; release it first")
            _, before = self._transition(
                agent_id,
                ("PAUSED", "SHADOW"),
                "RETIRED",
                principal,
                reason,
                "retire",
                auth_method=auth_method,
                actor_kind=actor_kind,
            )
            self._close_pending_resumes(agent_id)
            for a in self._controls(agent_id, "pause", "active"):
                self._close_control(a, "closed")
            return {"agent_id": agent_id, "state": "RETIRED", "changed": True, "from": before}

    def _role(self, agent_id: str, principal: str) -> str:
        row = self._ensure_row(agent_id)
        if principal == row["owner_user"]:
            return "owner"
        reviewers = self.policy.current().doc.reviewers
        if principal in reviewers:
            return "reviewer"
        raise TransitionError(
            f"{principal} may not approve a resume (needs the agent owner or a reviewer)"
        )

    def approver_role(self, agent_id: str, principal: str) -> str:
        """owner or reviewer for ``principal``, else ``TransitionError`` (WP27 reuses it for
        the two-person lift of a session pause)."""
        with self._lock:
            return self._role(agent_id, principal)

    def resume(
        self,
        agent_id: str,
        principal: str,
        reason: str = "",
        *,
        auth_method: str | None = None,
        actor_kind: str | None = None,
    ) -> dict[str, Any]:
        """Two different people (agent owner + reviewer) within the resume window."""
        reason = _reason(reason)
        if not principal:
            raise TransitionError("principal is required")
        with self._lock:
            row = self._ensure_row(agent_id)
            if row["gate_state"] == "QUARANTINED":
                raise TransitionError(
                    f"agent {agent_id} is QUARANTINED; an admin must release it first"
                )
            if row["gate_state"] == "RETIRED":
                raise TransitionError(f"agent {agent_id} is RETIRED; it cannot resume")
            if row["gate_state"] != "PAUSED":
                raise TransitionError(f"agent {agent_id} is {row['gate_state']}; not paused")
            role = self._role(agent_id, principal)
            pending = self._pending_resumes(agent_id)
            for p in pending:
                if p["principal"] == principal:
                    raise TransitionError(
                        f"{principal} already approved this resume; a second, different "
                        "person must approve"
                    )
            partner = next((p for p in pending if p["role"] != role), None)
            if partner is None:
                self._new_control(
                    agent_id,
                    "resume",
                    principal,
                    role=role,
                    reason=reason,
                    status="pending",
                    expires_at=self.clock.now() + timedelta(seconds=self.resume_window_s),
                )
                self.evidence.record(
                    "gate_resume_requested",
                    agent_id,
                    {
                        "agent_id": agent_id,
                        "principal": principal,
                        "role": role,
                        "reason_sha256": sha256_hex(reason),
                        "window_s": self.resume_window_s,
                        "ts": format_ts(self.clock.now()),
                        **({"auth_method": auth_method} if auth_method is not None else {}),
                        **({"actor_kind": actor_kind} if actor_kind is not None else {}),
                    },
                )
                needed = "reviewer" if role == "owner" else "owner"
                return {
                    "agent_id": agent_id,
                    "state": "PAUSED",
                    "status": "pending",
                    "needs": needed,
                    "changed": False,
                }
            active = self._controls(agent_id, "pause", "active")
            resume_to: GateStateT = "RUNNING"
            if active and active[-1]["resume_to"] in ("RUNNING", "SHADOW"):
                resume_to = active[-1]["resume_to"]
            self._transition(
                agent_id,
                ("PAUSED",),
                resume_to,
                principal,
                reason,
                "resume",
                {"approver_1": partner["principal"], "approver_2": principal},
                auth_method=auth_method,
                actor_kind=actor_kind,
            )
            self._close_control(partner, "used")
            for a in active:
                self._close_control(a, "closed")
            if self.on_resume is not None:  # WP27: session pauses end with the agent's resume
                try:
                    self.on_resume(agent_id, principal)
                except Exception:  # noqa: BLE001 - a hook problem must not undo the resume
                    log.exception("on_resume hook failed")
            return {
                "agent_id": agent_id,
                "state": resume_to,
                "status": "resumed",
                "approvers": [partner["principal"], principal],
                "changed": True,
            }

    def set_mode(self, agent_id: str, mode: GateStateT, principal: str) -> dict[str, Any]:
        """Switch between SHADOW and RUNNING (not out of PAUSED, QUARANTINED or RETIRED)."""
        if mode not in ("RUNNING", "SHADOW"):
            raise TransitionError("mode must be RUNNING or SHADOW")
        with self._lock:
            row = self._ensure_row(agent_id)
            if row["gate_state"] == mode:
                return {"agent_id": agent_id, "state": mode, "changed": False}
            self._transition(agent_id, ("RUNNING", "SHADOW"), mode, principal, "", "set_mode")
            return {"agent_id": agent_id, "state": mode, "changed": True}
