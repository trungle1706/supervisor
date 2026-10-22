"""Lifecycle move and stage approvals of an AI system (WP-G1, docs/governance.md section 9).

* ``request`` asks for the move of a system to a stage that needs an approval (the stage policy
  in ``config/tasks.yaml``, ``stages.py``). One pending request per target stage.
* ``decide`` answers it. The approver is a reviewer or oversight manager on the team of the
  system, or holds the ``approver`` role, and is neither the requester nor the owner of the
  system (refusal text starts ``segregation of duties:``).
* ``move`` changes ``lifecycle_stage``. A target that needs approval needs an approved request
  made from the current stage that no earlier move has used (``applied_at``).

Every step writes a ``stage_change`` chain record (ids, enums, hashes; no name, no reason text,
no user id). An approval writes an ``outbound_event`` (``stage_approved``).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

from supervisor.controls.model import actor_ref
from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import ConcurrencyError, NotFoundError
from supervisor.governance import events
from supervisor.governance.model import (
    LIFECYCLE_STAGES,
    SegregationOfDuties,
    SystemsError,
    _text,
    check_system_id,
    check_user,
    choice,
)
from supervisor.governance.stages import load_policy, needs_approval
from supervisor.governance.systems import SystemService, _plain

log = logging.getLogger("supervisor.governance")

APPROVAL_STATUSES: tuple[str, ...] = ("pending", "approved", "rejected")
DECISIONS: tuple[str, ...] = ("approve", "reject")
# Team roles that may answer a stage approval (besides the global approver role).
APPROVER_TEAM_ROLES: tuple[str, ...] = ("reviewer", "oversight_manager")
APPROVER_ROLE = "approver"
MAX_APPROVALS = 200


def same(a: str | None, b: str | None) -> bool:
    """Two user ids name the same person (compared without letter case)."""
    return bool(a) and bool(b) and str(a).strip().casefold() == str(b).strip().casefold()


class LifecycleService:
    def __init__(self, systems: SystemService, policy: Mapping[str, bool] | None = None) -> None:
        self.systems = systems
        self._policy = dict(policy) if policy is not None else None

    @classmethod
    def from_adapters(cls, adapters: Any, evidence: Any = None) -> LifecycleService:
        return cls(SystemService.from_adapters(adapters, evidence=evidence))

    # ------------------------------------------------------------------ plumbing
    @property
    def state(self) -> Any:
        return self.systems.state

    @property
    def policy(self) -> dict[str, bool]:
        if self._policy is None:
            self._policy = load_policy(getattr(self.systems.settings, "tasks_config", None))
        return self._policy

    def needs_approval(self, to_stage: str) -> bool:
        return needs_approval(self.policy, to_stage)

    def _chain(self, action: str, sys_row: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
        sid = str(sys_row["system_id"])
        body = {
            "system_id": sid,
            "action": action,
            "lifecycle_stage": sys_row["lifecycle_stage"],
            "ts": format_ts(self.systems.clock.now()),
            **payload,
        }
        self.systems._chain("stage_change", f"system:{sid}", body)

    def _ref(self, user: str) -> str:
        return actor_ref(self.systems.settings, user, "system")

    def _need_approval(self, system_id: str, approval_id: str) -> dict[str, Any]:
        if not isinstance(approval_id, str) or not approval_id.startswith("ap_"):
            raise NotFoundError(f"approval {str(approval_id)[:64]} does not exist")
        row = self.state.get("stage_approval", {"approval_id": approval_id})
        if row is None or row["system_id"] != system_id:
            raise NotFoundError(f"approval {approval_id[:64]} does not exist")
        return dict(row)

    # ------------------------------------------------------------------ reads
    def approvals(self, system_id: str) -> list[dict[str, Any]]:
        check_system_id(system_id)
        self.systems._need(system_id)
        rows = [dict(r) for r in self.state.query("stage_approval", {"system_id": system_id})]
        rows.sort(key=lambda r: (r["created_at"], r["approval_id"]))
        return [_plain(r) for r in rows]  # type: ignore[misc]

    def status(self, system_id: str) -> dict[str, Any]:
        """Stage, the stages that need an approval, and the approvals (for the Tasks tab)."""
        row = self.systems._need(system_id)
        return {
            "lifecycle_stage": row["lifecycle_stage"],
            "needs_approval": [s for s in LIFECYCLE_STAGES if self.needs_approval(s)],
            "approvals": self.approvals(system_id),
        }

    # ------------------------------------------------------------------ request
    def request(self, system_id: str, to_stage: str, actor: str) -> dict[str, Any]:
        check_user(actor, "actor")
        sys_row = self.systems._need_open(system_id)
        choice(to_stage, LIFECYCLE_STAGES, "to_stage")
        cur = str(sys_row["lifecycle_stage"])
        self._check_target(cur, to_stage)
        if not self.needs_approval(to_stage):
            raise SystemsError(
                f"the move to {to_stage} needs no approval; use POST /v1/systems/{system_id}/stage"
            )
        mine = [r for r in self.state.query("stage_approval", {"system_id": system_id})]
        if any(r["status"] == "pending" and r["to_stage"] == to_stage for r in mine):
            raise SystemsError(f"a request to move to {to_stage} is already waiting for an answer")
        if len(mine) >= MAX_APPROVALS:
            raise SystemsError(f"a system can have at most {MAX_APPROVALS} stage approvals")
        row = dict(
            self.state.insert(
                "stage_approval",
                {
                    "approval_id": "ap_" + uuid.uuid4().hex[:24],
                    "system_id": system_id,
                    "from_stage": cur,
                    "to_stage": to_stage,
                    "requested_by": actor,
                    "status": "pending",
                    "created_at": self.systems.clock.now(),
                },
            )
        )
        self._chain(
            "request",
            sys_row,
            {
                "approval_id": row["approval_id"],
                "from_stage": cur,
                "to_stage": to_stage,
                "status": "pending",
                "actor_ref": self._ref(actor),
            },
        )
        return _plain(row)  # type: ignore[no-any-return]

    @staticmethod
    def _check_target(cur: str, to_stage: str) -> None:
        if cur == "retirement":
            raise SystemsError("the system is retired; its stage cannot change")
        if to_stage == cur:
            raise SystemsError(f"the system is already in the {cur} stage")

    # ------------------------------------------------------------------ decide
    def _owners(self, sys_row: Mapping[str, Any]) -> set[str]:
        owners = {str(sys_row["owner_user"]).casefold()}
        for m in self.systems._team_rows(str(sys_row["system_id"])):
            if m["team_role"] == "system_owner":
                owners.add(str(m["user_id"]).casefold())
        return owners

    def can_decide(self, sys_row: Mapping[str, Any], user_id: str, roles: Any) -> bool:
        """True when the person may answer a stage approval of this system: a reviewer or
        oversight manager on its team, or holds the approver role."""
        if APPROVER_ROLE in set(roles or ()):
            return True
        return any(
            same(m["user_id"], user_id) and m["team_role"] in APPROVER_TEAM_ROLES
            for m in self.systems._team_rows(str(sys_row["system_id"]))
        )

    def decide(
        self,
        system_id: str,
        approval_id: str,
        decision: str,
        who: Any,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Approve or reject a pending request. ``who`` is the calling principal (needs
        ``user_id`` and ``roles``)."""
        user = check_user(str(getattr(who, "user_id", "")), "approver")
        sys_row = self.systems._need_open(system_id)
        ap = self._need_approval(system_id, approval_id)
        choice(decision, DECISIONS, "decision")
        text = _text(reason, "reason", 1000, required=decision == "reject")
        if ap["status"] != "pending":
            raise SystemsError(f"the request was already answered ({ap['status']})")
        if not self.can_decide(sys_row, user, getattr(who, "roles", ())):
            raise SystemsError(
                "only a reviewer or oversight manager of this system, or an approver, "
                "can answer a stage approval"
            )
        if same(user, ap["requested_by"]):
            raise SegregationOfDuties(
                "segregation of duties: the person who asked for the move cannot answer it"
            )
        if user.casefold() in self._owners(sys_row):
            raise SegregationOfDuties(
                "segregation of duties: the owner of the system cannot answer its stage approval"
            )
        if ap["from_stage"] != sys_row["lifecycle_stage"]:
            raise SystemsError(
                f"the system is now in the {sys_row['lifecycle_stage']} stage, not "
                f"{ap['from_stage']}; ask again"
            )
        status = "approved" if decision == "approve" else "rejected"
        now = self.systems.clock.now()
        try:
            stored = dict(
                self.state.update(
                    "stage_approval",
                    {"approval_id": approval_id},
                    {"status": status, "decided_by": user, "reason": text, "decided_at": now},
                    int(ap["row_version"]),
                )
            )
        except ConcurrencyError:
            raise SystemsError("the request was answered by someone else; reload") from None
        self._chain(
            "approve" if status == "approved" else "reject",
            sys_row,
            {
                "approval_id": approval_id,
                "from_stage": ap["from_stage"],
                "to_stage": ap["to_stage"],
                "status": status,
                "actor_ref": self._ref(user),
                "requester_ref": self._ref(str(ap["requested_by"])),
                "reason_hash": sha256_hex({"reason": text or ""}),
            },
        )
        if status == "approved":
            events.emit(
                self.state,
                self.systems.clock,
                self.systems.settings,
                "stage_approved",
                system_id,
                {
                    "approval_id": approval_id,
                    "from_stage": str(ap["from_stage"]),
                    "to_stage": str(ap["to_stage"]),
                },
            )
        return _plain(stored)  # type: ignore[no-any-return]

    # ------------------------------------------------------------------ move
    def move(self, system_id: str, to_stage: str, actor: str) -> dict[str, Any]:
        """Change the lifecycle stage. A stage that needs approval needs an approved request
        from the current stage that was not used yet."""
        check_user(actor, "actor")
        sys_row = self.systems._need_open(system_id)
        choice(to_stage, LIFECYCLE_STAGES, "to_stage")
        cur = str(sys_row["lifecycle_stage"])
        self._check_target(cur, to_stage)
        ap: dict[str, Any] | None = None
        if self.needs_approval(to_stage):
            ready = [
                dict(r)
                for r in self.state.query("stage_approval", {"system_id": system_id})
                if r["status"] == "approved"
                and r["to_stage"] == to_stage
                and r["from_stage"] == cur
                and r.get("applied_at") is None
            ]
            if not ready:
                raise SystemsError(
                    f"the move to {to_stage} needs an approved stage approval "
                    f"(POST /v1/systems/{system_id}/approvals, then an approver answers it)"
                )
            ap = max(ready, key=lambda r: (r["decided_at"], r["approval_id"]))
        payload: dict[str, Any] = {
            "from_stage": cur,
            "to_stage": to_stage,
            "status": "moved",
            "actor_ref": self._ref(actor),
            "approval_id": "",
        }
        if ap is not None:  # claim the approval first: a lost race leaves the system untouched
            try:
                self.state.update(
                    "stage_approval",
                    {"approval_id": ap["approval_id"]},
                    {"applied_at": self.systems.clock.now()},
                    int(ap["row_version"]),
                )
            except ConcurrencyError:
                raise SystemsError(
                    "the stage approval was used by someone else; reload and retry"
                ) from None
            payload["approval_id"] = ap["approval_id"]
            payload["approver_ref"] = self._ref(str(ap["decided_by"]))
        try:
            stored = dict(
                self.state.update(
                    "ai_system",
                    {"system_id": system_id},
                    {"lifecycle_stage": to_stage},
                    int(sys_row["row_version"]),
                )
            )
        except ConcurrencyError:
            raise SystemsError(
                "the AI system was changed by someone else; reload and retry"
            ) from None
        self._chain("move", stored, payload)
        return self.systems.get(system_id)
