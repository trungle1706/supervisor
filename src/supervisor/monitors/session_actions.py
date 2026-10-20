"""What the session monitor does when its rule fires (WP27, ADR D29).

Two actions, both deterministic and both written to the evidence chain as hashes and integers:

* ``session_escalation`` case (medium; high when a money or credit tool is in the window), with
  the masked timeline in the summary. No incident clock: the monitor opens the case through
  ``monitors.common.open_case``, which sets none, and no rule here adds one.
* a session-scoped pause (``session_control`` row) of the tool classes in ``pause_scope``. The
  gate consults it (``GATE-SESSION-PAUSE``). It ends by the two-person resume (the agent owner
  and a reviewer, same rule as ``AgentStateMachine.resume``) or when the cool-down runs out.

Idempotent: a session that already has an open case, or a case inside its cool-down, gets
neither a second case nor a second pause. The state is a ``monitor_state`` row.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import ConcurrencyError
from supervisor.gateway.state import TransitionError
from supervisor.monitors.common import (
    MonitorContext,
    find_open_case,
    get_state,
    open_case,
    put_state,
    raise_severity,
)
from supervisor.monitors.session import (
    Assessment,
    SessionConfig,
    timeline_text,
)

log = logging.getLogger("supervisor.monitors.session")

ACTOR = "monitor:session"
CASE_TYPE = "session_escalation"
STATE_MONITOR = "session"
ACTIVE, LIFTED, EXPIRED = "active", "lifted", "expired"


def session_ref(agent_id: str, session_id: str) -> str:
    """Stable short key of (agent, session) for ``monitor_state`` rows."""
    return sha256_hex(f"{agent_id}|{session_id}")[:32]


@dataclass
class ActionResult:
    case_id: str | None = None
    case_opened: bool = False
    pause_id: str | None = None
    pause_set: bool = False
    skipped: str | None = None  # cooldown | open_case | below_threshold
    raised: bool = False
    notes: list[str] = field(default_factory=list)


class SessionActions:
    def __init__(
        self,
        ctx: MonitorContext,
        *,
        resume_window_s: int = 900,
        role_of: Callable[[str, str], str] | None = None,
    ) -> None:
        self.ctx = ctx
        self.resume_window_s = resume_window_s
        self.role_of = role_of  # (agent_id, principal) -> owner | reviewer, or raises

    # ---------------------------------------------------------------- case + pause

    def act(
        self,
        a: Assessment,
        cfg: SessionConfig,
        rows: Sequence[Mapping[str, Any]],
        *,
        source: str,
    ) -> ActionResult:
        """Apply the case rule and the pause rule to one assessment."""
        res = ActionResult()
        if not (a.case_due or a.pause_due):
            res.skipped = "below_threshold"
            return res
        now = self.ctx.clock.now()
        key = session_ref(a.agent_id, a.session_id)
        st = get_state(self.ctx, STATE_MONITOR, key) or {}
        case_id = st.get("case_id")
        open_row = find_open_case(self.ctx, a.agent_id, CASE_TYPE, case_id) if case_id else None
        if open_row is not None:
            res.case_id, res.skipped = str(case_id), "open_case"
            if a.money_involved:
                res.raised = raise_severity(
                    self.ctx, str(case_id), "high", actor=ACTOR, reason="money tool in session"
                )
        elif st.get("case_at") and now < _ts(st["case_at"]) + timedelta(seconds=cfg.cooldown_s):
            res.skipped = "cooldown"
            res.case_id = case_id
        else:
            res.case_id = self._open(a, cfg, rows, source=source)
            res.case_opened = True
            st = {"case_id": res.case_id, "case_at": format_ts(now), "score_bp": a.score_bp}
            put_state(self.ctx, STATE_MONITOR, key, st)
        if a.pause_due and res.skipped != "cooldown":
            pid, created = self.pause(a, cfg, res.case_id)
            res.pause_id, res.pause_set = pid, created
        return res

    def _open(
        self, a: Assessment, cfg: SessionConfig, rows: Sequence[Mapping[str, Any]], *, source: str
    ) -> str:
        severity = "high" if a.money_involved else "medium"
        tl = timeline_text(rows)
        hits = ", ".join(a.hits) or "none"
        summary = (
            f"Session {a.session_id}: score {a.score_bp} bp, {len(a.hits)} of {a.k} signal hits "
            f"({hits}), {a.turns} turns in {cfg.window_s} s, money moved {a.amount_minor}.\n"
            f"Masked timeline (tool, class, outcome, flags; no text):\n{tl}"
        )
        payload = {
            "session_sha256": sha256_hex(a.session_id),
            "score_bp": a.score_bp,
            "hits": list(a.hits),
            "k": a.k,
            "turns": a.turns,
            "amount_minor": a.amount_minor,
            "money_involved": a.money_involved,
            "window_s": cfg.window_s,
            "first_ts": format_ts(_from_ms(a.first_ms)),
            "last_ts": format_ts(_from_ms(a.last_ms)),
            "timeline_sha256": sha256_hex(list(rows)),
            "config_sha256": sha256_hex(cfg.as_dict()),
            "path": source,
        }
        return open_case(
            self.ctx,
            agent_id=a.agent_id,
            severity=severity,
            case_type=CASE_TYPE,
            summary=summary,
            actor=ACTOR,
            evidence_payload=payload,
        )

    # ---------------------------------------------------------------- pause

    def active_pauses(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        crit: dict[str, Any] = {"status": ACTIVE}
        if agent_id:
            crit["agent_id"] = agent_id
        return self.ctx.state.query("session_control", crit)

    def pause(self, a: Assessment, cfg: SessionConfig, case_id: str | None) -> tuple[str, bool]:
        """Set the session pause. Returns (control_id, created). An active pause stays."""
        now = self.ctx.clock.now()
        for row in self.ctx.state.query(
            "session_control",
            {"agent_id": a.agent_id, "session_id": a.session_id, "status": ACTIVE},
        ):
            if row["expires_at"] > now:
                return str(row["control_id"]), False
        cid = uuid.uuid4().hex
        expires = now + timedelta(seconds=cfg.cooldown_s)
        self.ctx.state.insert(
            "session_control",
            {
                "control_id": cid,
                "session_id": a.session_id,
                "agent_id": a.agent_id,
                "scope": ",".join(cfg.pause_scope),
                "status": ACTIVE,
                "score_bp": a.score_bp,
                "case_id": case_id,
                "created_at": now,
                "expires_at": expires,
            },
        )
        self.ctx.evidence.record(
            "session_pause",
            f"session_pause:{cid}",
            {
                "control_id": cid,
                "agent_id": a.agent_id,
                "session_sha256": sha256_hex(a.session_id),
                "scope": list(cfg.pause_scope),
                "score_bp": a.score_bp,
                "hits": list(a.hits),
                "case_id": case_id,
                "expires_at": format_ts(expires),
                "cooldown_s": cfg.cooldown_s,
                "ts": format_ts(now),
            },
        )
        return cid, True

    def expire(self) -> list[str]:
        """Lift pauses whose cool-down ran out. Records each on the chain. Returns the ids."""
        now = self.ctx.clock.now()
        done = []
        for row in self.active_pauses():
            if row["expires_at"] <= now and self._close(row, EXPIRED, "cooldown", now):
                done.append(str(row["control_id"]))
        return done

    def lift_for_agent(self, agent_id: str, principal: str) -> list[str]:
        """The agent got its two-person resume: its session pauses end with it."""
        now = self.ctx.clock.now()
        return [
            str(r["control_id"])
            for r in self.active_pauses(agent_id)
            if self._close(r, LIFTED, principal, now)
        ]

    def resume(self, agent_id: str, session_id: str, principal: str, reason: str = "") -> dict:
        """Two different people (agent owner + reviewer) within the resume window lift one
        session pause. Raises ``TransitionError`` (HTTP 400) when not allowed."""
        if self.role_of is None:
            raise TransitionError("resume approval is not wired")
        if not principal:
            raise TransitionError("principal is required")
        now = self.ctx.clock.now()
        rows = [
            r
            for r in self.ctx.state.query(
                "session_control",
                {"agent_id": agent_id, "session_id": session_id, "status": ACTIVE},
            )
            if r["expires_at"] > now
        ]
        if not rows:
            raise TransitionError(f"session {session_id} has no active pause")
        row = rows[-1]
        role = self.role_of(agent_id, principal)
        first = row.get("approver_1")
        fresh = (
            first
            and row.get("approver_1_at") is not None
            and now - row["approver_1_at"] <= timedelta(seconds=self.resume_window_s)
        )
        reason_sha = sha256_hex(reason or "")
        if not fresh:
            self._update(
                row,
                {"approver_1": principal, "approver_1_role": role, "approver_1_at": now},
            )
            self.ctx.evidence.record(
                "session_resume_requested",
                f"session_pause:{row['control_id']}",
                {
                    "control_id": row["control_id"],
                    "agent_id": agent_id,
                    "session_sha256": sha256_hex(session_id),
                    "principal": principal,
                    "role": role,
                    "reason_sha256": reason_sha,
                    "window_s": self.resume_window_s,
                    "ts": format_ts(now),
                },
            )
            return {
                "session_id": session_id,
                "status": "pending",
                "needs": "reviewer" if role == "owner" else "owner",
                "changed": False,
            }
        if first == principal:
            raise TransitionError(
                f"{principal} already approved this resume; a second, different person must approve"
            )
        if row.get("approver_1_role") == role:
            raise TransitionError(f"the second approval must come from the other role than {role}")
        self._close(
            row, LIFTED, principal, now, approvers=[first, principal], reason_sha=reason_sha
        )
        return {
            "session_id": session_id,
            "status": "resumed",
            "approvers": [first, principal],
            "changed": True,
        }

    # ---------------------------------------------------------------- helpers

    def _update(self, row: Mapping[str, Any], changes: Mapping[str, Any]) -> None:
        try:
            self.ctx.state.update(
                "session_control",
                {"control_id": row["control_id"]},
                dict(changes),
                int(row["row_version"]),
            )
        except ConcurrencyError as exc:
            raise TransitionError("session pause changed concurrently; retry") from exc

    def _close(
        self,
        row: Mapping[str, Any],
        status: str,
        by: str,
        now: datetime,
        *,
        approvers: Sequence[str] = (),
        reason_sha: str = "",
    ) -> bool:
        try:
            self._update(row, {"status": status, "lifted_by": by, "lifted_at": now})
        except TransitionError:
            return False
        self.ctx.evidence.record(
            "session_resumed" if status == LIFTED else "session_pause_expired",
            f"session_pause:{row['control_id']}",
            {
                "control_id": row["control_id"],
                "agent_id": row["agent_id"],
                "session_sha256": sha256_hex(row["session_id"]),
                "status": status,
                "lifted_by": by,
                "approvers": list(approvers),
                "reason_sha256": reason_sha,
                "ts": format_ts(now),
            },
        )
        return True


def _ts(value: Any) -> datetime:
    from supervisor.monitors.common import as_dt

    return as_dt(value)


def _from_ms(ms: int) -> datetime:
    from datetime import UTC

    return datetime.fromtimestamp(ms / 1000, tz=UTC)


__all__ = [
    "ACTIVE",
    "ACTOR",
    "CASE_TYPE",
    "ActionResult",
    "SessionActions",
    "session_ref",
]
