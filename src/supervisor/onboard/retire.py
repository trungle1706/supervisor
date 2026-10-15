"""Stage 7 Retire (WP19): take an agent out of service and leave the evidence behind.

    python -m supervisor.onboard --retire payments --principal admin.chi --reason "..." --out out

Steps, in this order (a failed step leaves the earlier ones done; run it again to finish):

1. Refuse an unknown agent, and an agent that is RUNNING ("pause it first") or QUARANTINED
   ("release it first"). Only an admin (policy ``admins``) may retire (ADR D03 amendment).
2. Gate state -> RETIRED (one way; the gateway blocks every call from now on).
3. Close every open case of the agent: ``CaseService.close_for_retirement`` (resolution
   ``retired``, no sign-off row; the two-person rule does not apply to a retirement).
4. Final chain entry ``agent_retired`` on the agent lane (strings and integers only; the
   reason enters as a SHA-256).
5. Audit pack (the console builder) copied to ``--out``.
6. Retirement note (markdown, UTF-8) listing the facts and the duties that stay with the bank.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from supervisor.cases import SystemActor, build_case_service
from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import SupervisorError

MAX_REASON = 2000


class RetireError(SupervisorError):
    """The agent cannot be retired (shown to the user as [FAIL])."""


@dataclass(frozen=True)
class RetirementResult:
    agent_id: str
    previous_state: str
    changed: bool
    cases_closed: list[str]
    chain_head: str
    pack_path: Path
    note_path: Path
    verify_ok: bool
    state_history: list[dict[str, str]] = field(default_factory=list)


@dataclass
class _PackCtx:
    """The few attributes ``build_audit_pack`` reads from a console context."""

    settings: Any
    runtime: Any
    cases: Any
    last_verify: dict[str, Any] = field(default_factory=dict)

    @property
    def tables(self) -> Any:
        return self.runtime.adapters.tables

    @property
    def clock(self) -> Any:
        return self.runtime.adapters.clock


def _history(tables: Any, agent_id: str) -> list[dict[str, str]]:
    """State changes of the agent from its chain lane (oldest first)."""
    lane = f"agent:{agent_id}"
    payloads = {int(p["seq"]): p["payload"] for p in tables.query("chain_payload", {"lane": lane})}
    out: list[dict[str, str]] = []
    for e in sorted(tables.query("chain_entry", {"lane": lane}), key=lambda r: r["seq"]):
        if e["record_type"] != "gate_state_change":
            continue
        try:
            body = json.loads(payloads[int(e["seq"])])
        except (KeyError, ValueError):
            continue
        out.append(
            {
                "ts": str(body.get("ts", "")),
                "from": str(body.get("from_state", "")),
                "to": str(body.get("to_state", "")),
                "event": str(body.get("event", "")),
                "principal": str(body.get("principal", "")),
            }
        )
    return out


def render_note(
    *,
    agent: dict[str, Any],
    reason: str,
    principal: str,
    when: str,
    history: list[dict[str, str]],
    cases_closed: list[str],
    chain_head: str,
    pack_name: str,
    verify_ok: bool,
) -> str:
    """Retirement note. UTF-8 markdown; the headings carry a Vietnamese title."""
    lines = [
        f"# Retirement note / Biên bản ngừng sử dụng: {agent['agent_id']}",
        "",
        "## Facts / Thông tin",
        f"- Agent: {agent['agent_id']} ({agent.get('name') or '-'})",
        f"- Owner team: {agent.get('owner_team') or '-'}",
        f"- Owner: {agent.get('owner_user') or '-'}",
        f"- Retired by: {principal}",
        f"- Retired at (UTC): {when}",
        f"- Reason: {reason}",
        "- Final gate state: RETIRED (the gateway blocks every call)",
        "",
        "## State history / Lịch sử trạng thái",
    ]
    lines += [
        f"- {h['ts']}  {h['from']} -> {h['to']}  ({h['event']} by {h['principal']})"
        for h in history
    ] or ["- (none recorded)"]
    lines += ["", f"## Cases closed / Vụ việc đã đóng: {len(cases_closed)}"]
    lines += [f"- {c}  (resolution: retired)" for c in cases_closed] or ["- (no open cases)"]
    lines += [
        "",
        "## Evidence / Bằng chứng",
        f"- Chain head of lane agent:{agent['agent_id']}: {chain_head}",
        f"- Audit pack: {pack_name}",
        f"- Offline verify of the pack: {'OK' if verify_ok else 'FAIL'}",
        "",
        "## Duties that stay with the bank / Nghĩa vụ còn lại của ngân hàng",
        "- Keep the evidence for the retention period: FILL-ME (years; "
        "EVIDENCE_RETENTION_DAYS defaults to 1825 days).",
        "- Deregister the keys and tool credentials of this agent in the bank systems: "
        "FILL-ME (owner and system).",
        "- Tell the owner team and the model-risk function that the agent is out of service: "
        "FILL-ME.",
        "",
    ]
    return "\n".join(lines)


def retire_agent(
    runtime: Any,
    agent_id: str,
    *,
    principal: str,
    reason: str,
    out_dir: Path | str,
    now: datetime | None = None,
) -> RetirementResult:
    """Retire ``agent_id`` on a ``supervisor.wiring.Runtime``. See the module docstring."""
    reason = (reason or "").strip()
    if not reason:
        raise RetireError("a reason is required to retire an agent")
    if len(reason) > MAX_REASON:
        raise RetireError(f"reason is longer than {MAX_REASON} characters")
    if not principal:
        raise RetireError("a principal is required")
    from supervisor.console.auditpack import build_audit_pack
    from supervisor.gateway.state import TransitionError

    out = Path(out_dir)
    adapters = runtime.adapters
    states = runtime.gateway.states
    current = states.get_state(agent_id)
    if current is None:
        raise RetireError(f"unknown agent {agent_id}")
    if current == "RUNNING":
        raise RetireError(f"agent {agent_id} is RUNNING; pause it first")
    try:
        # the principal is a name typed on the CLI, not a verified identity
        res = states.retire(
            agent_id, principal, reason, auth_method="onboard_retire", actor_kind="unverified"
        )
    except TransitionError as exc:
        raise RetireError(str(exc)) from exc

    actor = SystemActor(user_id=principal, auth_method="onboard_retire")
    cases = build_case_service(runtime, system=actor)
    ts = now or adapters.clock.now()
    closed: list[str] = []
    for case in cases.list_cases(agent_id=agent_id):
        if case["status"] == "closed":
            continue
        cases.close_for_retirement(case["case_id"], actor, reason)
        closed.append(case["case_id"])

    lane = f"agent:{agent_id}"
    runtime.chain.record(
        "agent_retired",
        f"agent_retired:{agent_id}:{format_ts(ts)}",
        {
            "agent_id": agent_id,
            "principal": principal,
            "reason_sha256": sha256_hex(reason),
            "cases_closed": len(closed),
            "final_gate_state": "RETIRED",
            "ts": format_ts(ts),
        },
    )
    runtime.chain.commit_root(force=True)
    head = runtime.chain.heads()[lane]

    out.mkdir(parents=True, exist_ok=True)
    ctx = _PackCtx(runtime.settings, runtime, cases)
    pack = build_audit_pack(
        ctx, actor, case_ids=[c["case_id"] for c in cases.list_cases(agent_id=agent_id)]
    )
    pack_path = out / pack.name
    shutil.copyfile(pack.path, pack_path)

    agent = adapters.state.get("agent", {"agent_id": agent_id}) or {"agent_id": agent_id}
    history = _history(adapters.tables, agent_id)
    note_path = out / f"retirement-{agent_id}.md"
    note_path.write_text(
        render_note(
            agent=agent,
            reason=reason,
            principal=principal,
            when=format_ts(ts),
            history=history,
            cases_closed=closed,
            chain_head=head.entry_hash,
            pack_name=pack.name,
            verify_ok=pack.verify_ok,
        ),
        encoding="utf-8",
    )
    return RetirementResult(
        agent_id=agent_id,
        previous_state=str(res.get("from", "RETIRED")),
        changed=bool(res["changed"]),
        cases_closed=closed,
        chain_head=head.entry_hash,
        pack_path=pack_path,
        note_path=note_path,
        verify_ok=pack.verify_ok,
        state_history=history,
    )


__all__ = ["RetireError", "RetirementResult", "retire_agent"]
